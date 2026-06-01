"""
FastAPI tile server for COG rendering.
Serves XYZ tiles with optional segmentation overlay.
"""

# Force rasterio's bundled PROJ database (avoids conflicts with stale PostgreSQL proj.db on Windows)
import os
import sys
try:
    import rasterio as _ras_init
    _ras_proj = os.path.join(os.path.dirname(_ras_init.__file__), "proj_data")
    if os.path.isdir(_ras_proj):
        os.environ["PROJ_LIB"] = _ras_proj
        os.environ["PROJ_DATA"] = _ras_proj
    _ras_gdal = os.path.join(os.path.dirname(_ras_init.__file__), "gdal_data")
    if os.path.isdir(_ras_gdal):
        os.environ["GDAL_DATA"] = _ras_gdal
except Exception:
    pass

from fastapi import FastAPI, HTTPException, Query, UploadFile, File, BackgroundTasks
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import numpy as np
from PIL import Image
import io
import logging
import tempfile
import shutil
from pathlib import Path
from typing import List, Literal, Optional, Tuple
import json

import rasterio
from rasterio.warp import transform_bounds, reproject, calculate_default_transform, Resampling
from rasterio.transform import from_bounds as transform_from_bounds
from rasterio.windows import from_bounds as window_from_bounds
from scipy import ndimage

from .raster_io import RasterReader
from .roi import ROIExtractor, TileCoordConverter
from .segmentation import RegionGrowing
from .cache import TileCache

# Algorithm core ported from app/ — see plan-what-and-all-curious-volcano.md
from .algo.registry import get_formula, resolve_required_bands, shortlist as indices_shortlist
from .algo.io import read_band_arrays
from .algo.segmentation_algo import region_grow
from .algo.progressive_segmentation import (
    progressive_region_grow_with_ROI,
    compute_multiple_indices,
)
from .algo.symbology import (
    apply_ramp,
    apply_custom_ramp,
    rgba_to_png_bytes,
    get_ramps,
    get_index_defaults,
    get_default_for_index,
    resolve_range,
    compute_stats,
)
from .algo.index_cache import IndexCache

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

app = FastAPI(title="GeoSegmenter Tile Server")

# CORS for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global state
RASTER_PATH: Optional[Path] = None
tile_cache = TileCache(max_size_mb=500)
index_cache = IndexCache()
raster_metadata = None

# Preview-resolution cap used by precompute & render endpoints
PREVIEW_MAX_SIDE = 2048

# Search paths for resolving filenames
DATA_DIRS = [
    Path(__file__).parent.parent.parent / "data",
    Path.cwd() / "data",
    Path.home() / "Downloads",
    Path.home() / "Desktop",
]


class LoadRasterRequest(BaseModel):
    filepath: str


@app.on_event("startup")
async def startup_event():
    """Initialize on startup."""
    logger.info("GeoSegmenter Tile Server started")
    logger.info(f"Data search paths: {[str(d) for d in DATA_DIRS]}")


@app.get("/health")
async def health():
    """Health check."""
    return {"status": "ok"}


def _resolve_path(filepath: str) -> Optional[Path]:
    """Resolve a filepath - try as absolute, then search DATA_DIRS for matching filename."""
    # Try as absolute path first
    path = Path(filepath)
    if path.is_absolute() and path.exists():
        return path

    # Try relative to cwd
    if path.exists():
        return path.resolve()

    # Search by filename in data dirs
    filename = path.name
    for data_dir in DATA_DIRS:
        if data_dir.exists():
            candidate = data_dir / filename
            if candidate.exists():
                return candidate
            # Also recursive search
            for found in data_dir.rglob(filename):
                return found

    return None


def _get_metadata_dict(reader_metadata: dict) -> dict:
    """Convert raster metadata to a JSON-serializable dict with WGS84 bounds."""
    bounds = reader_metadata["bounds"]
    src_crs = reader_metadata["crs"]

    # Reproject bounds to WGS84 (EPSG:4326) for Leaflet
    try:
        if src_crs is not None:
            wgs84_bounds = transform_bounds(
                src_crs, "EPSG:4326",
                bounds.left, bounds.bottom, bounds.right, bounds.top,
                densify_pts=21,
            )
            left_lon, bottom_lat, right_lon, top_lat = wgs84_bounds
        else:
            # Assume bounds are already in lat/lng if no CRS
            left_lon, bottom_lat, right_lon, top_lat = (
                bounds.left, bounds.bottom, bounds.right, bounds.top
            )
    except Exception as e:
        logger.warning(f"Could not reproject bounds: {e}")
        left_lon, bottom_lat, right_lon, top_lat = (
            bounds.left, bounds.bottom, bounds.right, bounds.top
        )

    return {
        "crs": str(src_crs) if src_crs else "unknown",
        "bounds": {
            "left": float(left_lon),
            "bottom": float(bottom_lat),
            "right": float(right_lon),
            "top": float(top_lat),
        },
        "native_bounds": {
            "left": float(bounds.left),
            "bottom": float(bounds.bottom),
            "right": float(bounds.right),
            "top": float(bounds.top),
        },
        "width": int(reader_metadata["width"]),
        "height": int(reader_metadata["height"]),
        "bands": int(reader_metadata["count"]),
        "dtype": str(reader_metadata["dtype"]),
    }


