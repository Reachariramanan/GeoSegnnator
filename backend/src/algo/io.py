from pathlib import Path
from typing import Any, Dict, Iterable, Tuple

import numpy as np
import rasterio

from .bands import get_band_index_by_name_for_path
from .config import DEFAULT_SCALE_FACTOR, SCALE_MAX_CUTOFF


def _detect_scale_factor(array: np.ndarray) -> float:
    max_val = float(np.nanmax(array)) if array.size else 0.0
    return DEFAULT_SCALE_FACTOR if max_val > SCALE_MAX_CUTOFF else 1.0


def scale_reflectance(array: np.ndarray) -> np.ndarray:
    scale = _detect_scale_factor(array)
    if scale != 1.0:
        array = array / scale
    return np.clip(array, 0.0, 1.0)


def read_band_arrays(image_path: str, band_names: Iterable[str], apply_nodata_mask: bool = True) -> Tuple[Dict[str, np.ndarray], Dict[str, Any]]:
    band_names = list(band_names)
    band_arrays: Dict[str, np.ndarray] = {}

    with rasterio.open(image_path) as src:
        descriptions = [d.lower() if d else "" for d in src.descriptions]
        name_to_index = {name: idx + 1 for idx, name in enumerate(descriptions) if name}

        if not name_to_index:
            name_to_index = get_band_index_by_name_for_path(image_path)

        for name in band_names:
            band_index = name_to_index.get(name)
            if band_index is None:
                raise ValueError(f"Band not found: {name}")
            band = src.read(band_index).astype("float32")
            band_arrays[name] = scale_reflectance(band)

        meta = {
            "profile": src.profile.copy(),
            "nodata": src.nodata,
            "transform": src.transform,
            "crs": src.crs,
        }

        if apply_nodata_mask and src.nodata is not None:
            band_arrays = mask_nodata(band_arrays, src.nodata)

        return band_arrays, meta


def mask_nodata(arrays: Dict[str, np.ndarray], nodata: float) -> Dict[str, np.ndarray]:
    if nodata is None:
        return arrays
    mask = None
    for band in arrays.values():
        mask = band == nodata if mask is None else (mask & (band == nodata))
    if mask is None:
        return arrays
    masked = {}
    for name, band in arrays.items():
        band = band.copy()
        band[mask] = np.nan
        masked[name] = band
    return masked


def write_raster_geotiff(out_path: Path, data: np.ndarray, profile: Dict[str, Any], nodata: float | None = None) -> None:
    out_profile = profile.copy()
    out_profile.update(count=1, dtype="float32", nodata=nodata, compress="lzw")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(out_path, "w", **out_profile) as dst:
        dst.write(data.astype("float32"), 1)


def write_mask_geotiff(out_path: Path, mask: np.ndarray, profile: Dict[str, Any]) -> None:
    out_profile = profile.copy()
    out_profile.update(count=1, dtype="uint8", nodata=0, compress="lzw")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(out_path, "w", **out_profile) as dst:
        dst.write(mask.astype("uint8"), 1)
