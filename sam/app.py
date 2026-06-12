"""
Standalone FastAPI service that wraps a single SAM (Segment Anything) model
from Hugging Face, selected via SAM_MODEL_ID, for point-prompted (and, for
SAM3, text-prompted) segmentation.

Exposes:
  GET  /health   -> readiness + which model is loaded
  POST /segment  -> { image_path, pos_points, neg_points, text_prompt } -> { mask, area, score }

`image_path` is resolved relative to /app/Data, the same volume the main
annotator service uses for image storage.
"""

import base64
import logging
import os

import cv2
import numpy as np
import torch
from fastapi import FastAPI, HTTPException
from PIL import Image
from pydantic import BaseModel
from typing import List, Optional

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("sam")

DATA_DIR = "/app/Data"
MODEL_ID = os.environ.get("SAM_MODEL_ID", "facebook/sam3")
HF_TOKEN = os.environ.get("HF_TOKEN")

app = FastAPI(title="SAM Segmentation Service")

_state = {"model": None, "processor": None,
          "text_model": None, "text_processor": None}

# Point-prompted (PVS) model/processor classes per model family. Both use the
# same 4D input_points / 3D input_labels shapes and post_process_masks/iou_scores
# API, so the inference code below is shared.
_MODEL_CLASSES = {
    "facebook/sam3": ("Sam3TrackerModel", "Sam3TrackerProcessor"),
    "facebook/sam2.1-hiera-large": ("Sam2Model", "Sam2Processor"),
}


def _load_model():
    import transformers

    model_cls_name, processor_cls_name = _MODEL_CLASSES.get(MODEL_ID, ("AutoModel", "AutoProcessor"))
    try:
        log.info("Loading SAM model %s (%s/%s) ...", MODEL_ID, model_cls_name, processor_cls_name)
        model_cls = getattr(transformers, model_cls_name)
        processor_cls = getattr(transformers, processor_cls_name)
        _state["processor"] = processor_cls.from_pretrained(MODEL_ID, token=HF_TOKEN)
        _state["model"] = model_cls.from_pretrained(MODEL_ID, token=HF_TOKEN).eval()
        log.info("Loaded SAM model %s", MODEL_ID)
    except Exception:
        log.exception("Failed to load %s", MODEL_ID)

    # Text-prompted (open-vocabulary) model, only available for SAM3.
    if MODEL_ID == "facebook/sam3":
        try:
            log.info("Loading SAM3 text-prompt model %s ...", MODEL_ID)
            _state["text_model"] = transformers.Sam3Model.from_pretrained(MODEL_ID, token=HF_TOKEN).eval()
            _state["text_processor"] = transformers.Sam3Processor.from_pretrained(MODEL_ID, token=HF_TOKEN)
            log.info("Loaded SAM3 text-prompt model")
        except Exception:
            log.exception("Failed to load SAM3 text-prompt model")


@app.on_event("startup")
def startup():
    _load_model()


@app.get("/health")
def health():
    return {
        "status": "ok" if _state["model"] is not None else "model_unavailable",
        "model_id": MODEL_ID,
        "text_prompt_available": _state["text_model"] is not None,
    }


class PointXY(BaseModel):
    x: int
    y: int


class SegmentRequest(BaseModel):
    image_path: str
    pos_points: List[PointXY] = []
    neg_points: List[PointXY] = []
    text_prompt: Optional[str] = None


def _resolve_image(image_path: str) -> str:
    full = os.path.normpath(os.path.join(DATA_DIR, image_path))
    if not full.startswith(DATA_DIR):
        raise HTTPException(status_code=400, detail="Invalid image path")
    if not os.path.isfile(full):
        raise HTTPException(status_code=400, detail=f"Image not found: {image_path}")
    return full


def _encode_mask(mask: np.ndarray) -> str:
    ok, png = cv2.imencode(".png", mask * 255)
    if not ok:
        raise HTTPException(status_code=500, detail="Failed to encode mask")
    return base64.b64encode(png.tobytes()).decode("ascii")


@app.post("/segment")
def segment(req: SegmentRequest):
    if req.text_prompt:
        return _segment_text(req)
    return _segment_points(req)


def _segment_points(req: SegmentRequest):
    if _state["model"] is None or _state["processor"] is None:
        raise HTTPException(status_code=503, detail="SAM model not loaded")
    if not req.pos_points:
        raise HTTPException(status_code=400, detail="At least one positive point is required")

    path = _resolve_image(req.image_path)
    image = Image.open(path).convert("RGB")

    points = [[p.x, p.y] for p in req.pos_points] + [[p.x, p.y] for p in req.neg_points]
    labels = [1] * len(req.pos_points) + [0] * len(req.neg_points)

    processor = _state["processor"]
    model = _state["model"]

    inputs = processor(
        images=image,
        input_points=[[points]],
        input_labels=[[labels]],
        return_tensors="pt",
    )

    with torch.no_grad():
        outputs = model(**inputs)

    masks = processor.post_process_masks(outputs.pred_masks.cpu(), inputs["original_sizes"])

    # masks[0]: (num_objects, num_candidates, H, W); pick the best-scoring
    # candidate for our single object prompt.
    candidate_masks = masks[0][0]
    scores = outputs.iou_scores[0][0]
    best = int(torch.argmax(scores).item())
    mask = candidate_masks[best].numpy().astype(np.uint8)

    return {
        "mask": _encode_mask(mask),
        "area": int(mask.sum()),
        "score": float(scores[best].item()),
    }


def _segment_text(req: SegmentRequest):
    if _state["text_model"] is None or _state["text_processor"] is None:
        raise HTTPException(status_code=503, detail="Text-prompted SAM model not loaded")

    path = _resolve_image(req.image_path)
    image = Image.open(path).convert("RGB")

    processor = _state["text_processor"]
    model = _state["text_model"]

    inputs = processor(images=image, text=req.text_prompt, return_tensors="pt")

    with torch.no_grad():
        outputs = model(**inputs)

    results = processor.post_process_instance_segmentation(
        outputs, threshold=0.3, mask_threshold=0.5, target_sizes=inputs["original_sizes"],
    )[0]

    masks = results["masks"]
    scores = results["scores"]
    if masks is None or len(masks) == 0:
        h, w = image.size[1], image.size[0]
        return {"mask": _encode_mask(np.zeros((h, w), np.uint8)), "area": 0, "score": 0.0}

    best = int(torch.argmax(scores).item())
    mask = masks[best].cpu().numpy().astype(np.uint8)

    return {
        "mask": _encode_mask(mask),
        "area": int(mask.sum()),
        "score": float(scores[best].item()),
    }