@app.post("/load-raster")
async def load_raster(req: LoadRasterRequest, background_tasks: BackgroundTasks):
    """Load a GeoTIFF file by path or filename."""
    global RASTER_PATH, raster_metadata

    resolved = _resolve_path(req.filepath)
    if resolved is None:
        raise HTTPException(
            status_code=404,
            detail=f"File not found: '{req.filepath}'. Searched: {[str(d) for d in DATA_DIRS]}"
        )

    try:
        with RasterReader(str(resolved)) as reader:
            raster_metadata = reader.metadata
        old_path = str(RASTER_PATH) if RASTER_PATH is not None else None
        RASTER_PATH = resolved
        if old_path and old_path != str(resolved):
            index_cache.clear_for(old_path)
        meta_dict = _get_metadata_dict(raster_metadata)
        logger.info(f"Loaded {resolved}. WGS84 bounds: {meta_dict['bounds']}")
        background_tasks.add_task(_precompute_all_indices, str(resolved))
        return {"status": "ok", "metadata": meta_dict, "path": str(resolved)}
    except Exception as e:
        logger.error(f"Failed to load raster: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/upload-raster")
async def upload_raster(background_tasks: BackgroundTasks, file: UploadFile = File(...)):
    """Upload a GeoTIFF file directly."""
    global RASTER_PATH, raster_metadata

    # Save to data dir
    data_dir = DATA_DIRS[0]
    data_dir.mkdir(parents=True, exist_ok=True)
    dest = data_dir / file.filename

    with open(dest, "wb") as f:
        shutil.copyfileobj(file.file, f)

    try:
        with RasterReader(str(dest)) as reader:
            raster_metadata = reader.metadata
        old_path = str(RASTER_PATH) if RASTER_PATH is not None else None
        RASTER_PATH = dest
        if old_path and old_path != str(dest):
            index_cache.clear_for(old_path)
        meta_dict = _get_metadata_dict(raster_metadata)
        logger.info(f"Uploaded and loaded {dest}. WGS84 bounds: {meta_dict['bounds']}")
        background_tasks.add_task(_precompute_all_indices, str(dest))
        return {"status": "ok", "metadata": meta_dict, "path": str(dest)}
    except Exception as e:
        logger.error(f"Failed to load uploaded raster: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/metadata")
async def get_metadata():
    """Get loaded raster metadata."""
    if raster_metadata is None:
        raise HTTPException(status_code=400, detail="No raster loaded")
    return _get_metadata_dict(raster_metadata)


