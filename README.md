# Segment · Research Annotator

Interactive, research-grade image segmentation/annotation. Click to grow a region,
keep clicking to grow more, switch to **Omit** (or right-click) to shrink it. 13
selectable algorithms across three families. Matte-black glassmorphism UI with dark +
light themes, drag-drop, paste (Ctrl+V) and save (Ctrl+S).

## Stack
- **Backend** — FastAPI + OpenCV + scikit-image (`server/`)
- **Frontend** — React + TypeScript + Vite (`client/`)

## Algorithms
| Family | Algorithms |
| --- | --- |
| Classic interactive | Region growing, Marker watershed, GrabCut, Active contour (snake), Morphological GAC / Chan-Vese |
| Graph & superpixel | Random walker, SLIC superpixels, Felzenszwalb |
| Classic thresholding/edge | Otsu, Adaptive threshold, Canny+morphology, K-means color, Mean shift |

`region_growing`, `slic` and `felzenszwalb` are **incremental** (each click adds/removes
on top of the current mask). The rest **recompute** from all accumulated positive/negative
markers on every click. The registry in `server/segmentation.py` also publishes each
algorithm's parameter schema, so the right-hand controls panel is generated automatically.

## Data
Any `*.zip` in `Data/` is auto-extracted on backend startup. `Data/zoom_15.zip` ships with
sample map tiles. Uploaded/pasted images land in `Data/uploads/`; saved annotations
(mask PNG + COCO-ish polygon JSON) land in `Data/annotations/`.

## Run with Docker (recommended)

Builds the frontend, bundles it into the FastAPI image, and serves everything on **one port (8787)**:

```bash
docker compose up -d --build
# open http://localhost:8787
```

`Data/` is mounted as a volume, so uploaded images and saved annotations persist on the host.
Stop with `docker compose down`.

## Run locally (dev)

Backend (from the repo root):
```bash
pip install -r server/requirements.txt   # add --break-system-packages on PEP-668 systems
uvicorn server.main:app --reload --port 8000
```

Frontend:
```bash
cd client
npm install
npm run dev        # http://localhost:5173 (proxies /api and /images to :8000)
```

## Controls
- **Left-click** — add positive seed (grow)
- **Right-click** or **Alt+Left-click** — add omission seed (shrink)
- **Grow / Omit** toggle (or keys `g` / `o`) sets the default left-click behavior
- **Scroll** — zoom · **Middle-drag** or **Shift+drag** — pan
- **Ctrl/⌘+Z** — undo last point · **Reset** — clear all
- **Ctrl/⌘+S** — save mask + polygons to `Data/annotations/`
- **Drag-drop** an image anywhere, or **Ctrl+V** to paste one
- **☾ / ☀** — toggle dark / light theme
