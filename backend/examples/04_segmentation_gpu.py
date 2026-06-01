"""
Example 4: GPU region growing with CuPy and PyTorch.
Demonstrates performance comparison and GPU management.
"""

import sys
sys.path.insert(0, "../src")

import numpy as np
import time


def example_gpu_cupy():
    """CuPy GPU segmentation."""
    print("=== CuPy GPU Segmentation ===")

    try:
        from gpu_cupy import CuPyRegionGrowing
    except ImportError:
        print("CuPy not installed. Install with: pip install cupy-cuda11x")
        return

    # Create large test image
    image = np.ones((1024, 1024), dtype=np.uint8) * 100
    image[200:400, 200:400] = 150
    image[600:800, 600:800] = 200
    image += np.random.randint(-20, 20, image.shape)
    image = np.clip(image, 0, 255).astype(np.uint8)

    seeds = [(300, 300), (700, 700)]

    segmenter = CuPyRegionGrowing(
        connectivity=4,
        intensity_threshold=30.0,
        spectral_distance_metric="euclidean"
    )

    start = time.time()
    result = segmenter.grow(image, seeds)
    elapsed = time.time() - start

    print(f"Compute time: {result.compute_time:.3f}s")
    print(f"Peak memory: {result.memory_peak:.1f}MB")
    print(f"Labels shape: {result.labels.shape}")


def example_gpu_pytorch():
    """PyTorch GPU segmentation."""
    print("\n=== PyTorch GPU Segmentation ===")

    try:
        from gpu_pytorch import PyTorchRegionGrowing
    except ImportError:
        print("PyTorch not installed. Install with: pip install torch torchvision")
        return

    import torch

    # Check CUDA availability
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"Using device: {device}")

    image = np.ones((1024, 1024), dtype=np.uint8) * 100
    image[200:400, 200:400] = 150
    image[600:800, 600:800] = 200
    image += np.random.randint(-20, 20, image.shape)
    image = np.clip(image, 0, 255).astype(np.uint8)

    seeds = [(300, 300), (700, 700)]

    segmenter = PyTorchRegionGrowing(
        connectivity=4,
        intensity_threshold=30.0,
        device=device
    )

    result = segmenter.grow(image, seeds)

    print(f"Compute time: {result.compute_time:.3f}s")
    print(f"Memory: {result.memory_peak:.1f}MB")
    print(f"Labels shape: {result.labels.shape}")


def benchmark_cpu_vs_gpu():
    """Compare CPU and GPU performance."""
    print("\n=== CPU vs GPU Benchmark ===")

    from segmentation import RegionGrowing

    image = np.ones((512, 512), dtype=np.uint8) * 100
    image[100:300, 100:300] = 150
    image += np.random.randint(-20, 20, image.shape)
    image = np.clip(image, 0, 255).astype(np.uint8)

    seeds = [(200, 200)]

    # CPU benchmark
    cpu_seg = RegionGrowing(connectivity=4, intensity_threshold=30.0)
    start = time.time()
    cpu_result = cpu_seg.grow(image, seeds)
    cpu_time = time.time() - start
    print(f"CPU time: {cpu_time:.3f}s")

    # CuPy benchmark (if available)
    try:
        from gpu_cupy import CuPyRegionGrowing
        gpu_seg = CuPyRegionGrowing(connectivity=4, intensity_threshold=30.0)
        gpu_result = gpu_seg.grow(image, seeds)
        print(f"GPU (CuPy) time: {gpu_result.compute_time:.3f}s")
        print(f"Speedup: {cpu_time / gpu_result.compute_time:.1f}×")
    except ImportError:
        print("(CuPy not available for benchmark)")


if __name__ == "__main__":
    example_gpu_cupy()
    example_gpu_pytorch()
    benchmark_cpu_vs_gpu()