@app.get("/preview.png")
async def get_preview(max_size: int = Query(2048)):
    """Render the entire raster as a single PNG reprojected to WGS84.

    Returned image is aligned to the WGS84 bounds reported by /metadata,
    so the frontend can place it as an L.imageOverlay directly.
    """
    if RASTER_PATH is None:
        raise HTTPException(status_code=400, detail="No raster loaded")

    try:
        with rasterio.open(str(RASTER_PATH)) as src:
            src_crs = src.crs or rasterio.CRS.from_epsg(4326)

            # WGS84 destination bounds
            dst_left, dst_bottom, dst_right, dst_top = transform_bounds(
                src_crs, "EPSG:4326",
                src.bounds.left, src.bounds.bottom, src.bounds.right, src.bounds.top,
                densify_pts=21,
            )

            # Compute output size preserving aspect ratio
            geo_width = dst_right - dst_left
            geo_height = dst_top - dst_bottom
            aspect = geo_width / geo_height if geo_height > 0 else 1.0

            if aspect >= 1:
                out_w = max_size
                out_h = max(1, int(round(max_size / aspect)))
            else:
                out_h = max_size
                out_w = max(1, int(round(max_size * aspect)))

            # Destination transform (WGS84)
            from rasterio.transform import from_bounds as transform_from_bounds
            dst_transform = transform_from_bounds(
                dst_left, dst_bottom, dst_right, dst_top, out_w, out_h
            )

            num_bands = min(3, src.count)
            band_indices = list(range(1, num_bands + 1))

            # Reproject each band into a WGS84 array
            dst_data = np.zeros((num_bands, out_h, out_w), dtype=np.float32)
            for i, b in enumerate(band_indices):
                src_band = src.read(b)
                reproject(
                    source=src_band,
                    destination=dst_data[i],
                    src_transform=src.transform,
                    src_crs=src_crs,
                    dst_transform=dst_transform,
                    dst_crs="EPSG:4326",
                    resampling=Resampling.bilinear,
                )

        # Stretch to 0-255 per band using 2-98 percentile
        rgb = np.zeros((num_bands, out_h, out_w), dtype=np.uint8)
        alpha = np.zeros((out_h, out_w), dtype=np.uint8)
        any_valid = np.zeros((out_h, out_w), dtype=bool)

        for i in range(num_bands):
            band = dst_data[i]
            valid = band > 0
            any_valid |= valid
            if valid.any():
                p2, p98 = np.percentile(band[valid], [2, 98])
                if p98 > p2:
                    scaled = np.clip((band - p2) / (p98 - p2) * 255, 0, 255)
                else:
                    scaled = np.clip(band, 0, 255)
                rgb[i] = scaled.astype(np.uint8)

        alpha[any_valid] = 255

        # Expand single/dual band to RGB
        if num_bands == 1:
            rgb = np.repeat(rgb, 3, axis=0)
        elif num_bands == 2:
            rgb = np.concatenate([rgb, rgb[:1]], axis=0)

        # Compose RGBA: (H, W, 4)
        rgba = np.concatenate([rgb[:3], alpha[np.newaxis]], axis=0)
        img_array = np.transpose(rgba, (1, 2, 0))
        img = Image.fromarray(img_array, mode="RGBA")

        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=False)
        buf.seek(0)
        logger.info(f"Preview rendered: {out_w}x{out_h}, {len(buf.getvalue()) / 1024:.0f}KB")
        return StreamingResponse(buf, media_type="image/png")

    except Exception as e:
        logger.error(f"Preview render failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


def _tile_bounds_3857(x: int, y: int, z: int) -> Tuple[float, float, float, float]:
    """XYZ tile -> bounds in Web Mercator (EPSG:3857)."""
    import math
    n = 2 ** z
    # Web Mercator extent
    extent = 20037508.342789244
    tile_size = (2 * extent) / n
    left = -extent + x * tile_size
    right = left + tile_size
    top = extent - y * tile_size
    bottom = top - tile_size
    return left, bottom, right, top


def _empty_png() -> bytes:
    """Return a transparent 256x256 PNG."""
    img = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


@app.get("/tiles/{z}/{x}/{y}.png")
async def get_tile(
    z: int,
    x: int,
    y: int,
    apply_segmentation: bool = Query(False),
    seeds: Optional[str] = Query(None),
) -> StreamingResponse:
    """
    Get tile at XYZ coordinates. Properly reprojects raster CRS to Web Mercator.
    """
    if RASTER_PATH is None:
        raise HTTPException(status_code=400, detail="No raster loaded")

    cache_key = f"{z}/{x}/{y}/seg={apply_segmentation}"
    cached = tile_cache.get(cache_key)
    if cached is not None:
        return StreamingResponse(io.BytesIO(cached), media_type="image/png")

    try:
        # Tile bounds in Web Mercator
        tile_left, tile_bottom, tile_right, tile_top = _tile_bounds_3857(x, y, z)

        with rasterio.open(str(RASTER_PATH)) as src:
            src_crs = src.crs
            if src_crs is None:
                src_crs = rasterio.CRS.from_epsg(4326)

            # Reproject tile bounds (3857) to source CRS to find the window
            try:
                src_left, src_bottom, src_right, src_top = transform_bounds(
                    "EPSG:3857", src_crs,
                    tile_left, tile_bottom, tile_right, tile_top,
                    densify_pts=21,
                )
            except Exception as e:
                logger.warning(f"Bounds transform failed: {e}")
                return StreamingResponse(io.BytesIO(_empty_png()), media_type="image/png")

            # Check overlap with raster extent
            raster_bounds = src.bounds
            if (src_right < raster_bounds.left or src_left > raster_bounds.right or
                src_top < raster_bounds.bottom or src_bottom > raster_bounds.top):
                empty = _empty_png()
                tile_cache.put(cache_key, empty)
                return StreamingResponse(io.BytesIO(empty), media_type="image/png")

            # Clip to raster extent
            src_left = max(src_left, raster_bounds.left)
            src_right = min(src_right, raster_bounds.right)
            src_bottom = max(src_bottom, raster_bounds.bottom)
            src_top = min(src_top, raster_bounds.top)

            if src_right <= src_left or src_top <= src_bottom:
                empty = _empty_png()
                return StreamingResponse(io.BytesIO(empty), media_type="image/png")

            # Read window from source
            window = window_from_bounds(
                src_left, src_bottom, src_right, src_top, src.transform
            )
            num_bands = min(3, src.count)
            band_indices = list(range(1, num_bands + 1))

            try:
                src_data = src.read(
                    band_indices,
                    window=window,
                    out_shape=(num_bands, 256, 256),
                    resampling=Resampling.bilinear,
                    boundless=True,
                    fill_value=0,
                )
            except Exception as e:
                logger.warning(f"Read window failed: {e}")
                return StreamingResponse(io.BytesIO(_empty_png()), media_type="image/png")

        # Normalize to 0-255
        if src_data.dtype == np.uint8:
            data = src_data
        else:
            data = np.zeros_like(src_data, dtype=np.uint8)
            for i in range(src_data.shape[0]):
                band = src_data[i].astype(np.float32)
                mask = band > 0
                if mask.any():
                    valid = band[mask]
                    p2, p98 = np.percentile(valid, [2, 98])
                    if p98 > p2:
                        scaled = np.clip((band - p2) / (p98 - p2) * 255, 0, 255)
                    else:
                        scaled = np.clip(band, 0, 255)
                    data[i] = scaled.astype(np.uint8)

        # Pad/expand bands to RGB if needed
        if data.shape[0] == 1:
            data = np.repeat(data, 3, axis=0)
        elif data.shape[0] == 2:
            data = np.concatenate([data, data[:1]], axis=0)

        # Apply segmentation if requested
        if apply_segmentation and seeds:
            try:
                seed_list = json.loads(seeds)
                seg = RegionGrowing(connectivity=4, intensity_threshold=20.0)
                result = seg.grow(data[0], seed_list)
                data = _overlay_segmentation(data, result.labels)
            except Exception as e:
                logger.warning(f"Segmentation failed: {e}")

        # Convert to PNG (RGB)
        img_array = np.transpose(data[:3], (1, 2, 0))
        img = Image.fromarray(img_array, mode="RGB")

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        tile_bytes = buf.getvalue()

        tile_cache.put(cache_key, tile_bytes)
        return StreamingResponse(io.BytesIO(tile_bytes), media_type="image/png")

    except Exception as e:
        logger.error(f"Tile request failed for {z}/{x}/{y}: {e}", exc_info=True)
        return StreamingResponse(io.BytesIO(_empty_png()), media_type="image/png")


@app.get("/tile-cache-stats")
async def cache_stats():
    """Get tile cache statistics."""
    return tile_cache.stats()


@app.post("/clear-cache")
async def clear_cache():
    """Clear tile cache."""
    tile_cache.clear()
    return {"status": "cache cleared"}


def _overlay_segmentation(data: np.ndarray, labels: np.ndarray) -> np.ndarray:
    """Overlay segmentation boundaries on image."""
    from scipy import ndimage

    # Find boundaries
    boundaries = ndimage.sobel(labels.astype(float))
    boundaries = boundaries > 0.1

    # Create output
    output = data.copy() if data.ndim == 3 else np.stack([data, data, data])

    # Red overlay on boundaries
    if output.ndim == 3:
        output[0, boundaries] = 255  # Red channel
        output[1, boundaries] = 50
        output[2, boundaries] = 50

    return output


# ---------------------------------------------------------------------------
# Spectral-index segmentation endpoints (algorithm core ported from app/)
# ---------------------------------------------------------------------------


class SeedPoint(BaseModel):
    row: int
    col: int
    kind: Literal["pos", "neg"] = "pos"


class IndexSegRequest(BaseModel):
    index_name: str = "ndvi"
    threshold: float = 0.5
    seeds: List[SeedPoint]
    max_size: int = 2048


class ProgressiveSegRequest(BaseModel):
    index_name: str = "ndvi"
    threshold: float = 0.5
    seeds: List[SeedPoint]
    max_iterations: int = 10
    roi_dimming: float = 0.3
    max_size: int = 2048


class TrainFormulaRequest(BaseModel):
    index_names: List[str]
    threshold: float = 0.5
    seeds: List[SeedPoint]


def _split_seeds(seeds: List[SeedPoint]) -> Tuple[List[Tuple[int, int]], List[Tuple[int, int]]]:
    pos = [(s.row, s.col) for s in seeds if s.kind == "pos"]
    neg = [(s.row, s.col) for s in seeds if s.kind == "neg"]
    return pos, neg


def _compute_index_map_for_loaded_raster(index_name: str):
    """Read required bands from RASTER_PATH and compute the named index.

    Returns (index_map, meta) where meta has 'profile', 'transform', 'crs'.
    """
    if RASTER_PATH is None:
        raise HTTPException(status_code=400, detail="No raster loaded")

    try:
        formula = get_formula(index_name)
    except KeyError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    try:
        band_map, _ = resolve_required_bands(formula.required_bands)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"{index_name}: {exc}")

    try:
        band_arrays, meta = read_band_arrays(
            str(RASTER_PATH), band_map.values(), apply_nodata_mask=True
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Band resolution failed for {index_name}: {exc}. "
                   "Check data/superdove_metadata_report.json files[] entry exists for this TIFF.",
        )

    ordered_args = [band_arrays[name] for name in band_map.values()]
    params = formula.params or {}
    index_map = formula.compute(*ordered_args, **params)
    return index_map, meta


