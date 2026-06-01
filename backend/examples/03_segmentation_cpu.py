"""
Example 3: CPU region growing segmentation.
Demonstrates single-band and multispectral workflows.
"""

import sys
sys.path.insert(0, "../src")

from segmentation import RegionGrowing
import numpy as np
from PIL import Image


def example_cpu_segmentation():
    """Region growing on CPU."""

    print("=== Single-Band Segmentation ===")

    # Create synthetic grayscale image with distinct regions
    image = np.ones((512, 512), dtype=np.uint8) * 100
    image[100:200, 100:200] = 150  # Region 1
    image[300:400, 300:400] = 200  # Region 2
    image[200:300, 50:150] = 180   # Region 3

    # Add noise
    noise = np.random.randint(-20, 20, image.shape)
    image = np.clip(image.astype(int) + noise, 0, 255).astype(np.uint8)

    # Segment with seeds in each region
    segmenter = RegionGrowing(
        connectivity=4,
        intensity_threshold=30.0,
        spectral_distance_metric="euclidean"
    )
    seeds = [(150, 150), (350, 350), (250, 100)]  # (row, col)

    result = segmenter.grow(image, seeds)

    print(f"Labels shape: {result.labels.shape}")
    print(f"Unique regions: {np.unique(result.labels[result.labels > 0])}")
    print(f"Region statistics:")
    for label, stats in result.region_stats.items():
        print(f"  Region {label}: {stats['count']} pixels, "
              f"mean={stats['mean']:.1f}, std={stats['std']:.1f}")

    # Save visualization
    colored = np.zeros((512, 512, 3), dtype=np.uint8)
    colors = [(255, 0, 0), (0, 255, 0), (0, 0, 255)]  # RGB
    for label, color in zip(np.unique(result.labels[result.labels > 0]), colors):
        colored[result.labels == label] = color

    img = Image.fromarray(colored)
    print(f"Saved segmentation to output_cpu_single_band.png")

    print("\n=== Multispectral Segmentation ===")

    # Create synthetic RGB image
    rgb = np.ones((3, 512, 512), dtype=np.uint8)

    # Red region
    rgb[:, 100:200, 100:200] = [[255], [50], [50]]
    # Green region
    rgb[:, 300:400, 300:400] = [[50], [255], [50]]
    # Blue region
    rgb[:, 200:300, 50:150] = [[50], [50], [255]]

    # Add noise
    rgb = np.clip(rgb.astype(int) + np.random.randint(-30, 30, rgb.shape), 0, 255).astype(np.uint8)

    result_rgb = segmenter.grow(rgb, seeds)

    print(f"Multispectral labels shape: {result_rgb.labels.shape}")
    print(f"Unique regions: {np.unique(result_rgb.labels[result_rgb.labels > 0])}")
    for label, stats in result_rgb.region_stats.items():
        mean = stats['mean']
        print(f"  Region {label}: mean RGB={mean}")


if __name__ == "__main__":
    example_cpu_segmentation()
