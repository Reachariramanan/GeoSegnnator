"""
Example 1: Windowed raster reading from COG.
Demonstrates safe file I/O without loading entire dataset.
"""

import sys
sys.path.insert(0, "../src")

from raster_io import RasterReader
import numpy as np


def example_windowed_read():
    """Read geographic region without loading full file."""
    filepath = "../../data/sample.tif"  # Replace with actual COG

    with RasterReader(filepath) as reader:
        # Get metadata
        metadata = reader.metadata
        print(f"Dataset info:")
        print(f"  Bounds: {metadata['bounds']}")
        print(f"  CRS: {metadata['crs']}")
        print(f"  Shape: {metadata['width']} × {metadata['height']}")
        print(f"  Bands: {metadata['count']}")
        print(f"  Data type: {metadata['dtype']}")

        # Read specific geographic region
        # bounds = (left, bottom, right, top)
        bounds = (
            metadata["bounds"].left,
            metadata["bounds"].bottom,
            metadata["bounds"].left + (metadata["bounds"].right - metadata["bounds"].left) * 0.1,
            metadata["bounds"].bottom + (metadata["bounds"].top - metadata["bounds"].bottom) * 0.1,
        )

        window = reader.window_from_bounds(*bounds)
        print(f"\nWindow: row {window.row_off}-{window.row_off + window.height}, "
              f"col {window.col_off}-{window.col_off + window.width}")

        # Read RGB bands
        try:
            data = reader.read_window(window, bands=[1, 2, 3])
            print(f"Data shape: {data.shape}")
            print(f"Data range: [{data.min()}, {data.max()}]")
        except Exception as e:
            print(f"Note: {e} (expected if file has <3 bands)")
            # Read first band instead
            data = reader.read_window(window, bands=[1])
            print(f"Single-band shape: {data.shape}")

        # Convert pixel coords to geographic
        print(f"\nPixel→Geographic conversion:")
        row, col = 0, 0
        x, y = reader.pixel_coords_to_geo(row, col)
        print(f"  Pixel ({row}, {col}) → Geographic ({x:.4f}, {y:.4f})")

        # Convert geographic to pixel
        x_test = metadata["bounds"].left + 100
        y_test = metadata["bounds"].top - 100
        row_test, col_test = reader.geo_to_pixel_coords(x_test, y_test)
        print(f"  Geographic ({x_test:.4f}, {y_test:.4f}) → Pixel ({row_test}, {col_test})")


if __name__ == "__main__":
    example_windowed_read()