def _downsampled_shape(width: int, height: int, max_side: int) -> Tuple[int, int]:
    """Pick (out_w, out_h) so the longer side equals max_side, preserving aspect."""
    if width <= 0 or height <= 0:
        return max(1, width), max(1, height)
    if max(width, height) <= max_side:
        return width, height
    if width >= height:
        out_w = max_side
        out_h = max(1, int(round(height * max_side / width)))
    else:
        out_h = max_side
        out_w = max(1, int(round(width * max_side / height)))
    return out_w, out_h


def _scaled_transform(orig_transform, src_w: int, src_h: int, out_w: int, out_h: int):
    """Scale a rasterio Affine so pixel size matches the downsampled grid."""
    sx = src_w / max(1, out_w)
    sy = src_h / max(1, out_h)
    return orig_transform * orig_transform.scale(sx, sy)


def _read_band_arrays_downsampled(image_path: str, band_names, out_w: int, out_h: int, apply_nodata_mask: bool = True):
    """Read selected bands at a downsampled resolution.

    Mirrors algo.io.read_band_arrays but reads with out_shape so each band is
    decimated to roughly preview resolution. Returns (band_arrays, meta) where
    meta carries the *scaled* transform so downstream warping aligns correctly.
    """
    from .algo.io import scale_reflectance, mask_nodata
    from .algo.bands import get_band_index_by_name_for_path

    band_names = list(band_names)
    band_arrays = {}

    with rasterio.open(image_path) as src:
        descriptions = [d.lower() if d else "" for d in src.descriptions]
        name_to_index = {name: idx + 1 for idx, name in enumerate(descriptions) if name}
        if not name_to_index:
            name_to_index = get_band_index_by_name_for_path(image_path)

        for name in band_names:
            band_index = name_to_index.get(name)
            if band_index is None:
                raise ValueError(f"Band not found: {name}")
            band = src.read(
                band_index,
                out_shape=(out_h, out_w),
                resampling=Resampling.average,
            ).astype("float32")
            band_arrays[name] = scale_reflectance(band)

        scaled_tx = _scaled_transform(src.transform, src.width, src.height, out_w, out_h)
        meta = {
            "transform": scaled_tx,
            "crs": src.crs,
            "nodata": src.nodata,
            "width": out_w,
            "height": out_h,
            "src_width": src.width,
            "src_height": src.height,
        }

        if apply_nodata_mask and src.nodata is not None:
            band_arrays = mask_nodata(band_arrays, src.nodata)

        return band_arrays, meta


