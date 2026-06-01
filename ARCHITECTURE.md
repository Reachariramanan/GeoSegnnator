# GeoSegmenter: Architecture & Design

## System Overview

```
┌─────────────────────────────────────────────────────────────┐
│                      Frontend (React + Leaflet)              │
│  ┌─────────────┐  ┌──────────┐  ┌────────────────────────┐  │
│  │ Map Control │  │ROI Select│  │Cache & Segmentation UI │  │
│  └──────┬──────┘  └────┬─────┘  └──────────┬─────────────┘  │
└─────────┼──────────────┼──────────────────┼────────────────┘
          │              │                  │
          └──────────────┼──────────────────┘
                         │
          ┌──────────────▼──────────────────┐
          │   FastAPI Tile Server (8000)   │
          │  /tiles/{z}/{x}/{y}.png        │
          │  /load-raster                  │
          │  /metadata                     │
          │  /tile-cache-stats             │
          └──────────────┬──────────────────┘
          ┌──────────────▼──────────────────┐
          │     GeoTIFF/COG Processor       │
          │  ┌──────────────────────────┐   │
          │  │ raster_io.py (windowed)  │   │
          │  ├──────────────────────────┤   │
          │  │ roi.py (bbox/polygon)    │   │
          │  ├──────────────────────────┤   │
          │  │ segmentation.py (CPU)    │   │
          │  ├──────────────────────────┤   │
          │  │ gpu_cupy.py (CuPy)       │   │
          │  ├──────────────────────────┤   │
          │  │ gpu_pytorch.py (PyTorch) │   │
          │  ├──────────────────────────┤   │
          │  │ cache.py (LRU)           │   │
          │  └──────────────────────────┘   │
          └────────────┬────────────────────┘
                       │
          ┌────────────▼────────────┐
          │  GeoTIFF / Cloud Storage│
          │  (COG preferred)        │
          └─────────────────────────┘
```

## Component Architecture

### 1. Windowed Raster I/O (`raster_io.py`)

**Purpose:** Read large GeoTIFFs without loading entire file into memory.

**Key Classes:**
- `RasterReader`: Context manager for safe file access
  - `metadata`: Returns CRS, bounds, resolution, bands, dtype
  - `read_window()`: Reads geographic region at optional zoom
  - `window_from_bounds()`: Converts geographic bounds to pixel window
  - `pixel_coords_to_geo()`: Reverse transform

**Design Decisions:**
- **Context manager pattern** — Ensures files close properly
- **Lazy metadata** — Only load when accessed
- **Window-based reads** — Never buffer entire raster
- **Resampling support** — Optionally downsample on read

**Memory Profile:**
```
Typical usage:
  - File handle: ~1 MB
  - Single window read (256×256×3): ~200 KB
  - Metadata: <1 KB
  Total: <2 MB per RasterReader instance
```

### 2. ROI Extraction (`roi.py`)

**Purpose:** Convert different ROI formats to geographic bounds and windowed reads.

**Supported Input Types:**

| Input | Method | Use Case |
|-------|--------|----------|
| Bbox | `from_bbox(left, bottom, right, top)` | Rectangle selection |
| Polygon | `from_polygon(geojson)` | Irregular shapes |
| XYZ tile | `from_tile_coords(x, y, z)` | Web Mercator standard |
| Pixel bbox | `from_pixel_coords(row_min, row_max, col_min, col_max)` | Direct pixel indexing |

**Tile Coordinate System:**
```
Web Mercator (EPSG:3857):
  Resolution at zoom z = 40075016.686 / (256 * 2^z) meters
  Tile bounds: 256×256 pixels in Web Mercator
  
Conversion:
  Bounds ↔ Tiles: TileCoordConverter.bounds_to_tiles() / tile_to_bounds()
```

**Polygon Clipping:**
- Rasterizes GeoJSON polygon to mask
- Applies mask to data (zeros outside polygon)
- Preserves data type

### 3. CPU Segmentation (`segmentation.py`)

**Algorithm:** Breadth-First Search (BFS) region growing

**Key Features:**
- Multi-seed support
- 4 and 8 connectivity
- Spectral distance metrics:
  - Euclidean: `√(Σ(Δ_i)²)` — default, rotation-invariant
  - Manhattan: `Σ|Δ_i|` — fast approximation
  - Chebyshev: `max|Δ_i|` — bottleneck distance

**Single-Band Workflow:**
```python
1. Initialize queue with seed pixel
2. For each pixel in queue:
   - Examine 4/8 neighbors
   - If neighbor is unvisited:
     - Compute intensity distance
     - If distance ≤ threshold:
       - Add to region, mark visited
       - Enqueue for expansion
3. Return labeled image
```

