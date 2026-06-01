"""
GPU-accelerated region growing using CuPy.
Vectorized operations on CUDA arrays.
"""

from typing import Tuple, List, Optional
import numpy as np

try:
    import cupy as cp
    HAS_CUPY = True
except ImportError:
    HAS_CUPY = False
    cp = None

from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)


@dataclass
class GPUSegmentationResult:
    """Result of GPU segmentation."""
    labels: np.ndarray  # transferred back to CPU
    seeds: List[Tuple[int, int]]
    compute_time: float  # seconds
    memory_peak: float  # MB


class CuPyRegionGrowing:
    """GPU region growing using CuPy (vectorized, no recursion)."""

    def __init__(
        self,
        connectivity: int = 4,
        intensity_threshold: float = 20.0,
        spectral_distance_metric: str = "euclidean",
    ):
        """Initialize CuPy region growing."""
        if not HAS_CUPY:
            raise RuntimeError("CuPy not installed. Install with: pip install cupy-cuda11x")

        self.connectivity = connectivity
        self.threshold = intensity_threshold
        self.metric = spectral_distance_metric

    def grow(
        self,
        data: np.ndarray,
        seeds: List[Tuple[int, int]],
    ) -> GPUSegmentationResult:
        """
        GPU region growing.

        Args:
            data: CPU numpy array (H, W) or (B, H, W)
            seeds: List of (row, col) seed points

        Returns:
            GPUSegmentationResult with labels on CPU
        """
        import time

        start = time.time()
        mem_before = cp.get_default_memory_pool().get_limit()

        # Transfer to GPU
        gpu_data = cp.asarray(data)

        if gpu_data.ndim == 3:
            labels = self._grow_multispectral_gpu(gpu_data, seeds)
        else:
            labels = self._grow_single_band_gpu(gpu_data, seeds)

        # Transfer back to CPU
        labels_cpu = cp.asnumpy(labels)

        elapsed = time.time() - start
        mem_peak = (cp.get_default_memory_pool().get_limit() - mem_before) / (1024 ** 2)

        logger.info(f"CuPy segmentation: {elapsed:.2f}s, peak {mem_peak:.1f}MB")

        return GPUSegmentationResult(labels_cpu, seeds, elapsed, mem_peak)

    def _grow_single_band_gpu(
        self, gpu_data: "cp.ndarray", seeds: List[Tuple[int, int]]
    ) -> "cp.ndarray":
        """Single-band region growing on GPU."""
        H, W = gpu_data.shape
        labels = cp.zeros((H, W), dtype=cp.int32)

        for seed_id, (r, c) in enumerate(seeds, start=1):
            if labels[r, c] > 0:
                continue

            # Initialize: create frontier with seed
            frontier = cp.zeros((H, W), dtype=bool)
            frontier[r, c] = True
            labels[r, c] = seed_id
            seed_val = gpu_data[r, c]

            # Expand until frontier is empty
            while cp.any(frontier):
                # Dilate frontier by connectivity
                expanded = self._dilate_frontier(frontier, self.connectivity)
                # Only expand to unlabeled, unvisited pixels
                new_frontier = expanded & (labels == 0)

                # Compute distances for new pixels
                if cp.any(new_frontier):
                    distances = cp.abs(gpu_data[new_frontier] - seed_val)
                    # Add pixels within threshold
                    add_mask = new_frontier.copy()
                    add_mask[new_frontier] &= distances <= self.threshold
                    labels[add_mask] = seed_id

                frontier = new_frontier & add_mask

        return labels

    def _grow_multispectral_gpu(
        self, gpu_data: "cp.ndarray", seeds: List[Tuple[int, int]]
    ) -> "cp.ndarray":
        """Multispectral region growing on GPU."""
        B, H, W = gpu_data.shape
        labels = cp.zeros((H, W), dtype=cp.int32)

        for seed_id, (r, c) in enumerate(seeds, start=1):
            if labels[r, c] > 0:
                continue

            frontier = cp.zeros((H, W), dtype=bool)
            frontier[r, c] = True
            labels[r, c] = seed_id
            seed_spectrum = gpu_data[:, r, c]

            while cp.any(frontier):
                expanded = self._dilate_frontier(frontier, self.connectivity)
                new_frontier = expanded & (labels == 0)

                if cp.any(new_frontier):
                    # Compute spectral distance for new pixels
                    distances = self._spectral_distance_gpu(
                        gpu_data[:, new_frontier], seed_spectrum
                    )
                    add_mask = new_frontier.copy()
                    add_mask[new_frontier] &= distances <= self.threshold
                    labels[add_mask] = seed_id

                frontier = new_frontier & add_mask

        return labels

    def _dilate_frontier(self, frontier: "cp.ndarray", connectivity: int) -> "cp.ndarray":
        """Morphological dilation of frontier."""
        if connectivity == 4:
            kernel = cp.array([[0, 1, 0], [1, 1, 1], [0, 1, 0]], dtype=bool)
        else:  # 8
            kernel = cp.ones((3, 3), dtype=bool)

        from cupyx.scipy import ndimage

        return ndimage.binary_dilation(frontier, structure=kernel)

    def _spectral_distance_gpu(
        self, spectrum_array: "cp.ndarray", seed_spectrum: "cp.ndarray"
    ) -> "cp.ndarray":
        """Compute spectral distance on GPU."""
        if self.metric == "euclidean":
            return cp.sqrt(cp.sum((spectrum_array - seed_spectrum[:, None]) ** 2, axis=0))
        elif self.metric == "manhattan":
            return cp.sum(cp.abs(spectrum_array - seed_spectrum[:, None]), axis=0)
        elif self.metric == "chebyshev":
            return cp.max(cp.abs(spectrum_array - seed_spectrum[:, None]), axis=0)
        else:
            raise ValueError(f"Unknown metric: {self.metric}")