def _compute_index_map_downsampled(image_path: str, index_name: str, max_side: int = PREVIEW_MAX_SIDE):
    """Compute one index at preview resolution. Returns (index_map: float32, meta)."""
    formula = get_formula(index_name)
    band_map, _ = resolve_required_bands(formula.required_bands)

    with rasterio.open(image_path) as src:
        out_w, out_h = _downsampled_shape(src.width, src.height, max_side)

    band_arrays, meta = _read_band_arrays_downsampled(
        image_path, band_map.values(), out_w, out_h, apply_nodata_mask=True
    )
    ordered = [band_arrays[name] for name in band_map.values()]
    params = formula.params or {}
    index_map = formula.compute(*ordered, **params).astype("float32")
    return index_map, meta


def _precompute_all_indices(raster_path: str) -> None:
    """Background job: compute every supported/approx index at preview resolution
    and stash it in the IndexCache so /render/index serves them instantly.
    """
    try:
        catalog = indices_shortlist()
    except Exception as exc:
        logger.error(f"precompute: indices_shortlist failed: {exc}")
        return

    targets = [
        entry["name"]
        for entry in catalog
        if entry.get("status") in ("supported", "supported_approx")
    ]
    if not targets:
        logger.info("precompute: no supported indices to cache")
        return

    index_cache.init_progress(raster_path, len(targets))
    logger.info(f"precompute: starting {len(targets)} indices for {raster_path}")

    for name in targets:
        if RASTER_PATH is None or str(RASTER_PATH) != raster_path:
            logger.info(f"precompute: aborting — raster changed during job ({raster_path})")
            break
        try:
            arr, meta = _compute_index_map_downsampled(raster_path, name, PREVIEW_MAX_SIDE)
            stats = compute_stats(arr, 2.0, 98.0)
            index_cache.put(
                raster_path,
                name,
                arr,
                {
                    "transform": meta["transform"],
                    "crs": meta["crs"],
                    "stats": stats,
                    "width": meta["width"],
                    "height": meta["height"],
                },
            )
            index_cache.mark_done(raster_path, name)
        except Exception as exc:
            logger.warning(f"precompute: {name} failed: {exc}")
            index_cache.mark_error(raster_path, name, str(exc))

    index_cache.finish_progress(raster_path)
    logger.info(
        f"precompute: finished. ready={len(index_cache.ready_names(raster_path))}/{len(targets)}"
    )


def _warp_to_wgs84_png(source: np.ndarray, src_transform, src_crs, max_size: int = 2048) -> bytes:
    """Warp a 2D mask / float array (or RGBA HxWx4) into WGS84 and encode as PNG.

    The output PNG is sized so the longer side equals max_size, matching the
    aspect ratio of the reprojected WGS84 bounding box. The frontend overlays
    it on the raster's reported WGS84 bounds (same convention as /preview.png).
    """
    src_crs = src_crs or rasterio.CRS.from_epsg(4326)

    # Compute source bounds from transform + array shape
    if source.ndim == 3:
        src_h, src_w = source.shape[:2]
    else:
        src_h, src_w = source.shape
    src_left, src_top = src_transform * (0, 0)
    src_right, src_bottom = src_transform * (src_w, src_h)

    dst_left, dst_bottom, dst_right, dst_top = transform_bounds(
        src_crs, "EPSG:4326",
        min(src_left, src_right), min(src_top, src_bottom),
        max(src_left, src_right), max(src_top, src_bottom),
        densify_pts=21,
    )

    geo_w = dst_right - dst_left
    geo_h = dst_top - dst_bottom
    aspect = geo_w / geo_h if geo_h > 0 else 1.0
    if aspect >= 1:
        out_w = max_size
        out_h = max(1, int(round(max_size / aspect)))
    else:
        out_h = max_size
        out_w = max(1, int(round(max_size * aspect)))

    dst_transform = transform_from_bounds(dst_left, dst_bottom, dst_right, dst_top, out_w, out_h)

    if source.ndim == 3 and source.shape[2] == 4:
        # RGBA — reproject each channel separately
        out = np.zeros((out_h, out_w, 4), dtype=np.uint8)
        for c in range(4):
            channel = np.ascontiguousarray(source[:, :, c])
            dst_channel = np.zeros((out_h, out_w), dtype=channel.dtype)
            reproject(
                source=channel,
                destination=dst_channel,
                src_transform=src_transform,
                src_crs=src_crs,
                dst_transform=dst_transform,
                dst_crs="EPSG:4326",
                resampling=Resampling.nearest,
            )
            out[:, :, c] = dst_channel
        img = Image.fromarray(out, mode="RGBA")
    else:
        # 2D mask — produce RGBA where mask>0 is colored & opaque, rest transparent
        src_2d = source.astype(np.float32)
        dst_2d = np.zeros((out_h, out_w), dtype=np.float32)
        reproject(
            source=src_2d,
            destination=dst_2d,
            src_transform=src_transform,
            src_crs=src_crs,
            dst_transform=dst_transform,
            dst_crs="EPSG:4326",
            resampling=Resampling.nearest,
        )
        rgba_arr = apply_ramp(dst_2d, "mask", 0.0, 1.0, transparent_zero=True)
        img = Image.fromarray(rgba_arr, mode="RGBA")

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=False)
    buf.seek(0)
    return buf.getvalue()