**Multispectral Workflow:**
```
Same as single-band but:
  - Distance = spectral distance across all bands
  - Per-band statistics in output
```

**Performance Profile:**
```
512×512 single-band image:
  - BFS: ~50-200ms (threshold-dependent)
  - Memory: ~2 MB
  - Scaling: O(N) where N = region size

Bottleneck: Python loops in inner expansion
Solution: GPU acceleration for large regions
```

### 4. GPU Implementations

#### A. CuPy (`gpu_cupy.py`)

**Strategy:** Vectorized frontier expansion (no recursion)

```python
Iteration:
  1. Dilate frontier using morphological operation
  2. Compute distances for new pixels (vectorized)
  3. Add pixels within threshold to region
  4. Update frontier, repeat
```

**Advantages:**
- No stack overflow (iterative, not recursive)
- Vectorized operations → 2-3× faster
- Memory transfer overhead minimized

**Limitations:**
- Requires CUDA GPU
- Not available on all systems

#### B. PyTorch (`gpu_pytorch.py`)

**Strategy:** Conv2d dilation kernels + iterative expansion

```python
Kernel-based dilation:
  - Use max_pool2d(kernel_size=3, stride=1)
  - Creates "halo" around frontier
  - Faster for 8-connectivity
```

**Advantages:**
- Integrates with PyTorch ecosystem
- Better for downstream deep learning
- Slightly faster dilation kernels

**Limitations:**
- Requires PyTorch install
- Overhead for small regions

**GPU vs CPU Decision:**
```
Region size < 50 MB
  → CPU (overhead dominates)
  
50 MB < Region size < 500 MB
  → CPU competitive, GPU optional
  
Region size > 500 MB
  → GPU (2-3× faster, worth 100ms init)
```

### 5. Tile Server (`tile_server.py`)

**Framework:** FastAPI (async-capable, auto-docs)

**Endpoints:**

| Endpoint | Method | Purpose | Params |
|----------|--------|---------|--------|
| `/load-raster` | POST | Load GeoTIFF | `filepath` (string) |
| `/metadata` | GET | Get raster info | — |
| `/tiles/{z}/{x}/{y}.png` | GET | Fetch tile | `apply_segmentation`, `seeds` |
| `/tile-cache-stats` | GET | Cache metrics | — |
| `/clear-cache` | POST | Reset cache | — |

**Tile Rendering Pipeline:**
```
GET /tiles/10/163/316.png
  ↓
XYZ → bounds (TileCoordConverter)
  ↓
bounds → window (RasterReader)
  ↓
read_window(window, out_shape=(256, 256))
  ↓
[Optional] apply segmentation
  ↓
normalize (0-255) → PIL Image → PNG encode
  ↓
cache tile
  ↓
return PNG bytes
```

**Caching Strategy:**
```
Cache key: f"{z}/{x}/{y}/seg={bool}/seeds={seed_json}"

Example:
  "10/163/316/seg=False" → 196 KB (256×256×3×uint8)
  
LRU eviction:
  500 MB cache ÷ 196 KB/tile ≈ 2,500 tiles max
  Typical panning: ~50 visible + ~200 buffer = fine
```

### 6. LRU Tile Cache (`cache.py`)

**Data Structure:** `OrderedDict` (Python 3.7+)

**Operations:**
- `get(key)` — Move to end (recent)
- `put(key, tile)` — Add, evict if needed
- `clear()` — Reset

**Memory Management:**
```
Put tile:
  1. Check if current_size + tile_size > max_size
  2. While overflow:
     - Pop oldest (first) tile
     - Decrement current_size
  3. Add tile, update current_size
```

**Configuration:**
```python
cache = TileCache(max_size_mb=500)  # Default
cache = TileCache(max_size_mb=2000)  # Large datasets
```

## Data Flow Examples

### Example 1: Windowed Read + Single-Band Segmentation

```
User requests: /tiles/10/163/316.png?apply_segmentation=true&seeds=[[128,128]]

1. TileCoordConverter.tile_to_bounds(163, 316, 10)
   → (left, bottom, right, top) in EPSG:3857

2. RasterReader.window_from_bounds(...)
   → Window(row_off, col_off, width, height)

3. RasterReader.read_window(window, bands=[1], out_shape=(256, 256))
   → numpy(256, 256) uint8 array

4. RegionGrowing.grow(data, seeds=[[128, 128]])
   → labels(256, 256) int32, stats dict

5. Overlay segmentation boundaries on original data
   → rgb(256, 256, 3) uint8

6. Image.fromarray(...) → PIL Image
   → PNG encode → bytes

7. TileCache.put("10/163/316/seg=True", png_bytes)
   → stored for next request
```

### Example 2: Large Multispectral Segmentation (GPU)

