# GeoSegmenter: 5-Minute Quickstart

## Setup (5 min)

### 1. Backend (2 min)

```bash
cd backend

# Windows
python -m venv venv
venv\Scripts\activate

# macOS/Linux
python -m venv venv
source venv/bin/activate

# Install
pip install -r requirements.txt

# Start server
python -m uvicorn src.tile_server:app --reload --port 8000
```

### 2. Frontend (2 min)

```bash
cd frontend
npm install
npm run dev
```

Open **http://localhost:5173** in browser.

### 3. Load a GeoTIFF (1 min)

**Via UI:**
- In left panel, paste path to GeoTIFF
- Click "Load"
- Map auto-fits to bounds

**Via curl:**
```bash
curl -X POST http://localhost:8000/load-raster \
  -H "Content-Type: application/json" \
  -d '{"filepath": "path/to/file.tif"}'
```

---

## Test Run (Python)

```python
# backend/test_example.py
import sys
sys.path.insert(0, 'src')

from raster_io import RasterReader
from roi import ROIExtractor
from segmentation import RegionGrowing
import numpy as np

# 1. Read region
with RasterReader("path/to/file.tif") as reader:
    bounds = reader.metadata['bounds']
    window = reader.window_from_bounds(
        bounds.left, bounds.bottom,
        bounds.left + 0.1 * (bounds.right - bounds.left),
        bounds.bottom + 0.1 * (bounds.top - bounds.bottom)
    )
    data = reader.read_window(window, bands=[1])

# 2. Segment
segmenter = RegionGrowing(connectivity=4, intensity_threshold=20)
result = segmenter.grow(data, seeds=[(100, 100)])

print(f"Regions found: {len(result.region_stats)}")
print(f"Region sizes: {[s['count'] for s in result.region_stats.values()]}")
```

Run:
```bash
cd backend
source venv/bin/activate
python test_example.py
```

---

## Common Tasks

### Convert GeoTIFF to COG

```python
from backend.src.raster_io import create_cog_from_geotiff

create_cog_from_geotiff("input.tif", "output_cog.tif", tilesize=512)
```

### Get Metadata

```bash
curl http://localhost:8000/metadata | jq
```

### Fetch Tile at (z=10, x=163, y=316)

```bash
curl -o tile.png "http://localhost:8000/tiles/10/163/316.png"
```

### Check GPU

```python
import torch
print(f"CUDA available: {torch.cuda.is_available()}")
print(f"GPU: {torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'N/A'}")
```

### Use GPU Segmentation

```python
from backend.src.gpu_pytorch import PyTorchRegionGrowing
import numpy as np

segmenter = PyTorchRegionGrowing(device="cuda")
data = np.random.randint(0, 255, (512, 512), dtype=np.uint8)
result = segmenter.grow(data, seeds=[(256, 256)])
print(f"GPU time: {result.compute_time:.3f}s")
```

---

## Key Files

| File | Purpose |
|------|---------|
| `backend/src/raster_io.py` | Windowed GeoTIFF reading |
| `backend/src/roi.py` | ROI extraction & coordinate conversion |
| `backend/src/segmentation.py` | CPU region growing |
| `backend/src/gpu_cupy.py` | GPU segmentation (CuPy) |
| `backend/src/gpu_pytorch.py` | GPU segmentation (PyTorch) |
| `backend/src/tile_server.py` | FastAPI tile endpoint |
| `frontend/src/App.tsx` | React root component |
| `frontend/src/components/Map.tsx` | Leaflet map |

---

## Next Steps

1. **Replace sample data** — Use your own GeoTIFF
2. **Tune thresholds** — Adjust `intensity_threshold` in segmentation
3. **Enable GPU** — Install CuPy/PyTorch for speedup
4. **Deploy** — Follow [DEPLOYMENT.md](DEPLOYMENT.md)
5. **Monitor** — Setup logging in [DEPLOYMENT.md](DEPLOYMENT.md)

---

## Troubleshooting

**"No module named 'rasterio'"**
```bash
pip install rasterio --only-binary :all:
# or
conda install rasterio
```

**GDAL/PROJ errors**
```bash
# Windows: use conda
conda install gdal

# macOS: use brew
brew install gdal

# Linux: use apt
sudo apt-get install gdal-bin libgdal-dev
```

**GPU not found**
```bash
# Install PyTorch with CUDA
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu118

# Or CuPy
pip install cupy-cuda11x
```

**Backend not loading tiles**
- Ensure raster path is correct
- Check file is readable: `gdalinfo path/to/file.tif`
- Check tiles API: `curl http://localhost:8000/tiles/10/163/316.png`

---

## Architecture in 30 Seconds

```
Frontend (React + Leaflet)
    ↓ HTTP request
Backend (FastAPI)
    ↓ reads GeoTIFF window
Raster I/O (rasterio)
    ↓ segments data
Segmentation (CPU or GPU)
    ↓ caches tile
Tile Cache (LRU)
    ↓ returns PNG
Frontend displays tile
```

**Key insight:** No full file loads. Only read what you need → zoom/pan fast.

---

## Performance Expectations

| Operation | Time | Hardware |
|-----------|------|----------|
| Load 4GB GeoTIFF | ~5ms | Any (just metadata) |
| Read 256×256 tile | 50-100ms | Typical SSD |
| Render tile (PNG) | 10-20ms | CPU |
| Segmentation (CPU) | 200-500ms | Single core |
| Segmentation (GPU) | 50-200ms | NVIDIA GPU |
| **Total (cached)** | <1ms | Memory |

---

## What Makes This Fast

✅ **Windowed reads** — Never load full raster  
✅ **COG format** — Internal tiling + overviews  
✅ **LRU cache** — Avoid re-renders  
✅ **GPU segmentation** — 2-5× faster for large regions  
✅ **Tile server** — Async, concurrent requests  

---

## Next Depth

- **Distributed:** See [ARCHITECTURE.md](ARCHITECTURE.md) — Dask/multi-GPU
- **Production:** See [DEPLOYMENT.md](DEPLOYMENT.md) — Docker, cloud, monitoring
- **Advanced:** See [README.md](README.md) — Custom workflows, plugins