@app.get("/indices")
async def list_indices():
    """List available spectral indices with their support status."""
    return indices_shortlist()


@app.get("/ramps")
async def list_ramps():
    """Return all preset color ramps and per-index default ramp/range settings."""
    defaults_raw = get_index_defaults()
    defaults_serializable = {}
    for name, cfg in defaults_raw.items():
        entry = {
            "ramp": cfg.get("ramp"),
            "range_mode": cfg.get("range_mode"),
        }
        rng = cfg.get("range")
        if rng is not None:
            entry["range"] = [float(rng[0]), float(rng[1])]
        defaults_serializable[name] = entry
    return {"ramps": get_ramps(), "defaults": defaults_serializable}


@app.get("/index-cache-status")
async def index_cache_status():
    """Progress + readiness for the precompute job tied to the loaded raster."""
    path = str(RASTER_PATH) if RASTER_PATH is not None else None
    return index_cache.progress(path)


class RampStopModel(BaseModel):
    pos: float
    color: str
    alpha: float = 1.0


class CustomRampModel(BaseModel):
    stops: List[RampStopModel]


class RenderIndexRequest(BaseModel):
    index_name: str
    ramp: Optional[str] = None
    range_mode: Literal["auto", "fixed", "percentile"] = "auto"
    range_min: Optional[float] = None
    range_max: Optional[float] = None
    custom_ramp: Optional[CustomRampModel] = None
    max_size: int = 2048


class RenderBandRequest(BaseModel):
    band: int
    ramp: str = "sequential"
    range_mode: Literal["auto", "fixed", "percentile"] = "percentile"
    range_min: Optional[float] = None
    range_max: Optional[float] = None
    custom_ramp: Optional[CustomRampModel] = None
    max_size: int = 2048


def _render_array_with_ramp(
    arr: np.ndarray,
    ramp_id: Optional[str],
    custom_ramp: Optional[CustomRampModel],
    range_mode: str,
    range_min: Optional[float],
    range_max: Optional[float],
    default_range: Optional[Tuple[float, float]],
    default_ramp: Optional[str],
) -> np.ndarray:
    """Resolve ramp + range + call the right apply_ramp variant. Returns HxWx4 uint8."""
    rmin, rmax = resolve_range(
        arr, range_mode, default_range, 2.0, 98.0, range_min, range_max
    )
    if custom_ramp is not None and custom_ramp.stops:
        stops = [
            {"pos": s.pos, "color": s.color, "alpha": s.alpha}
            for s in custom_ramp.stops
        ]
        return apply_custom_ramp(arr, stops, rmin, rmax)

    ramp_key = ramp_id or default_ramp or "sequential"
    return apply_ramp(arr, ramp_key, rmin, rmax)


@app.post("/render/index")
async def render_index(req: RenderIndexRequest):
    """Render a spectral index map as an RGBA PNG, aligned to WGS84 bounds.

    Pulls from IndexCache when available; falls back to on-the-fly compute and
    populates the cache for next time.
    """
    if RASTER_PATH is None:
        raise HTTPException(status_code=400, detail="No raster loaded")

    raster_path = str(RASTER_PATH)
    cached = index_cache.get(raster_path, req.index_name)
    if cached is not None:
        arr, meta = cached
        src_transform = meta["transform"]
        src_crs = meta["crs"]
    else:
        try:
            arr, meta = _compute_index_map_downsampled(
                raster_path, req.index_name, PREVIEW_MAX_SIDE
            )
        except KeyError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        src_transform = meta["transform"]
        src_crs = meta["crs"]
        # Populate cache for next time
        stats = compute_stats(arr, 2.0, 98.0)
        index_cache.put(
            raster_path,
            req.index_name,
            arr,
            {
                "transform": src_transform,
                "crs": src_crs,
                "stats": stats,
                "width": meta["width"],
                "height": meta["height"],
            },
        )

    defaults = get_default_for_index(req.index_name)
    default_range = defaults.get("range")
    if default_range is not None:
        default_range = (float(default_range[0]), float(default_range[1]))

    rgba = _render_array_with_ramp(
        arr,
        req.ramp,
        req.custom_ramp,
        req.range_mode,
        req.range_min,
        req.range_max,
        default_range,
        defaults.get("ramp"),
    )

    png_bytes = _warp_to_wgs84_png(rgba, src_transform, src_crs, req.max_size)
    return StreamingResponse(io.BytesIO(png_bytes), media_type="image/png")


