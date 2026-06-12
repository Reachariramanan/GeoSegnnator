# Plan: GeoSAM (LangSAM) + Scharr Edge-Guided Graph-Cut + SAM3 text-prompt fix

## Context

SAM3 text prompts do little on satellite imagery: the model is trained on
natural-image vocabulary, and `_segment_text` in `sam/app.py` silently returns an
empty mask when nothing clears its hardcoded `threshold=0.3 / mask_threshold=0.5`.
For overhead/remote-sensing imagery the better tools are (a) a remote-sensing-aware
text model and (b) edge/boundary-driven segmentation rather than "find the object".

This plan adds **two new segmentation options** (keeping SAM2/SAM3 intact) and a
**diagnostic + configurability fix** to SAM3:

- **A. Scharr Edge-Guided Graph-Cut** — a new "Edge-guided" family algorithm that
  snaps boundaries to image gradients (ChatGPT's plan), using a real graph-cut +
  CRF refinement pass (user chose to add the proper deps).
- **B. GeoSAM** — a new "Foundation models" option backed by **samgeo's `LangSAM`**
  (GroundingDINO + SAM, text-prompted, remote-sensing oriented), in its own
  container. The local toolkit already lives at
  `/home/hariramanan/Annotator/segment-geospatial`.
- **C. SAM3 text-prompt diagnostic + env-configurable thresholds** so we can see
  whether satellite prompts return low-confidence masks vs. nothing.

All changes are additive and non-breaking. **No frontend changes are required** —
the dropdown (`Toolbar.tsx`), params panel (`ParamsPanel.tsx`), and types
(`api.ts`) are all driven by the backend `registry_schema()`; new families and
params surface automatically.

---

## A. Scharr Edge-Guided Graph-Cut (server-side, new family)

### Dependencies (user chose "real graph-cut/CRF")
Add to `server/requirements.txt`:
```
PyMaxflow
pydensecrf
```
Note: `pydensecrf` builds from source (Cython/Eigen). If the wheel/build fails in
the `annotator` image, fall back to `pydensecrf` from
`git+https://github.com/lucasb-eyer/pydensecrf.git`. The `annotator` Dockerfile
must rebuild to pick these up.

### New function in `server/segmentation.py`
Add a new section after the graph/superpixel block (after `felzenszwalb_seg`,
~line 298). Reuse existing helpers `_gray` and `smooth_mask`; import `maxflow`
and `pydensecrf` lazily inside the function so a missing/failed build degrades to
a graceful zero-mask instead of breaking import of the whole module.

Pipeline (matches ChatGPT's plan, dependency-backed):
1. `gray = _gray(image)`; optional Gaussian blur (`sigma` param).
2. **Scharr** magnitude: `gx = cv2.Scharr(gray, CV_64F,1,0)`, `gy = ...0,1`,
   `grad = sqrt(gx^2+gy^2)`, normalize to `[0,1]`.
3. Build seed-based unary costs from `pos`/`neg` clicks (large fixed cost to pin
   seeds to fg/bg, neutral elsewhere). If no `pos`, return zeros.
4. **Graph cut** with `maxflow.Graph[float]`: 4-connected grid, edge weights
   `w = exp(-k * grad)` (the `edge_weight` param `k`) so cuts are cheap along
   strong edges. Solve, read `get_grid_segments` → binary mask.
5. **CRF refinement**: `pydensecrf.DenseCRF2D` with the original RGB image,
   unary from the graph-cut mask, a few inference iters → refined mask.
6. `return smooth_mask(mask)`.

Non-incremental (like `random_walker_seg`); the API's `combine()` already handles
add/omit across clicks. Wrap maxflow/CRF in try/except → on any failure return
the graph-cut mask (or zeros) so the endpoint never 500s.

### Registry entry (`ALGORITHMS` in `segmentation.py`)
Insert a new block before "Classic thresholding / edge":
```python
    # ---- Edge-guided ----
    "scharr_graphcut": {
        "name": "Scharr Edge-Guided Graph-Cut",
        "family": "Edge-guided",
        "incremental": False,
        "fn": scharr_graphcut_seg,
        "params": [
            _p("edge_weight", "float", 8.0, min=0.0, max=30.0, step=0.5),
            _p("sigma", "float", 1.0, min=0.0, max=5.0, step=0.5),
            _p("crf_iters", "int", 5, min=0, max=20),
        ],
    },
```
`registry_schema()` and the dispatcher pick this up automatically; the new
"Edge-guided" family appears as a Toolbar optgroup with no frontend edits.

### Risk
`maxflow`/`pydensecrf` over multi-megapixel satellite tiles is CPU/memory heavy.
Mitigation: cap working resolution (downscale before graph-cut, upscale mask).
Add a guarded max-pixel downscale in the function. Flag for benchmarking.

---

## B. GeoSAM via samgeo `LangSAM` (new container + Foundation-models option)

GeoSAM = samgeo's **`LangSAM`** (`segment-geospatial/samgeo/text_sam.py`,
`class LangSAM`): GroundingDINO + SAM, **text-prompted**, remote-sensing oriented.
`predict(image_pil, text_prompt, box_threshold, text_threshold, return_results=True)`
returns `(masks, boxes, phrases, logits)`. Weights auto-download from HF. It uses
`segment_anything` + `groundingdino-py` (NOT HF transformers), so it needs its own
container — it cannot reuse `sam/app.py`.

### New container: `geosam/` (mirrors the `sam/` service contract)
Create:
- **`geosam/app.py`** — FastAPI service exposing the **same contract** as
  `sam/app.py`: `GET /health` and
  `POST /segment {image_path, pos_points, neg_points, text_prompt} ->
  {mask(base64 PNG), area, score}`. Implementation:
  - On startup, instantiate `LangSAM()` (add `segment-geospatial` to path or pip
    install it).
  - In `/segment`: resolve `image_path` under `/app/Data` (reuse the
    `_resolve_image` pattern from `sam/app.py:98-104`), open as RGB PIL.
  - Call `LangSAM.predict(image, text_prompt, box_threshold, text_threshold,
    return_results=True)`; union the returned per-object masks (or pick the
    highest-logit one) into a single binary mask; `score` = max logit.
  - Encode mask as base64 PNG (reuse `_encode_mask` pattern from
    `sam/app.py:107-111`). Empty/no-detection → zero mask, area 0, score 0.
  - Thresholds via env: `GEOSAM_BOX_THRESHOLD` (default 0.24),
    `GEOSAM_TEXT_THRESHOLD` (default 0.24) — GroundingDINO defaults are lower
    than SAM3's and better for overhead imagery.
- **`geosam/Dockerfile`** — based on a CUDA/CPU torch base; pip install
  `segment-geospatial` (pulls `segment_anything`, `groundingdino-py`, `rasterio`,
  etc.), `fastapi`, `uvicorn[standard]`, `opencv-python-headless`. (The samgeo
  repo's own Dockerfile is a Jupyter image — do not reuse it; write a slim API
  Dockerfile modeled on `sam/Dockerfile`.) Expose 9000, run uvicorn.
- **`geosam/requirements.txt`** — `segment-geospatial`, `fastapi`,
  `uvicorn[standard]`, `opencv-python-headless`, `pillow`, `numpy`. (torch comes
  via segment-geospatial / base image.)

### `server/segmentation.py` proxy + registry
- Add env near lines 29-30:
  ```python
  GEOSAM_URL = os.environ.get("GEOSAM_URL", "http://geosam:9000")
  ```
- Add proxy fn after `sam3_segment` (~line 417), reusing `_sam_segment`:
  ```python
  def geosam_segment(image, pos, neg, params, image_path=None):
      """Proxy to the `geosam` container (samgeo LangSAM: GroundingDINO + SAM,
      text-prompted, remote-sensing oriented)."""
      return _sam_segment(GEOSAM_URL, image, pos, neg, params, image_path=image_path)
  ```
- Registry entry in the Foundation-models block (after `sam3`, line 557):
  ```python
      "geosam": {
          "name": "GeoSAM (remote sensing, text)",
          "family": "Foundation models",
          "incremental": True,
          "needs_image_path": True,
          "fn": geosam_segment,
          "params": [_p("text_prompt", "string", "")],
      },
  ```
  Reuses the entire `_sam_segment` proxy (lines 380-407) and text plumbing.

### `docker-compose.yml`
- In `annotator.environment` add `GEOSAM_URL: "http://geosam:9000"`; in
  `annotator.depends_on` add `- geosam`.
- New `geosam` service built from `geosam/Dockerfile`, with
  `./Data:/app/Data:ro` and a `geosam-weights:/root/.cache` volume (HF +
  torch hub cache for GroundingDINO/SAM weights). Add `geosam-weights:` to the
  top-level `volumes:` block.

### Risk
First run downloads GroundingDINO + SAM checkpoints (large); image build is heavy
(`groundingdino-py` compiles CUDA ops — confirm CPU-only build works, else pin a
CPU-friendly version). GeoSAM is **text-only** here (point prompts ignored), which
matches its strength; the `text_prompt` param drives it.

---

## C. SAM3 text-prompt diagnostic + threshold fix (`sam/app.py`)

Edit `_segment_text` (lines 162-194) only. Non-breaking; defaults preserve current
behavior.

- Add module-level env constants (near lines 29-31):
  ```python
  SAM3_TEXT_THRESHOLD = float(os.environ.get("SAM3_TEXT_THRESHOLD", "0.3"))
  SAM3_MASK_THRESHOLD = float(os.environ.get("SAM3_MASK_THRESHOLD", "0.5"))
  ```
- Before `post_process_instance_segmentation`, log raw score count + top-5 scores
  (guarded `getattr` on `outputs` for `pred_scores`/`logits`, wrapped in
  try/except so unknown attr names never break the request).
- Pass `threshold=SAM3_TEXT_THRESHOLD, mask_threshold=SAM3_MASK_THRESHOLD`.
- After post-processing, log how many masks passed the threshold before the
  empty-mask early return.
- Optionally surface `SAM3_TEXT_THRESHOLD` (commented) in the `sam3` service env
  in compose for easy tuning without rebuilds.

This lets us distinguish "low-confidence masks below threshold" (lower
`SAM3_TEXT_THRESHOLD` via env + restart) from "no grounding at all" (a model/prompt
problem GeoSAM is meant to solve).

---

## Files touched

- `server/segmentation.py` — Scharr graph-cut fn + registry entry (A);
  `GEOSAM_URL`, `geosam_segment` proxy + registry entry (B).
- `server/requirements.txt` — `PyMaxflow`, `pydensecrf` (A).
- `geosam/app.py`, `geosam/Dockerfile`, `geosam/requirements.txt` — **new** (B).
- `docker-compose.yml` — `geosam` service, `GEOSAM_URL`, `depends_on`,
  `geosam-weights` volume (B).
- `sam/app.py` — env thresholds + diagnostic logging in `_segment_text` (C).
- **No frontend changes** (registry-driven).

---

## Verification

### Build & run
```
docker compose build annotator sam3        # A (annotator) + C (sam3)
docker compose build geosam                # B (first build is heavy)
docker compose up -d annotator sam2 sam3 geosam
```

### A — Scharr Edge-Guided Graph-Cut
- UI → family "Edge-guided" → "Scharr Edge-Guided Graph-Cut".
- Positive click inside a region bounded by a clear edge (field/road/shoreline);
  confirm the boundary snaps to the gradient. Negative click constrains it.
- Sweep `edge_weight` (higher = hug edges harder), `sigma`, `crf_iters`.
- No positive seed → empty mask, no error.
- `curl http://localhost:8787/<algorithms-endpoint>` shows the `scharr_graphcut`
  entry. Confirm `annotator` logs show no maxflow/CRF import errors.

### B — GeoSAM
- `docker compose logs -f geosam` → startup loads LangSAM (GroundingDINO + SAM).
- `curl http://geosam:9000/health` (via `docker compose exec annotator` or host
  port) → `status: ok`.
- UI → "Foundation models" → "GeoSAM (remote sensing, text)"; enter a satellite
  prompt (e.g. "building", "road", "field", "water"); confirm a mask returns with
  a `score`. Compare against SAM3 on the same prompt/image.

### C — SAM3 logs
```
docker compose logs -f sam3
```
- Trigger a text prompt on a satellite image. Expect
  `SAM3 text '<prompt>': N raw scores, top=[...]` and
  `N masks passed threshold`.
- If top raw scores are ~0.1–0.25 with 0 passing → set `SAM3_TEXT_THRESHOLD=0.1`
  (compose env), `docker compose up -d sam3`, retry. If raw count ~0 → grounding
  failure (use GeoSAM instead).

---

## Open questions / risks (summary)
1. **pydensecrf build** may need the git source install if no wheel for py3.12.
2. **graph-cut/CRF perf** on large tiles — add a max-pixel downscale guard.
3. **GroundingDINO CPU build** in the geosam image — confirm `groundingdino-py`
   installs without a GPU; pin a CPU-compatible version if needed.
4. **First-run weight downloads** for GeoSAM are large; cached in `geosam-weights`.
