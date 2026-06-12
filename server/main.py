import os
import io
import json
import uuid
import base64
import zipfile
import datetime

import numpy as np
import cv2
from fastapi import FastAPI, HTTPException, UploadFile, File, APIRouter
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import List, Optional, Dict, Any

try:
    from server.segmentation import run_algorithm, registry_schema, ALGORITHMS, combine
except ImportError:  # allow `uvicorn main:app` from inside server/
    from segmentation import run_algorithm, registry_schema, ALGORITHMS, combine

# --------------------------------------------------------------------------- #
# Paths (portable)
# --------------------------------------------------------------------------- #
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "Data")
UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")
ANN_DIR = os.path.join(DATA_DIR, "annotations")
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(ANN_DIR, exist_ok=True)


def auto_unzip():
    """Extract any *.zip in Data/ whose target folder doesn't yet exist."""
    for f in os.listdir(DATA_DIR):
        if f.lower().endswith(".zip"):
            zpath = os.path.join(DATA_DIR, f)
            target = os.path.join(DATA_DIR, os.path.splitext(f)[0])
            if not os.path.isdir(target):
                try:
                    with zipfile.ZipFile(zpath) as zf:
                        zf.extractall(DATA_DIR)
                except zipfile.BadZipFile:
                    pass


auto_unzip()

app = FastAPI(title="Segmentation Annotator")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/images", StaticFiles(directory=DATA_DIR), name="images")

# API endpoints live on a router that is mounted at both "" (so `vite` dev with
# proxy rewrite works) and "/api" (so the containerised build, which has no proxy,
# can call /api/* directly). The frontend always calls /api/*.
api = APIRouter()


# --------------------------------------------------------------------------- #
# Models
# --------------------------------------------------------------------------- #
class Point(BaseModel):
    x: int
    y: int


class ProcessRequest(BaseModel):
    image_path: str
    algorithm: str = "region_growing"
    pos_points: List[Point] = []
    neg_points: List[Point] = []
    params: Dict[str, Any] = {}
    prev_mask: Optional[str] = None      # base64 PNG of current mask
    mode: str = "replace"                # replace | add | omit


class SaveRequest(BaseModel):
    image_path: str
    algorithm: str = ""
    boundary: List[List[Point]] = []     # list of polygons
    mask_image: Optional[str] = None     # base64 PNG


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _resolve(image_path: str) -> str:
    full = os.path.normpath(os.path.join(DATA_DIR, image_path.replace("\\", "/")))
    if not full.startswith(DATA_DIR):
        raise HTTPException(status_code=400, detail="Invalid path")
    if not os.path.exists(full):
        raise HTTPException(status_code=404, detail="Image not found")
    return full


def _decode_mask_b64(b64: Optional[str], shape) -> Optional[np.ndarray]:
    if not b64:
        return None
    try:
        raw = b64.split(",", 1)[-1]
        data = np.frombuffer(base64.b64decode(raw), np.uint8)
        m = cv2.imdecode(data, cv2.IMREAD_GRAYSCALE)
        if m is None:
            return None
        if m.shape[:2] != shape[:2]:
            m = cv2.resize(m, (shape[1], shape[0]), interpolation=cv2.INTER_NEAREST)
        return (m > 127).astype(np.uint8)
    except Exception:
        return None


def _mask_to_boundary(mask: np.ndarray):
    """Smooth external contours -> list of polygons (one per contour)."""
    if mask is None or mask.sum() == 0:
        return []
    contours, _ = cv2.findContours(mask.astype(np.uint8), cv2.RETR_EXTERNAL,
                                   cv2.CHAIN_APPROX_NONE)
    polys = []
    for cnt in contours:
        if cv2.contourArea(cnt) < 12:
            continue
        eps = 0.0015 * cv2.arcLength(cnt, True)  # gentle simplification
        approx = cv2.approxPolyDP(cnt, eps, True)
        pts = [{"x": int(p[0][0]), "y": int(p[0][1])} for p in approx]
        if len(pts) >= 3:
            polys.append(pts)
    return polys


def _mask_to_b64(mask: np.ndarray) -> str:
    _, buf = cv2.imencode(".png", (mask.astype(np.uint8) * 255))
    return "data:image/png;base64," + base64.b64encode(buf).decode("utf-8")


# --------------------------------------------------------------------------- #
# Endpoints
# --------------------------------------------------------------------------- #
@api.get("/algorithms")
async def algorithms():
    return {"algorithms": registry_schema()}


@api.get("/files")
async def list_files():
    files = []
    for root, _, names in os.walk(DATA_DIR):
        if os.path.basename(root) == "annotations":
            continue
        for f in names:
            if f.lower().endswith((".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff")):
                rel = os.path.relpath(os.path.join(root, f), DATA_DIR)
                files.append(rel.replace("\\", "/"))
    return {"files": sorted(files)}


@api.post("/upload")
async def upload_image(file: UploadFile = File(...)):
    ext = os.path.splitext(file.filename or "")[1] or ".png"
    name = f"{uuid.uuid4().hex}{ext}"
    path = os.path.join(UPLOAD_DIR, name)
    with open(path, "wb") as fh:
        fh.write(await file.read())
    return {"path": f"uploads/{name}"}