@app.post("/render/band")
async def render_band(req: RenderBandRequest):
    """Render a single raw band through a color ramp.

    Reads the band at preview resolution, computes percentile stats, and applies
    either a preset ramp or a custom inline ramp.
    """
    if RASTER_PATH is None:
        raise HTTPException(status_code=400, detail="No raster loaded")

    if req.band < 1:
        raise HTTPException(status_code=400, detail="Band index is 1-based")

    raster_path = str(RASTER_PATH)
    try:
        with rasterio.open(raster_path) as src:
            if req.band > src.count:
                raise HTTPException(
                    status_code=400,
                    detail=f"Band {req.band} out of range (raster has {src.count} bands)",
                )
            out_w, out_h = _downsampled_shape(src.width, src.height, req.max_size)
            arr = src.read(
                req.band,
                out_shape=(out_h, out_w),
                resampling=Resampling.average,
            ).astype("float32")
            if src.nodata is not None:
                arr = np.where(arr == src.nodata, np.nan, arr)
            src_transform = _scaled_transform(
                src.transform, src.width, src.height, out_w, out_h
            )
            src_crs = src.crs
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"/render/band failed: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))

    rgba = _render_array_with_ramp(
        arr,
        req.ramp,
        req.custom_ramp,
        req.range_mode,
        req.range_min,
        req.range_max,
        None,
        req.ramp,
    )

    png_bytes = _warp_to_wgs84_png(rgba, src_transform, src_crs, req.max_size)
    return StreamingResponse(io.BytesIO(png_bytes), media_type="image/png")


@app.post("/segment/index")
async def segment_index(req: IndexSegRequest):
    """Run connected-component region-grow segmentation on a spectral index.

    Body: index_name, threshold, seeds (each {row, col, kind}). At least one
    positive seed is required.
    Returns: image/png aligned to the loaded raster's WGS84 bounds.
    """
    if not req.seeds:
        raise HTTPException(status_code=400, detail="At least one seed required")
    pos, neg = _split_seeds(req.seeds)
    if not pos:
        raise HTTPException(status_code=400, detail="At least one positive seed required")

    index_map, meta = _compute_index_map_for_loaded_raster(req.index_name)
    logger.info(
        "segment/index name=%s thr=%.3f pos=%d neg=%d shape=%s",
        req.index_name, req.threshold, len(pos), len(neg), index_map.shape,
    )

    mask = region_grow(index_map, req.threshold, pos, neg)
    logger.info("segment/index pixels=%d", int(mask.sum()))

    png_bytes = _warp_to_wgs84_png(mask, meta["transform"], meta["crs"], req.max_size)
    return StreamingResponse(io.BytesIO(png_bytes), media_type="image/png")


@app.post("/segment/progressive")
async def segment_progressive(req: ProgressiveSegRequest):
    """Run progressive (iterative) region growing with optional ROI dimming.

    Same body as /segment/index plus max_iterations and roi_dimming. ROI is
    not currently sent from the frontend — runs unconstrained.
    Returns: image/png (RGBA visualization with red highlights) in WGS84.
    """
    if not req.seeds:
        raise HTTPException(status_code=400, detail="At least one seed required")
    pos, neg = _split_seeds(req.seeds)
    if not pos:
        raise HTTPException(status_code=400, detail="At least one positive seed required")

    index_map, meta = _compute_index_map_for_loaded_raster(req.index_name)
    logger.info(
        "segment/progressive name=%s thr=%.3f iters=%d pos=%d neg=%d",
        req.index_name, req.threshold, req.max_iterations, len(pos), len(neg),
    )

    mask, rgba, seg_meta = progressive_region_grow_with_ROI(
        index_map=index_map,
        threshold=req.threshold,
        pos_points=pos,
        neg_points=neg,
        roi_mask=None,
        max_iterations=req.max_iterations,
        roi_dimming=req.roi_dimming,
    )
    logger.info("segment/progressive meta=%s", seg_meta)

    png_bytes = _warp_to_wgs84_png(rgba, meta["transform"], meta["crs"], req.max_size)
    return StreamingResponse(io.BytesIO(png_bytes), media_type="image/png")


