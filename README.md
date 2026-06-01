# GeoSegmenter: High-Performance Raster Processing System

Full-stack system for large-scale GeoTIFF analysis with GPU-accelerated segmentation, windowed I/O, and real-time tile rendering.

**Features:**
- 🌍 **Windowed raster I/O** — no full loads into memory
- 🎯 **Multi-seed region growing** — CPU + GPU (CuPy/PyTorch)
- 🗺️ **XYZ tile server** — on-the-fly COG rendering
- ⚡ **GPU acceleration** — 2-5× speedup for >100MB tiles
- 💾 **LRU tile caching** — 500MB default cache
- 🔄 **Real-time visualization** — Leaflet + React frontend

---

## Quick Start

### Backend Setup

```bash
cd backend

# Create virtual environment
python -m venv venv
source venv/bin/activate  # or: venv\Scripts\activate on Windows

# Install dependencies
pip install -r requirements.txt

# Start server
python -m uvicorn src.tile_server:app --reload --port 8000
```

**Backend API:**
- `POST /load-raster` — Load GeoTIFF (JSON: `{"filepath": "path/to/file.tif"}`)
- `GET /metadata` — Get raster metadata
- `GET /tiles/{z}/{x}/{y}.png` — Fetch tile at XYZ coords
- `GET /tile-cache-stats` — Cache stats
- `POST /clear-cache` — Clear tile cache

### Frontend Setup

```bash
cd frontend

# Install dependencies
npm install

# Development server (http://localhost:5173)
npm run dev

# Build for production
npm run build
```

---

## Architecture

### Backend Stack

**Core Modules:**

1. **`raster_io.py`** — Windowed raster reading
   - `RasterReader`: Context manager for safe COG access
   - `window_from_bounds()`: Geographic → pixel coords
   - `create_cog_from_geotiff()`: Convert to optimized format

2. **`roi.py`** — Region-of-Interest extraction
   - `ROIExtractor.from_bbox()` — Geographic bounding box
   - `ROIExtractor.from_polygon()` — GeoJSON polygon clipping
   - `ROIExtractor.from_tile_coords()` — Web Mercator XYZ
   - `TileCoordConverter` — Bidirectional tile ↔ bounds

3. **`segmentation.py`** — CPU region growing
   - `RegionGrowing.grow()` — Multi-seed 4/8-connectivity
   - Spectral distance: Euclidean, Manhattan, Chebyshev
   - Single-band & multispectral support
   - Per-region statistics

4. **`gpu_cupy.py`** — CuPy GPU implementation
   - Vectorized frontier expansion
   - CUDA array management
   - **No recursion** (avoids stack overflow on large regions)
   - 2-3× CPU speedup on typical satellite imagery

5. **`gpu_pytorch.py`** — PyTorch GPU implementation
   - Conv2d-based dilation kernels
   - Batched multi-seed processing
   - Same API as CuPy version
   - Better for downstream deep learning pipelines

6. **`tile_server.py`** — FastAPI tile endpoint
   - Serves `/tiles/{z}/{x}/{y}.png`
   - Optional segmentation overlay
   - LRU caching with configurable size
   - CORS-enabled for frontend

7. **`cache.py`** — Tile LRU cache
   - Configurable size (default 500MB)
   - Automatic eviction of least-recently-used items
   - Memory-efficient

### Frontend Stack

**React + TypeScript + Leaflet:**

- **`App.tsx`** — State management
- **`Map.tsx`** — Leaflet map with dynamic tile layer
- **`Controls.tsx`** — Raster loading, segmentation, cache management

---

## Usage Examples

### 1. Windowed Raster Reading

```python
from src.raster_io import RasterReader

# Safe context manager usage
with RasterReader("data/satellite.tif") as reader:
    metadata = reader.metadata
    print(f"Bounds: {metadata['bounds']}")
    print(f"CRS: {metadata['crs']}")
    
    # Read geographic region without loading entire file
    bounds = (-120.5, 37.0, -120.0, 37.5)  # [left, bottom, right, top]
    window = reader.window_from_bounds(*bounds)
    
    # Read 3 RGB bands, resample to 512x512
    data = reader.read_window(window, bands=[1, 2, 3], out_shape=(512, 512))
    print(f"Shape: {data.shape}")  # (3, 512, 512)
```