```
User ROI: 2048×2048 Sentinel-2 true color
Bands: Red (B4), Green (B3), Blue (B2)

1. RasterReader.read_window(large_window, bands=[4, 3, 2])
   → (3, 2048, 2048) uint16 array
   → ~24 MB

2. Seeds: [[512, 512], [1536, 1536]]

3. CPU segmentation would take: ~5-10s
   GPU segmentation: ~1-2s (worth it!)

4. Decide: size > 10 MB → use GPU

5. CuPyRegionGrowing.grow(data, seeds)
   ↓
   Transfer to VRAM (24 MB)
   ↓
   Frontier expansion (vectorized)
   ↓
   Transfer labels back to CPU (4 MB)
   ↓
   ~1.5s total

6. Return segmentation visualization
```

## Performance Characteristics

### Tile Read Latency

```
First request (cache miss):
  - RasterReader init: ~5 ms
  - Read window: 50-100 ms (depends on disk I/O)
  - Normalize + PNG encode: 10-20 ms
  Total: 65-125 ms

Subsequent requests (cache hit):
  - Deserialize PNG: <1 ms
  Total: <1 ms
```

### Memory Usage

```
Per-tile memory (worst case):
  - RasterReader: 1 MB
  - Single 256×256 tile: 0.2 MB
  - Segmentation labels: 0.25 MB
  - PIL Image buffer: 0.2 MB
  
Total per tile: ~1.65 MB
Cache (500 MB): ~300 tiles resident
```

### GPU Overhead

```
CuPy initialization: 100-500ms (one-time)
Data transfer: ~20 MB/s typical
  - 100 MB upload: 5 ms
  - 100 MB download: 5 ms

Breakeven point: ~500 MB region (1s GPU vs 3s CPU)
```

## Scalability Paths

### 1. Distributed Processing (Dask)

```python
import dask.array as da
from dask_geopandas import GeoDataFrame

# Lazy tile loading
tiles = da.from_delayed(
    [delayed(read_tile)(x, y, z) for x, y, z in tile_list],
    shape=(len(tile_list), 256, 256, 3),
    dtype=np.uint8
)

# Distributed segmentation
results = tiles.map_blocks(segment, dtype=np.int32).compute()
```

### 2. Multi-GPU Segmentation

```python
import torch.distributed as dist

# Distribute seeds across GPUs
seeds_per_gpu = len(seeds) // num_gpus
for gpu_id in range(num_gpus):
    segmenter = PyTorchRegionGrowing(device=f"cuda:{gpu_id}")
    results[gpu_id] = segmenter.grow(data, seeds[gpu_id*n:(gpu_id+1)*n])
```

### 3. Cloud Storage (S3/GCS)

```python
# COG on S3 with HTTP range requests
import rasterio

with rasterio.open("s3://bucket/cog.tif") as src:
    # Only reads required bytes via HTTP GET Range
    data = src.read_window(window)
```

## Security & Production Considerations

### File Access
- **Risk:** Arbitrary file path injection
- **Mitigation:** Whitelist allowed directories, validate paths

```python
ALLOWED_DIRS = ["/data/geotiffs", "/mnt/geospatial"]
user_path = Path(filepath).resolve()
if not any(user_path.is_relative_to(d) for d in ALLOWED_DIRS):
    raise ValueError("File outside allowed directories")
```

### GPU Memory
- **Risk:** DOS via large segmentation requests
- **Mitigation:** Set max region size, implement rate limiting

```python
MAX_REGION_MB = 500
if data.nbytes > MAX_REGION_MB * 1024**2:
    raise ValueError("Region too large")
```

### Tile Cache Poisoning
- **Risk:** Malicious cache keys fill memory
- **Mitigation:** Validate seeds parameter, hash cache keys

```python
cache_key = hashlib.sha256(f"{z}{x}{y}{seeds}".encode()).hexdigest()
```

## Testing Strategy

```
Unit tests:
  - ROI conversion (bbox ↔ pixel ↔ geo)
  - Segmentation correctness (known shapes)
  - Cache eviction behavior

Integration tests:
  - Full tile pipeline (read → segment → render)
  - GPU availability fallback

Load tests:
  - 1,000 concurrent tile requests
  - Cache hit rate > 90%
  - Tail latency p99 < 500ms
```

## Monitoring & Observability

```python
# Log key metrics
logger.info(f"Tile read: {elapsed_ms}ms, cache_hit={hit}")
logger.info(f"GPU memory: {peak_mb}MB, speedup={cpu_time/gpu_time:.1f}×")

# Prometheus metrics (production)
from prometheus_client import Counter, Histogram

tile_requests = Counter(...)
segmentation_duration = Histogram(...)
```
