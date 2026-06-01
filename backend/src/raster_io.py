"""
Windowed raster I/O for large GeoTIFF files.
Supports COG (Cloud Optimized GeoTIFF) for efficient access.
"""

from typing import Tuple, Optional, Dict, Any
import numpy as np
import rasterio
from rasterio.windows import Window, from_bounds
from rasterio.enums import Resampling
import logging

logger = logging.getLogger(__name__)


class RasterReader:
    """Efficiently read COG/GeoTIFF data without loading entire file."""

    def __init__(self, filepath: str):
        """Initialize reader. Keeps file closed until reads."""
        self.filepath = filepath
        self._src = None
        self._metadata = None

    def __enter__(self):
        self._src = rasterio.open(self.filepath)
        return self

    def __exit__(self, *args):
        if self._src:
            self._src.close()

    @property
    def metadata(self) -> Dict[str, Any]:
        """Get raster metadata (CRS, bounds, resolution, etc.)."""
        if not self._src:
            raise RuntimeError("Use 'with' context manager or open() first")
        return {
            "crs": self._src.crs,
            "bounds": self._src.bounds,
            "width": self._src.width,
            "height": self._src.height,
            "count": self._src.count,  # number of bands
            "dtype": self._src.dtypes[0],
            "transform": self._src.transform,
            "nodata": self._src.nodata,
        }

    def read_window(
        self,
        window: Window,
        bands: Optional[list] = None,
        out_shape: Optional[Tuple[int, int]] = None,
    ) -> np.ndarray:
        """
        Read data from a specific window.

        Args:
            window: rasterio Window object (row/col bounds)
            bands: List of band indices (1-indexed), default all
            out_shape: Optional output shape for resampling

        Returns:
            numpy array of shape (bands, height, width)
        """
        if not self._src:
            raise RuntimeError("Use 'with' context manager first")

        if bands is None:
            bands = list(range(1, self._src.count + 1))

        return self._src.read(
            bands,
            window=window,
            out_shape=out_shape,
            resampling=Resampling.nearest if out_shape else Resampling.nearest,
        )

    def window_from_bounds(self, left: float, bottom: float, right: float, top: float) -> Window:
        """Convert geographic bounds to rasterio Window."""
        if not self._src:
            raise RuntimeError("Use 'with' context manager first")
        return from_bounds(left, bottom, right, top, self._src.transform)

    def pixel_coords_to_geo(self, row: int, col: int) -> Tuple[float, float]:
        """Convert pixel (row, col) to geographic (x, y)."""
        if not self._src:
            raise RuntimeError("Use 'with' context manager first")
        return self._src.transform * (col, row)

    def geo_to_pixel_coords(self, x: float, y: float) -> Tuple[int, int]:
        """Convert geographic (x, y) to pixel (row, col)."""
        if not self._src:
            raise RuntimeError("Use 'with' context manager first")
        # Inverse transform
        col, row = ~self._src.transform * (x, y)
        return int(row), int(col)


def create_cog_from_geotiff(src_path: str, dst_path: str, tilesize: int = 512):
    """
    Convert standard GeoTIFF to Cloud Optimized GeoTIFF with overviews.

    Args:
        src_path: Source GeoTIFF
        dst_path: Output COG path
        tilesize: Internal tile size (512 or 256)
    """
    with rasterio.open(src_path) as src:
        profile = src.profile.copy()
        profile.update(
            tiled=True,
            blockxsize=tilesize,
            blockysize=tilesize,
            compress="lzw",
            COPY_SRC_OVERVIEWS="YES",
        )

        with rasterio.open(dst_path, "w", **profile) as dst:
            for i in range(1, src.count + 1):
                data = src.read(i)
                dst.write(data, i)

            # Build overviews
            dst.build_overviews([2, 4, 8, 16], Resampling.average)
            dst.update_tags(ns="IMAGE_STRUCTURE", LAYOUT="COG")

    logger.info(f"Created COG: {dst_path}")