### 2. ROI Extraction

```python
from src.roi import ROIExtractor, TileCoordConverter

# Bounding box
roi = ROIExtractor.from_bbox((-120.5, 37.0, -120.0, 37.5))

# GeoJSON polygon
polygon = {
    "type": "Polygon",
    "coordinates": [[[-120.5, 37.0], [-120.0, 37.0], [-120.0, 37.5], [-120.5, 37.5], [-120.5, 37.0]]]
}
roi = ROIExtractor.from_polygon(polygon)

# XYZ tile coordinates
roi = ROIExtractor.from_tile_coords(x=10, y=20, z=8)

# Convert bounds to list of tiles at zoom level 12
tiles = TileCoordConverter.bounds_to_tiles(-120.5, 37.0, -120.0, 37.5, z=12)
print(f"Tiles: {tiles}")  # [(x0, y0, 12), (x1, y1, 12), ...]
```

### 3. CPU Region Growing

```python
from src.segmentation import RegionGrowing
import numpy as np

# Create segmenter
segmenter = RegionGrowing(
    connectivity=4,                        # 4 or 8 connectivity
    intensity_threshold=25.0,              # max spectral distance
    spectral_distance_metric="euclidean"   # or "manhattan", "chebyshev"
)

# Single-band image
image = np.random.randint(0, 255, (512, 512), dtype=np.uint8)
seeds = [(100, 100), (400, 400)]  # [(row, col), ...]
result = segmenter.grow(image, seeds)

print(f"Labels shape: {result.labels.shape}")  # (512, 512)
print(f"Region stats: {result.region_stats}")

# Multispectral (e.g., RGB)
rgb = np.random.randint(0, 255, (3, 512, 512), dtype=np.uint8)
result = segmenter.grow(rgb, seeds)
```

### 4. GPU Region Growing (CuPy)

```python
from src.gpu_cupy import CuPyRegionGrowing
import numpy as np

segmenter = CuPyRegionGrowing(
    connectivity=4,
    intensity_threshold=25.0,
    spectral_distance_metric="euclidean"
)

# Works with CPU numpy arrays
image = np.random.randint(0, 255, (1024, 1024), dtype=np.uint8)
seeds = [(100, 100), (400, 400)]

result = segmenter.grow(image, seeds)
print(f"GPU time: {result.compute_time:.3f}s")
print(f"Peak memory: {result.memory_peak:.1f}MB")

# Result is automatically transferred back to CPU
labels = result.labels  # numpy array
```

### 5. GPU Region Growing (PyTorch)

```python
from src.gpu_pytorch import PyTorchRegionGrowing
import numpy as np

segmenter = PyTorchRegionGrowing(
    connectivity=4,
    intensity_threshold=25.0,
    device="cuda"  # or "cpu"
)

image = np.random.randint(0, 255, (1024, 1024), dtype=np.uint8)
seeds = [(100, 100), (400, 400)]

result = segmenter.grow(image, seeds)
print(f"GPU time: {result.compute_time:.3f}s")
```

### 6. Tile Server API

```bash
# Load raster
curl -X POST http://localhost:8000/load-raster \
  -H "Content-Type: application/json" \
  -d '{"filepath": "data/satellite.tif"}'

# Get metadata
curl http://localhost:8000/metadata

# Fetch tile (z=10, x=163, y=316)
curl -o tile.png "http://localhost:8000/tiles/10/163/316.png"

# With segmentation overlay
curl -o seg.png "http://localhost:8000/tiles/10/163/316.png?apply_segmentation=true&seeds=[[100,100],[150,150]]"

# Cache stats
curl http://localhost:8000/tile-cache-stats

# Clear cache
curl -X POST http://localhost:8000/clear-cache
```

---

## Performance Optimization

### 1. Cloud Optimized GeoTIFF (COG)

Convert standard GeoTIFF to COG with internal tiling and overviews:

```python
from src.raster_io import create_cog_from_geotiff

# Creates COG with 512×512 internal tiles and overviews
create_cog_from_geotiff("input.tif", "output_cog.tif", tilesize=512)
```

