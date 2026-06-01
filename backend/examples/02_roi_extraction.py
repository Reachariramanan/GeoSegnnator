"""
Example 2: ROI extraction from bbox, polygon, and tile coordinates.
"""

import sys
sys.path.insert(0, "../src")

from roi import ROIExtractor, TileCoordConverter


def example_roi():
    """Demonstrate ROI extraction methods."""

    print("=== Bounding Box ROI ===")
    bounds = (-120.5, 37.0, -120.0, 37.5)
    roi = ROIExtractor.from_bbox(bounds)
    print(f"Bbox ROI: {roi}")

    print("\n=== Polygon ROI ===")
    polygon = {
        "type": "Polygon",
        "coordinates": [[
            [-120.5, 37.0],
            [-120.0, 37.0],
            [-120.0, 37.5],
            [-120.5, 37.5],
            [-120.5, 37.0]
        ]]
    }
    roi = ROIExtractor.from_polygon(polygon)
    print(f"Polygon ROI (min bounds): {roi}")

    print("\n=== Tile Coordinates ROI ===")
    roi = ROIExtractor.from_tile_coords(x=163, y=316, z=10)
    print(f"Tile (163, 316, 10) bounds: {roi}")

    print("\n=== Bounds to Tiles ===")
    tiles = TileCoordConverter.bounds_to_tiles(-120.5, 37.0, -120.0, 37.5, z=12)
    print(f"Bounds cover {len(tiles)} tiles at zoom 12:")
    for x, y, z in tiles[:5]:
        print(f"  ({x}, {y}, {z})")
    if len(tiles) > 5:
        print(f"  ... and {len(tiles) - 5} more")

    print("\n=== Tile to Bounds ===")
    bounds = TileCoordConverter.tile_to_bounds(163, 316, 10)
    print(f"Tile (163, 316, 10) → Bounds {bounds}")


if __name__ == "__main__":
    example_roi()