@app.post("/train/formula")
async def train_formula(req: TrainFormulaRequest):
    """Learn the best spectral index formula from seed-derived training labels.

    Pipeline:
      1. Compute every requested index from the loaded raster.
      2. Use the first index + threshold + seeds to derive a coarse mask.
      3. Pass index_maps + mask into learn_road_segmentation_formula.
    """
    if not req.index_names:
        raise HTTPException(status_code=400, detail="At least one index name required")
    if not req.seeds:
        raise HTTPException(status_code=400, detail="At least one seed required")
    pos, neg = _split_seeds(req.seeds)
    if not pos:
        raise HTTPException(status_code=400, detail="At least one positive seed required")
    if RASTER_PATH is None:
        raise HTTPException(status_code=400, detail="No raster loaded")

    raster_path = str(RASTER_PATH)

    # Prefer the precomputed (downsampled) index cache so training stays fast
    # even with many indices on huge rasters. Seeds are remapped to the
    # downsampled grid using the ratio of original->cached dimensions.
    cached_names = [n for n in req.index_names if index_cache.has(raster_path, n)]
    index_maps = {}
    src_w = src_h = None
    cache_w = cache_h = None

    if cached_names:
        with rasterio.open(raster_path) as _src:
            src_w, src_h = _src.width, _src.height
        for name in cached_names:
            entry = index_cache.get(raster_path, name)
            if entry is None:
                continue
            arr, meta = entry
            index_maps[name] = arr
            if cache_w is None:
                cache_w = int(meta["width"])
                cache_h = int(meta["height"])

    # For any name not in cache, fall back to computing from full-res bands
    missing = [n for n in req.index_names if n not in index_maps]
    if missing:
        needed_bands = set()
        for name in missing:
            try:
                formula = get_formula(name)
                band_map, _ = resolve_required_bands(formula.required_bands)
            except (KeyError, ValueError):
                continue
            needed_bands.update(band_map.values())

        if needed_bands:
            try:
                band_arrays, _ = read_band_arrays(
                    raster_path, needed_bands, apply_nodata_mask=True
                )
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc))
            fallback_maps = compute_multiple_indices(band_arrays, missing)
            # If we already have cached (downsampled) maps, downsample fallbacks
            # to the same grid so they can stack column-wise.
            if cache_w is not None and cache_h is not None:
                from PIL import Image as _PILImage
                for n, m in fallback_maps.items():
                    if m.shape != (cache_h, cache_w):
                        # NaN-safe nearest resize via PIL
                        as_img = _PILImage.fromarray(m.astype("float32"))
                        as_img = as_img.resize((cache_w, cache_h), resample=_PILImage.BILINEAR)
                        index_maps[n] = np.asarray(as_img, dtype="float32")
                    else:
                        index_maps[n] = m
            else:
                index_maps.update(fallback_maps)

    if not index_maps:
        raise HTTPException(status_code=400, detail="No indices could be computed")

    # Remap seeds to the downsampled grid if training from the cache
    if cache_w is not None and cache_h is not None and src_w and src_h:
        sx = cache_w / float(src_w)
        sy = cache_h / float(src_h)
        pos = [(min(cache_h - 1, max(0, int(r * sy))), min(cache_w - 1, max(0, int(c * sx)))) for r, c in pos]
        neg = [(min(cache_h - 1, max(0, int(r * sy))), min(cache_w - 1, max(0, int(c * sx)))) for r, c in neg]

    # Coarse training mask from the first available index
    first_name = next(iter(index_maps))
    first_index = index_maps[first_name]
    training_mask = region_grow(first_index, req.threshold, pos, neg)

    if np.unique(training_mask).size < 2:
        # Sweep nearby thresholds first; the seed points may be valid but the
        # requested threshold can still collapse the connected component to
        # background only.
        candidate_thresholds = [float(req.threshold)]
        candidate_thresholds.extend(float(t) for t in np.linspace(0.05, 0.95, 19))
        seen_thresholds = set()
        best_mask = training_mask
        best_balance = -1

        for threshold in candidate_thresholds:
            threshold_key = round(threshold, 4)
            if threshold_key in seen_thresholds:
                continue
            seen_thresholds.add(threshold_key)

            mask = region_grow(first_index, threshold, pos, neg)
            unique = np.unique(mask)
            if unique.size < 2:
                continue

            road_pixels = int(mask.sum())
            non_road_pixels = int(mask.size - road_pixels)
            balance = min(road_pixels, non_road_pixels)
            if balance > best_balance:
                best_balance = balance
                best_mask = mask

        training_mask = best_mask

    if np.unique(training_mask).size < 2:
        # Final fallback: build a small positive neighborhood directly from
        # the provided seeds so training can still proceed with both classes.
        seed_mask = np.zeros_like(first_index, dtype=bool)
        for row, col in pos:
            if 0 <= row < seed_mask.shape[0] and 0 <= col < seed_mask.shape[1]:
                seed_mask[row, col] = True

        if np.any(seed_mask):
            seed_mask = ndimage.binary_dilation(seed_mask, iterations=2)
            for row, col in neg:
                if 0 <= row < seed_mask.shape[0] and 0 <= col < seed_mask.shape[1]:
                    seed_mask[row, col] = False
            training_mask = seed_mask.astype(np.uint8)

    if np.unique(training_mask).size < 2:
        raise HTTPException(
            status_code=422,
            detail=(
                "Unable to derive both road and non-road pixels from the provided seeds. "
                "Place positive seeds on the road class and negative seeds outside it, "
                "or adjust the threshold so the seed region expands past the seed points."
            ),
        )

    # Lazy import — sklearn isn't needed for any other endpoint
    from .algo.training import learn_road_segmentation_formula
    result = learn_road_segmentation_formula(index_maps, training_mask)
    logger.info(
        "train/formula best=%s combined_iou=%.3f",
        result.get("best_index"), result.get("combined_iou", 0),
    )
    return result


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