**Benefits:**
- **HTTP range requests** — Only read required bytes from S3/HTTP
- **Overviews** — Fast rendering of zoomed-out tiles
- **Internal tiling** — Optimal I/O pattern (512×512 recommended)

### 2. Tile Cache Strategy

**COG tiles in cache (recommended):**
```
Tile size: 256×256 × 3 bands × uint8 = 196 KB
LRU cache: 500 MB ÷ 196 KB ≈ 2,500 tiles
Typical user: ~50 visible tiles + ~200 in panning buffer
```

**Configure cache:**
```python
from src.cache import TileCache
cache = TileCache(max_size_mb=1000)  # Increase for large datasets
```

### 3. When to Use GPU

**GPU beneficial for:**
- Tile size > 100 MB (entire region growing)
- Multispectral data (>3 bands)
- High similarity threshold (large regions)

**CPU suitable for:**
- Tile size < 50 MB
- Single-band data
- Real-time interactivity (GPU latency overhead)

### 4. Segmentation Thresholds

**Adjust for image characteristics:**

```python
# High-contrast imagery (satellite, medical)
threshold = 15.0  # tighter threshold

# Low-contrast imagery (elevation, acoustic)
threshold = 50.0  # looser threshold

# Multispectral (RGB → compute per-band stddev)
# Set to ~1 × typical stddev for consistent regions
```

### 5. Parallel Tile Rendering

For large regions, render multiple tiles in parallel:

```python
from concurrent.futures import ThreadPoolExecutor
import requests

def fetch_tile(x, y, z):
    return requests.get(f"http://localhost:8000/tiles/{z}/{x}/{y}.png")

with ThreadPoolExecutor(max_workers=4) as executor:
    futures = [executor.submit(fetch_tile, x, y, 12) for x, y, z in tiles]
    results = [f.result() for f in futures]
```

---

## GPU vs CPU Tradeoffs

| Aspect | CPU | GPU (CuPy/PyTorch) |
|--------|-----|-------------------|
| **Startup latency** | <10ms | 100-500ms (CUDA init) |
| **Data transfer** | Native RAM | CPU ↔ GPU overhead |
| **Throughput (1GB tile)** | 5-10s | 2-3s |
| **Memory** | Shared with OS | Dedicated VRAM |
| **Scaling** | Multi-process | Multi-GPU with careful sync |
| **Best for** | <100MB tiles | >1GB regions, batched |

**Decision tree:**
```
Tile > 500 MB?
  YES → GPU (CuPy)
  NO  → Is connectivity==8?
        YES → GPU (PyTorch kernels faster)
        NO  → CPU (BFS sufficient)
```

---

## Frontend Usage

1. **Load raster:** Enter path to GeoTIFF (local or cloud-optimized)
2. **View tiles:** Map auto-loads from backend at current zoom/pan
3. **Segmentation:** Toggle "Enable Region Growing" and click to add seeds
4. **Cache:** Monitor memory usage, clear if needed

**Keyboard shortcuts:**
- `Ctrl+Z` — Undo last seed (planned)
- `Escape` — Clear all seeds (planned)

---

## Troubleshooting

### Import Error: No module named 'cupy'

Install CuPy for your CUDA version:
```bash
# CUDA 11.x
pip install cupy-cuda11x

# CUDA 12.x
pip install cupy-cuda12x

# CPU-only fallback (slower)
pip install cupy-cp312  # CPU backend
```

### Segmentation too slow on GPU

- **Issue:** CUDA initialization overhead dominates
- **Solution:** Process larger batches or stick with CPU for <100MB

### Tile server returns blank/black tiles

- **Issue:** Data type normalization
- **Solution:** Check raster dtype; ensure bands 1-3 are RGB/grayscale

### Memory error during COG creation

- **Issue:** Intermediate overviews consume memory
- **Solution:** Process in chunks using `windowed=True` in rasterio

---

## Future Enhancements

1. **Dask lazy computation** — Process multi-terabyte datasets
2. **WebGL visualization** — Datashader for 100M+ pixels
3. **Distributed segmentation** — Multi-GPU/multi-node via Ray
4. **Export formats** — GeoJSON, Shapefile, COG output
5. **Deep learning** — Semantic segmentation via U-Net

---

## License

MIT
