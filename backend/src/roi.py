"""
Region-of-Interest (ROI) extraction from rasters.
Support bbox, polygon (GeoJSON), and tile coordinates.
"""

from typing import Tuple, Dict, Any, List, Optional
from dataclasses import dataclass
import numpy as np
from rasterio.windows import Window
from shapely.geometry import box, shape
from shapely.ops import unary_union
import logging

logger = logging.getLogger(__name__)


@dataclass
class ROIBounds:
    """ROI geographic bounds."""
    left: float
    bottom: float
    right: float
    top: float

    def to_window(self, transform) -> Window:
        """Convert to rasterio Window given transform."""
        from rasterio.windows import from_bounds
        return from_bounds(self.left, self.bottom, self.right, self.top, transform)


class ROIExtractor:
    """Extract ROI from raster using various input types."""

    @staticmethod
    def from_bbox(bounds: Tuple[float, float, float, float]) -> ROIBounds:
        """
        Create ROI from bounding box (left, bottom, right, top).
        """
        left, bottom, right, top = bounds
        return ROIBounds(left, bottom, right, top)

    @staticmethod
    def from_polygon(geojson: Dict[str, Any]) -> ROIBounds:
        """
        Create ROI from GeoJSON polygon.
        Returns minimum bounding rectangle.
        """
        geom = shape(geojson)
        bounds = geom.bounds  # (minx, miny, maxx, maxy)
        return ROIBounds(*bounds)

    @staticmethod
    def from_tile_coords(x: int, y: int, z: int, crs: str = "EPSG:3857") -> ROIBounds:
        """
        Create ROI from Web Mercator tile coordinates (XYZ).

        Args:
            x, y, z: Tile coordinates
            crs: Target CRS for bounds conversion

        Returns:
            ROIBounds in Web Mercator
        """
        n = 2 ** z
        resolution = 40075016.686 / (256 * n)  # Web Mercator resolution

        left = -20037508.343 + (x * 256 * resolution)
        right = left + (256 * resolution)
        top = 20037508.343 - (y * 256 * resolution)
        bottom = top - (256 * resolution)

        return ROIBounds(left, bottom, right, top)

    @staticmethod
    def clip_to_polygon(data: np.ndarray, polygon: Dict[str, Any]) -> np.ndarray:
        """
        Mask raster data to polygon bounds.

        Args:
            data: 2D or 3D raster data
            polygon: GeoJSON polygon

        Returns:
            Masked data (same shape, outside polygon = 0)
        """
        from rasterio.mask import mask as rio_mask
        # This requires geometry + transform; simplified version:
        geom = shape(polygon)

        # For 3D data (bands, height, width)
        if data.ndim == 3:
            out = np.zeros_like(data)
            for b in range(data.shape[0]):
                out[b] = _mask_2d_to_polygon(data[b], geom)
            return out
        else:
            return _mask_2d_to_polygon(data, geom)


def _mask_2d_to_polygon(data: np.ndarray, polygon) -> np.ndarray:
    """Helper: mask 2D array to polygon using rasterization."""
    from rasterio.features import rasterize
    from rasterio.transform import from_bounds

    height, width = data.shape
    bounds = polygon.bounds
    transform = from_bounds(*bounds, width, height)

    mask = rasterize(
        [polygon],
        out_shape=(height, width),
        transform=transform,
        default_value=1,
        all_touched=False,
    )

    return data * mask.astype(data.dtype)


class TileCoordConverter:
    """Convert between tile coords (XYZ) and geographic bounds."""

    @staticmethod
    def tile_to_bounds(x: int, y: int, z: int) -> Tuple[float, float, float, float]:
        """XYZ tile → geographic bounds (left, bottom, right, top)."""
        n = 2 ** z
        resolution = 40075016.686 / (256 * n)

        left = -20037508.343 + (x * 256 * resolution)
        right = left + (256 * resolution)
        top = 20037508.343 - (y * 256 * resolution)
        bottom = top - (256 * resolution)

        return left, bottom, right, top

    @staticmethod
    def bounds_to_tiles(
        left: float, bottom: float, right: float, top: float, z: int
    ) -> List[Tuple[int, int]]:
        """Geographic bounds → list of tile coords at zoom level z."""
        n = 2 ** z
        resolution = 40075016.686 / (256 * n)

        min_x = int((left + 20037508.343) / (256 * resolution))
        max_x = int((right + 20037508.343) / (256 * resolution))
        max_y = int((20037508.343 - top) / (256 * resolution))
        min_y = int((20037508.343 - bottom) / (256 * resolution))

        tiles = []
        for x in range(min_x, max_x + 1):
            for y in range(min_y, max_y + 1):
                tiles.append((x, y, z))

        return tiles
