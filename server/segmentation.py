"""
Research-level interactive segmentation toolkit.

Each algorithm is a function `fn(img_bgr, pos, neg, params) -> uint8 mask (0/1)`
where `pos` / `neg` are lists of (y, x) seed coordinates. Algorithms are exposed
through the `ALGORITHMS` registry, which also carries a UI parameter schema so the
frontend can auto-generate its controls panel.
"""

import os
import base64

import cv2
import numpy as np
import requests
from skimage.segmentation import (
    watershed,
    random_walker,
    slic,
    felzenszwalb,
    active_contour,
    morphological_geodesic_active_contour,
    inverse_gaussian_gradient,
    chan_vese,
)
from skimage.color import rgb2gray
from skimage.filters import gaussian

SAM2_URL = os.environ.get("SAM2_URL", "http://sam2:9000")
SAM3_URL = os.environ.get("SAM3_URL", "http://sam3:9000")


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _gray(image):
    if image.ndim == 3:
        return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    return image


def smooth_mask(mask, ksize=5):
    """Morphologically clean + blur-threshold a binary mask for smooth boundaries."""
    if mask is None:
        return None
    mask = (mask > 0).astype(np.uint8)
    if mask.sum() == 0:
        return mask
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (ksize, ksize))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    # Fill internal holes.
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE,
                            cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (ksize * 3, ksize * 3)))
    # Gaussian + threshold rounds the contour corners.
    blurred = cv2.GaussianBlur(mask.astype(np.float32), (ksize | 1, ksize | 1), 0)
    return (blurred > 0.5).astype(np.uint8)