@api.post("/process")
async def process(req: ProcessRequest):
    img = cv2.imread(_resolve(req.image_path))
    if img is None:
        raise HTTPException(status_code=400, detail="Invalid image file")

    if req.algorithm not in ALGORITHMS:
        raise HTTPException(status_code=400, detail=f"Unknown algorithm {req.algorithm}")

    pos = [(p.y, p.x) for p in req.pos_points]
    neg = [(p.y, p.x) for p in req.neg_points]
    prev = _decode_mask_b64(req.prev_mask, img.shape)

    try:
        new_mask, meta = run_algorithm(req.algorithm, img, pos, neg, req.params, prev_mask=prev, image_path=req.image_path)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"{type(e).__name__}: {e}")

    if new_mask is None:
        new_mask = np.zeros(img.shape[:2], np.uint8)

    # Combine with previous mask according to mode (skip for superpixel pickers,
    # which already mutate prev_mask internally).
    spec = ALGORITHMS[req.algorithm]
    if spec.get("needs_prev"):
        mask = (new_mask > 0).astype(np.uint8)
    else:
        mask = combine(prev, new_mask, req.mode)

    if mask is None:
        mask = np.zeros(img.shape[:2], np.uint8)

    return {
        "boundary": _mask_to_boundary(mask),
        "mask_image": _mask_to_b64(mask),
        "area": int(mask.sum()),
        "width": int(img.shape[1]),
        "height": int(img.shape[0]),
        "score": meta.get("score"),
    }


@api.post("/preview")
async def preview(req: ProcessRequest):
    """Like /process but for live hover previews: computes the would-be mask for a
    single hover point against the current committed mask, without the caller
    needing to track this as a history entry."""
    img = cv2.imread(_resolve(req.image_path))
    if img is None:
        raise HTTPException(status_code=400, detail="Invalid image file")

    if req.algorithm not in ALGORITHMS:
        raise HTTPException(status_code=400, detail=f"Unknown algorithm {req.algorithm}")

    spec = ALGORITHMS[req.algorithm]
    if not spec.get("incremental"):
        raise HTTPException(status_code=400, detail="Algorithm does not support hover preview")

    pos = [(p.y, p.x) for p in req.pos_points]
    neg = [(p.y, p.x) for p in req.neg_points]
    prev = _decode_mask_b64(req.prev_mask, img.shape)

    try:
        new_mask, meta = run_algorithm(req.algorithm, img, pos, neg, req.params, prev_mask=prev, image_path=req.image_path)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"{type(e).__name__}: {e}")

    if new_mask is None:
        new_mask = np.zeros(img.shape[:2], np.uint8)

    if spec.get("needs_prev"):
        mask = (new_mask > 0).astype(np.uint8)
    else:
        mask = combine(prev, new_mask, req.mode)

    if mask is None:
        mask = np.zeros(img.shape[:2], np.uint8)

    return {
        "boundary": _mask_to_boundary(mask),
        "area": int(mask.sum()),
        "score": meta.get("score"),
    }


@api.post("/save")
async def save(req: SaveRequest):
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    stem = os.path.splitext(os.path.basename(req.image_path))[0]
    base = f"{stem}_{stamp}"

    # Save mask PNG.
    mask_file = None
    if req.mask_image:
        raw = req.mask_image.split(",", 1)[-1]
        with open(os.path.join(ANN_DIR, base + "_mask.png"), "wb") as fh:
            fh.write(base64.b64decode(raw))
        mask_file = base + "_mask.png"

    # Save polygons JSON (COCO-ish).
    polys = [[[p.x, p.y] for p in poly] for poly in req.boundary]
    doc = {
        "image": req.image_path,
        "algorithm": req.algorithm,
        "created": stamp,
        "polygons": polys,
        "mask_file": mask_file,
    }
    json_name = base + ".json"
    with open(os.path.join(ANN_DIR, json_name), "w") as fh:
        json.dump(doc, fh, indent=2)

    return {"saved": json_name, "mask": mask_file}


# Mount the API at both "" (vite dev proxy strips /api) and "/api" (containerised
# build calls /api directly with no proxy).
app.include_router(api)
app.include_router(api, prefix="/api")


# --------------------------------------------------------------------------- #
# Serve the built frontend (production / container). When client/dist exists we
# serve its assets and fall back to index.html for client-side routing.
# --------------------------------------------------------------------------- #
STATIC_DIR = os.environ.get(
    "STATIC_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
)
if os.path.isdir(STATIC_DIR):
    app.mount("/assets", StaticFiles(directory=os.path.join(STATIC_DIR, "assets")), name="assets")

    @app.get("/")
    async def spa_root():
        return FileResponse(os.path.join(STATIC_DIR, "index.html"))

    @app.get("/{full_path:path}")
    async def spa_fallback(full_path: str):
        candidate = os.path.join(STATIC_DIR, full_path)
        if os.path.isfile(candidate):
            return FileResponse(candidate)
        return FileResponse(os.path.join(STATIC_DIR, "index.html"))


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
