"""
Example 5: Tile rendering workflow.
Demonstrates how to prepare and render tiles efficiently.
"""

import sys
sys.path.insert(0, "../src")

from raster_io import RasterReader, create_cog_from_geotiff
from roi import TileCoordConverter
import numpy as np
from PIL import Image


def create_sample_geotiff():
    """Create a sample GeoTIFF for testing."""
    import rasterio
    from rasterio.transform import from_bounds

    # Create sample data
    data = np.random.randint(50, 200, (3, 512, 512), dtype=np.uint8)

    # Define bounds (Web Mercator-like)
    bounds = (-120.5, 37.0, -120.0, 37.5)
    transform = from_bounds(*bounds, 512, 512)

    profile = {
        'driver': 'GTiff',
        'width': 512,
        'height': 512,
        'count': 3,
        'dtype': rasterio.uint8,
        'crs': 'EPSG:4326',
        'transform': transform,
    }

    with rasterio.open("../../data/sample.tif", 'w', **profile) as dst:
        dst.write(data)

    print("Created sample.tif")


def example_tile_workflow():
    """Full tile rendering workflow."""
    print("=== Tile Rendering Workflow ===")

    filepath = "../../data/sample.tif"

    # Step 1: Convert to COG (for production)
    try:
        create_cog_from_geotiff(filepath, "../../data/sample_cog.tif", tilesize=256)
        filepath = "../../data/sample_cog.tif"
    except Exception as e:
        print(f"Note: COG creation skipped ({e})")

    # Step 2: List tiles at zoom level 10
    print("\nTiles at zoom 10:")
    tiles = TileCoordConverter.bounds_to_tiles(-120.5, 37.0, -120.0, 37.5, z=10)
    for x, y, z in tiles[:3]:
        print(f"  Tile ({x}, {y}, {z})")

    # Step 3: Render a tile
    print("\nRendering sample tile...")

    with RasterReader(filepath) as reader:
        # Get bounds for first tile
        if tiles:
            x, y, z = tiles[0]
            bounds = TileCoordConverter.tile_to_bounds(x, y, z)
            print(f"Tile bounds: {bounds}")

            # Read window
            window = reader.window_from_bounds(*bounds)
            data = reader.read_window(
                window,
                bands=[1, 2, 3],
                out_shape=(256, 256)
            )

            # Normalize
            data = np.clip(
                (data - data.min()) / (data.max() - data.min() + 1e-6) * 255,
                0, 255
            ).astype(np.uint8)

            # Save PNG
            img = Image.fromarray(np.transpose(data, (1, 2, 0)), mode="RGB")
            img.save("output_tile.png")
            print(f"Saved tile to output_tile.png")


def example_pyramid_rendering():
    """Render tiles at multiple zoom levels."""
    print("\n=== Pyramid Rendering ===")

    bounds = (-120.5, 37.0, -120.0, 37.5)

    for zoom in [8, 10, 12, 14]:
        tiles = TileCoordConverter.bounds_to_tiles(*bounds, z=zoom)
        print(f"Zoom {zoom}: {len(tiles)} tiles")


if __name__ == "__main__":
    try:
        create_sample_geotiff()
    except Exception as e:
        print(f"Sample creation skipped: {e}")

    example_tile_workflow()
    example_pyramid_rendering()