def combine(prev, new, mode):
    """Combine a freshly computed mask with the previous mask.

    mode == 'add'     -> union (grow)
    mode == 'omit'    -> prev AND NOT new (shrink)
    mode == 'replace' -> just the new mask

    Algorithms are responsible for smoothing their own output (via
    `smooth_mask()` or a lighter equivalent); re-smoothing here would erase
    small precise regions (e.g. region_growing, SAM point prompts).
    """
    new = (new > 0).astype(np.uint8)
    if prev is None or mode == "replace":
        out = new
    elif mode == "add":
        out = cv2.bitwise_or(prev.astype(np.uint8), new)
    elif mode == "omit":
        out = cv2.bitwise_and(prev.astype(np.uint8), cv2.bitwise_not(new * 255) // 255)
    else:
        out = new
    return out


def _label_at(label_img, pts):
    """Return the set of label ids found at the given (y, x) points."""
    ids = set()
    h, w = label_img.shape[:2]
    for (y, x) in pts:
        if 0 <= y < h and 0 <= x < w:
            ids.add(int(label_img[y, x]))
    return ids


# --------------------------------------------------------------------------- #
# Classic interactive
# --------------------------------------------------------------------------- #
def region_growing(image, pos, neg, params):
    """Flood-fill region growing from positive seeds (color-tolerant).

    `threshold` is a normalized 0-1 tolerance, scaled by the image's overall
    contrast (stddev) to set floodFill's loDiff/upDiff. Negative seeds carve
    a small exclusion zone out of the result. `smooth` controls a light
    close+open cleanup (no hole-fill / corner-rounding).
    """
    threshold_frac = float(params.get("threshold", 0.05))
    smooth = bool(params.get("smooth", True))
    gray = _gray(image)
    h, w = gray.shape
    std = float(np.std(gray))
    diff = max(1, int(round(threshold_frac * std * 3)))

    mask = np.zeros((h + 2, w + 2), np.uint8)
    for (y, x) in pos:
        if 0 <= y < h and 0 <= x < w:
            work = gray.copy()  # fresh per seed, avoids cross-seed contamination
            cv2.floodFill(work, mask, (x, y), 1,
                          loDiff=diff, upDiff=diff,
                          flags=8 | cv2.FLOODFILL_MASK_ONLY | cv2.FLOODFILL_FIXED_RANGE)

    out = mask[1:-1, 1:-1].copy()

    # Carve out exclusion zones around negative seeds.
    for (y, x) in neg:
        if 0 <= y < h and 0 <= x < w:
            cv2.circle(out, (x, y), int(params.get("neg_radius", 6)), 0, -1)

    if not smooth:
        return out
    # Light close+open only -- the shared smooth_mask() over-rounds
    # flood-fill boundaries with its hole-fill + Gaussian blur passes.
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    out = cv2.morphologyEx(out, cv2.MORPH_CLOSE, k)
    out = cv2.morphologyEx(out, cv2.MORPH_OPEN, k)
    return out


def watershed_seg(image, pos, neg, params):
    """Marker-controlled watershed on the morphological gradient."""
    gray = _gray(image)
    blur = int(params.get("blur", 3)) | 1
    gradient = cv2.morphologyEx(gray, cv2.MORPH_GRADIENT, np.ones((3, 3), np.uint8))
    gradient = cv2.GaussianBlur(gradient, (blur, blur), 0)

    markers = np.zeros(gray.shape, dtype=np.int32)
    # Border = background.
    markers[0, :] = markers[-1, :] = markers[:, 0] = markers[:, -1] = 2
    for (y, x) in neg:
        if 0 <= y < gray.shape[0] and 0 <= x < gray.shape[1]:
            cv2.circle(markers, (x, y), 3, 2, -1)
    for i, (y, x) in enumerate(pos):
        if 0 <= y < gray.shape[0] and 0 <= x < gray.shape[1]:
            cv2.circle(markers, (x, y), 3, 1, -1)
    if not pos:
        return np.zeros(gray.shape, np.uint8)
    labels = watershed(gradient, markers)
    return smooth_mask((labels == 1).astype(np.uint8))


def grabcut(image, pos, neg, params):
    """Iterative GrabCut seeded with positive (FG) and negative (BG) clicks."""
    if image.ndim != 3:
        image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
    h, w = image.shape[:2]
    if not pos:
        return np.zeros((h, w), np.uint8)
    iters = int(params.get("iters", 5))
    brush = int(params.get("brush", 8))

    gc = np.full((h, w), cv2.GC_PR_BGD, np.uint8)
    # Seed a generous probable-foreground box around positive points.
    ys = [p[0] for p in pos]; xs = [p[1] for p in pos]
    pad = 20
    y0, y1 = max(0, min(ys) - pad), min(h, max(ys) + pad)
    x0, x1 = max(0, min(xs) - pad), min(w, max(xs) + pad)
    gc[y0:y1, x0:x1] = cv2.GC_PR_FGD
    for (y, x) in pos:
        cv2.circle(gc, (x, y), brush, cv2.GC_FGD, -1)
    for (y, x) in neg:
        cv2.circle(gc, (x, y), brush, cv2.GC_BGD, -1)

    bgd, fgd = np.zeros((1, 65), np.float64), np.zeros((1, 65), np.float64)
    try:
        cv2.grabCut(image, gc, None, bgd, fgd, iters, cv2.GC_INIT_WITH_MASK)
    except cv2.error:
        return np.zeros((h, w), np.uint8)
    mask = np.where((gc == cv2.GC_FGD) | (gc == cv2.GC_PR_FGD), 1, 0).astype(np.uint8)
    return smooth_mask(mask)


def snakes(image, pos, neg, params):
    """Active contour (snake) initialised as a circle around the positive seeds."""
    gray = rgb2gray(image[..., ::-1]) if image.ndim == 3 else image.astype(float) / 255
    h, w = gray.shape
    if not pos:
        return np.zeros((h, w), np.uint8)
    cy = np.mean([p[0] for p in pos]); cx = np.mean([p[1] for p in pos])
    radius = float(params.get("radius", 60))
    s = np.linspace(0, 2 * np.pi, 200)
    init = np.array([cy + radius * np.sin(s), cx + radius * np.cos(s)]).T
    img = gaussian(gray, float(params.get("sigma", 2.0)), preserve_range=False)
    snake = active_contour(img, init,
                           alpha=float(params.get("alpha", 0.015)),
                           beta=float(params.get("beta", 10.0)),
                           gamma=0.001)
    mask = np.zeros((h, w), np.uint8)
    poly = np.clip(np.round(snake[:, ::-1]).astype(np.int32), 0, [w - 1, h - 1])
    cv2.fillPoly(mask, [poly], 1)
    return smooth_mask(mask)


def morph_acwe(image, pos, neg, params):
    """Morphological geodesic active contour / Chan-Vese seeded from positive clicks."""
    gray = rgb2gray(image[..., ::-1]) if image.ndim == 3 else image.astype(float) / 255
    h, w = gray.shape
    if not pos:
        return np.zeros((h, w), np.uint8)
    init = np.zeros((h, w), np.uint8)
    for (y, x) in pos:
        if 0 <= y < h and 0 <= x < w:
            cv2.circle(init, (x, y), int(params.get("seed_radius", 15)), 1, -1)
    iters = int(params.get("iters", 80))
    if params.get("variant", "gac") == "chanvese":
        cv = chan_vese(gray, mu=float(params.get("smoothing", 0.25)),
                       max_num_iter=iters, init_level_set=init.astype(bool))
        mask = cv.astype(np.uint8)
        # Keep the component touching the seeds.
    else:
        gimg = inverse_gaussian_gradient(gray)
        mask = morphological_geodesic_active_contour(
            gimg, num_iter=iters, init_level_set=init,
            smoothing=int(params.get("smoothing_iters", 2)),
            balloon=float(params.get("balloon", 1.0))).astype(np.uint8)
    return smooth_mask(_keep_seeded(mask, pos))


def _keep_seeded(mask, pos):
    """Keep only connected components that contain a positive seed."""
    if mask.sum() == 0:
        return mask
    n, lbl = cv2.connectedComponents(mask.astype(np.uint8))
    keep = _label_at(lbl, pos) - {0}
    if not keep:
        return mask
    return np.isin(lbl, list(keep)).astype(np.uint8)


# --------------------------------------------------------------------------- #
# Graph & superpixel
# --------------------------------------------------------------------------- #
def random_walker_seg(image, pos, neg, params):
    """Random walker with positive (=1) and negative (=2) seed labels."""
    gray = _gray(image).astype(np.float64) / 255.0
    h, w = gray.shape
    if not pos:
        return np.zeros((h, w), np.uint8)
    markers = np.zeros((h, w), np.int32)
    brush = int(params.get("brush", 4))
    for (y, x) in neg:
        if 0 <= y < h and 0 <= x < w:
            cv2.circle(markers, (x, y), brush, 2, -1)
    for (y, x) in pos:
        if 0 <= y < h and 0 <= x < w:
            cv2.circle(markers, (x, y), brush, 1, -1)
    if 2 not in markers:
        # Random walker needs at least two labels; seed border as background.
        markers[0, :] = markers[-1, :] = markers[:, 0] = markers[:, -1] = 2
    try:
        labels = random_walker(gray, markers, beta=float(params.get("beta", 130)),
                               mode="bf")
    except Exception:
        return np.zeros((h, w), np.uint8)
    return smooth_mask((labels == 1).astype(np.uint8))


def _superpixel_pick(label_img, pos, neg, prev_mask):
    """Toggle whole superpixels in/out of the mask based on clicks."""
    h, w = label_img.shape
    mask = np.zeros((h, w), np.uint8) if prev_mask is None else (prev_mask > 0).astype(np.uint8)
    for sid in _label_at(label_img, pos):
        mask[label_img == sid] = 1
    for sid in _label_at(label_img, neg):
        mask[label_img == sid] = 0
    return mask


def slic_seg(image, pos, neg, params, prev_mask=None):
    rgb = image[..., ::-1] if image.ndim == 3 else cv2.cvtColor(image, cv2.COLOR_GRAY2RGB)
    segments = slic(rgb, n_segments=int(params.get("n_segments", 400)),
                    compactness=float(params.get("compactness", 10)),
                    start_label=1)
    return smooth_mask(_superpixel_pick(segments, pos, neg, prev_mask))


def felzenszwalb_seg(image, pos, neg, params, prev_mask=None):
    rgb = image[..., ::-1] if image.ndim == 3 else cv2.cvtColor(image, cv2.COLOR_GRAY2RGB)
    segments = felzenszwalb(rgb, scale=float(params.get("scale", 200)),
                            sigma=float(params.get("sigma", 0.6)),
                            min_size=int(params.get("min_size", 50)))
    return smooth_mask(_superpixel_pick(segments, pos, neg, prev_mask))


# --------------------------------------------------------------------------- #
# Classic thresholding / edge
# --------------------------------------------------------------------------- #
def _component_under_pos(binary, pos):
    """From a binary image keep the connected component(s) under positive seeds."""
    binary = (binary > 0).astype(np.uint8)
    if not pos or binary.sum() == 0:
        return binary
    return _keep_seeded(binary, pos)


def otsu(image, pos, neg, params):
    gray = _gray(image)
    _, th = cv2.threshold(gray, 0, 1, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    if params.get("invert"):
        th = 1 - th
    return smooth_mask(_component_under_pos(th, pos))


def adaptive_threshold(image, pos, neg, params):
    gray = _gray(image)
    block = int(params.get("block", 35)) | 1
    th = cv2.adaptiveThreshold(gray, 1, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                               cv2.THRESH_BINARY, block, int(params.get("C", 5)))
    if params.get("invert"):
        th = 1 - th
    return smooth_mask(_component_under_pos(th, pos))


def canny_morph(image, pos, neg, params):
    gray = _gray(image)
    edges = cv2.Canny(gray, int(params.get("low", 50)), int(params.get("high", 150)))
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (int(params.get("close", 5)),) * 2)
    closed = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, k)
    filled = closed.copy()
    h, w = filled.shape
    ff = np.zeros((h + 2, w + 2), np.uint8)
    cv2.floodFill(filled, ff, (0, 0), 255)
    filled = cv2.bitwise_not(filled)
    region = cv2.bitwise_or(closed, filled)
    return smooth_mask(_component_under_pos(region // 255 if region.max() > 1 else region, pos))


def kmeans_color(image, pos, neg, params):
    img = image if image.ndim == 3 else cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
    Z = lab.reshape(-1, 3).astype(np.float32)
    K = int(params.get("K", 5))
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 20, 1.0)
    _, labels, _ = cv2.kmeans(Z, K, None, criteria, 3, cv2.KMEANS_PP_CENTERS)
    label_img = labels.reshape(image.shape[:2])
    chosen = _label_at(label_img, pos) if pos else set()
    mask = np.isin(label_img, list(chosen)).astype(np.uint8) if chosen else np.zeros(image.shape[:2], np.uint8)
    if neg:
        for sid in _label_at(label_img, neg):
            mask[label_img == sid] = 0
    return smooth_mask(_component_under_pos(mask, pos) if pos else mask)


def meanshift(image, pos, neg, params):
    img = image if image.ndim == 3 else cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
    shifted = cv2.pyrMeanShiftFiltering(img, int(params.get("sp", 15)), int(params.get("sr", 30)))
    gray = cv2.cvtColor(shifted, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape
    if not pos:
        return np.zeros((h, w), np.uint8)
    tol = int(params.get("tol", 12))
    work = gray.copy()
    ffmask = np.zeros((h + 2, w + 2), np.uint8)
    for (y, x) in pos:
        if 0 <= y < h and 0 <= x < w:
            cv2.floodFill(work, ffmask, (x, y), 1, loDiff=tol, upDiff=tol,
                          flags=8 | cv2.FLOODFILL_MASK_ONLY)
    return smooth_mask(ffmask[1:-1, 1:-1])


# --------------------------------------------------------------------------- #
# Foundation models (proxied to a separate SAM service)
# --------------------------------------------------------------------------- #
def _sam_segment(sam_url, image, pos, neg, params, image_path=None):
    """Proxy to a SAM container's /segment endpoint. Prompted with point
    clicks (label 1 = foreground/pos, label 0 = background/neg), or with a
    free-text prompt (`params["text_prompt"]`) for open-vocabulary
    segmentation (SAM3 only). Returns (mask, meta) where meta carries the
    model's confidence score."""
    h, w = image.shape[:2]
    text_prompt = (params.get("text_prompt") or "").strip()
    if not pos and not text_prompt:
        return np.zeros((h, w), np.uint8), {}
    payload = {
        "image_path": image_path,
        "pos_points": [{"x": int(x), "y": int(y)} for (y, x) in pos],
        "neg_points": [{"x": int(x), "y": int(y)} for (y, x) in neg],
        "text_prompt": text_prompt or None,
    }
    try:
        r = requests.post(f"{sam_url}/segment", json=payload, timeout=60)
        r.raise_for_status()
    except requests.RequestException:
        return np.zeros((h, w), np.uint8), {}
    data = r.json()
    mask_png = base64.b64decode(data["mask"])
    mask = cv2.imdecode(np.frombuffer(mask_png, np.uint8), cv2.IMREAD_GRAYSCALE)
    if mask is None:
        return np.zeros((h, w), np.uint8), {}
    meta = {"score": data["score"]} if "score" in data else {}
    return (mask > 0).astype(np.uint8), meta


def sam2_segment(image, pos, neg, params, image_path=None):
    """Proxy to the `sam2` container (facebook/sam2.1-hiera-large, point prompts only)."""
    return _sam_segment(SAM2_URL, image, pos, neg, params, image_path=image_path)


def sam3_segment(image, pos, neg, params, image_path=None):
    """Proxy to the `sam3` container (facebook/sam3, point + text prompts)."""
    return _sam_segment(SAM3_URL, image, pos, neg, params, image_path=image_path)


# --------------------------------------------------------------------------- #
# Registry
# --------------------------------------------------------------------------- #
def _p(name, type_, default, **kw):
    return {"name": name, "type": type_, "default": default, **kw}


ALGORITHMS = {
    # ---- Classic interactive ----
    "region_growing": {
        "name": "Region Growing",
        "family": "Classic interactive",
        "incremental": True,
        "fn": region_growing,
        "params": [_p("threshold", "float", 0.05, min=0.0, max=1.0, step=0.005),
                   _p("smooth", "bool", True),
                   _p("neg_radius", "int", 6, min=1, max=30)],
    },
    "watershed": {
        "name": "Marker Watershed",
        "family": "Classic interactive",
        "incremental": False,
        "fn": watershed_seg,
        "params": [_p("blur", "int", 3, min=1, max=15)],
    },
    "grabcut": {
        "name": "GrabCut",
        "family": "Classic interactive",
        "incremental": False,
        "fn": grabcut,
        "params": [_p("iters", "int", 5, min=1, max=15), _p("brush", "int", 8, min=2, max=30)],
    },
    "snakes": {
        "name": "Active Contour (Snake)",
        "family": "Classic interactive",
        "incremental": False,
        "fn": snakes,
        "params": [_p("radius", "int", 60, min=10, max=200),
                   _p("sigma", "float", 2.0, min=0.5, max=6, step=0.5),
                   _p("alpha", "float", 0.015, min=0.001, max=0.1, step=0.001),
                   _p("beta", "float", 10.0, min=0.1, max=30, step=0.5)],
    },
    "morph_acwe": {
        "name": "Morphological GAC / Chan-Vese",
        "family": "Classic interactive",
        "incremental": False,
        "fn": morph_acwe,
        "params": [_p("variant", "select", "gac", options=["gac", "chanvese"]),
                   _p("iters", "int", 80, min=10, max=300),
                   _p("seed_radius", "int", 15, min=3, max=50),
                   _p("balloon", "float", 1.0, min=-2, max=2, step=0.5)],
    },
    # ---- Graph & superpixel ----
    "random_walker": {
        "name": "Random Walker",
        "family": "Graph & superpixel",
        "incremental": False,
        "fn": random_walker_seg,
        "params": [_p("beta", "int", 130, min=10, max=400), _p("brush", "int", 4, min=1, max=15)],
    },
    "slic": {
        "name": "SLIC Superpixels",
        "family": "Graph & superpixel",
        "incremental": True,
        "needs_prev": True,
        "fn": slic_seg,
        "params": [_p("n_segments", "int", 400, min=50, max=2000),
                   _p("compactness", "float", 10.0, min=1, max=50, step=1)],
    },
    "felzenszwalb": {
        "name": "Felzenszwalb",
        "family": "Graph & superpixel",
        "incremental": True,
        "needs_prev": True,
        "fn": felzenszwalb_seg,
        "params": [_p("scale", "float", 200.0, min=20, max=1000, step=10),
                   _p("sigma", "float", 0.6, min=0.1, max=3, step=0.1),
                   _p("min_size", "int", 50, min=10, max=500)],
    },
    # ---- Classic thresholding / edge ----
    "otsu": {
        "name": "Otsu Threshold",
        "family": "Classic thresholding/edge",
        "incremental": False,
        "fn": otsu,
        "params": [_p("invert", "bool", False)],
    },
    "adaptive_threshold": {
        "name": "Adaptive Threshold",
        "family": "Classic thresholding/edge",
        "incremental": False,
        "fn": adaptive_threshold,
        "params": [_p("block", "int", 35, min=3, max=151),
                   _p("C", "int", 5, min=-20, max=20),
                   _p("invert", "bool", False)],
    },
    "canny_morph": {
        "name": "Canny + Morphology",
        "family": "Classic thresholding/edge",
        "incremental": False,
        "fn": canny_morph,
        "params": [_p("low", "int", 50, min=0, max=255),
                   _p("high", "int", 150, min=0, max=255),
                   _p("close", "int", 5, min=1, max=25)],
    },
    "kmeans_color": {
        "name": "K-Means Color",
        "family": "Classic thresholding/edge",
        "incremental": False,
        "fn": kmeans_color,
        "params": [_p("K", "int", 5, min=2, max=12)],
    },
    "meanshift": {
        "name": "Mean Shift",
        "family": "Classic thresholding/edge",
        "incremental": False,
        "fn": meanshift,
        "params": [_p("sp", "int", 15, min=2, max=40),
                   _p("sr", "int", 30, min=5, max=80),
                   _p("tol", "int", 12, min=1, max=60)],
    },
    # ---- Foundation models ----
    "sam2": {
        "name": "SAM 2 (prompted)",
        "family": "Foundation models",
        "incremental": True,
        "needs_image_path": True,
        "fn": sam2_segment,
        "params": [],
    },
    "sam3": {
        "name": "SAM 3 (prompted)",
        "family": "Foundation models",
        "incremental": True,
        "needs_image_path": True,
        "fn": sam3_segment,
        "params": [_p("text_prompt", "string", "")],
    },
}


def run_algorithm(key, image, pos, neg, params, prev_mask=None, image_path=None):
    """Dispatch to the registered algorithm, passing prev_mask/image_path only
    when the algorithm declares it needs them.

    Returns (mask, meta) where meta is a dict of extra info (e.g. confidence
    `score`); algorithms that don't return meta default to {}.
    """
    spec = ALGORITHMS.get(key)
    if spec is None:
        raise KeyError(f"Unknown algorithm '{key}'")
    fn = spec["fn"]
    kwargs = {}
    if spec.get("needs_prev"):
        kwargs["prev_mask"] = prev_mask
    if spec.get("needs_image_path"):
        kwargs["image_path"] = image_path
    result = fn(image, pos, neg, params, **kwargs)
    if isinstance(result, tuple):
        return result
    return result, {}


def registry_schema():
    """JSON-serialisable description of every algorithm for the frontend."""
    out = []
    for key, spec in ALGORITHMS.items():
        out.append({
            "key": key,
            "name": spec["name"],
            "family": spec["family"],
            "incremental": spec.get("incremental", False),
            "params": spec["params"],
        })
    return out
