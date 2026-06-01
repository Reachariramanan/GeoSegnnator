# GeoSegmenter: High-Performance Raster Processing System

## Overview
Full-stack geospatial system for multi-GB GeoTIFF processing with GPU acceleration, ROI handling, and real-time tile rendering.

**Stack:**
- **Backend:** Python (FastAPI, GDAL/rasterio, CuPy/PyTorch, Dask)
- **Frontend:** TypeScript (React, Leaflet, Vite)
- **GPU:** CuPy (NVIDIA) and PyTorch (CUDA)

## Project Structure
```
GeoSegmenter/
├── backend/
│   ├── src/
│   │   ├── raster_io.py          # Windowed reads, COG handling
│   │   ├── roi.py                 # ROI extraction (bbox, polygon, tile)
│   │   ├── segmentation.py        # CPU region growing
│   │   ├── gpu_cupy.py            # CuPy GPU implementation
│   │   ├── gpu_pytorch.py         # PyTorch GPU implementation
│   │   ├── tile_server.py         # FastAPI tile endpoint
│   │   └── cache.py               # LRU tile caching
│   ├── requirements.txt
│   └── main.py
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   │   ├── Map.tsx            # Leaflet map
│   │   │   ├── Controls.tsx       # ROI/segmentation controls
│   │   │   └── Legend.tsx
│   │   ├── App.tsx
│   │   └── main.tsx
│   ├── index.html
│   ├── vite.config.ts
│   ├── package.json
│   └── tsconfig.json
├── README.md
└── data/
    └── sample.tif              # Example COG for testing
```

## Key Constraints
- **No full raster loads** into memory
- **Windowed reads only** (rasterio windows)
- **COG + overviews** required for performance
- **LRU caching** on tile server
- **GPU optional** for >100MB tiles

## Performance Targets
- Tile read: <100ms (cached)
- Segmentation: <500ms (GPU), <2s (CPU)
- COG tiling: 512×512 optimal
