"""
CPU-based region growing segmentation.
Multi-seed support with 4/8-connectivity and spectral thresholds.
"""

from typing import Tuple, List, Optional
from collections import deque
import numpy as np
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)


@dataclass
class SegmentationResult:
    """Result of segmentation."""
    labels: np.ndarray  # labeled image
    seeds: List[Tuple[int, int]]  # seed points used
    region_stats: dict  # per-region statistics


class RegionGrowing:
    """CPU region growing segmentation."""

    def __init__(
        self,
        connectivity: int = 4,
        intensity_threshold: float = 20.0,
        spectral_distance_metric: str = "euclidean",
    ):
        """
        Initialize region growing.

        Args:
            connectivity: 4 or 8 connectivity
            intensity_threshold: max spectral distance to add pixel
            spectral_distance_metric: 'euclidean', 'manhattan', or 'chebyshev'
        """
        self.connectivity = connectivity
        self.threshold = intensity_threshold
        self.metric = spectral_distance_metric

        self.neighbors_4 = [(-1, 0), (1, 0), (0, -1), (0, 1)]
        self.neighbors_8 = self.neighbors_4 + [(-1, -1), (-1, 1), (1, -1), (1, 1)]

    def grow(
        self,
        data: np.ndarray,
        seeds: List[Tuple[int, int]],
    ) -> SegmentationResult:
        """
        Grow regions from multiple seed points.

        Args:
            data: Input data (H, W) or (B, H, W) for multispectral
            seeds: List of (row, col) seed points

        Returns:
            SegmentationResult with labels, seeds, and stats
        """
        if data.ndim == 3:
            # Multispectral: (bands, height, width)
            labels = self._grow_multispectral(data, seeds)
        else:
            # Single band
            labels = self._grow_single_band(data, seeds)

        stats = self._compute_stats(data, labels)
        return SegmentationResult(labels, seeds, stats)

    def _grow_single_band(
        self, data: np.ndarray, seeds: List[Tuple[int, int]]
    ) -> np.ndarray:
        """Grow regions from seeds in single-band data."""
        H, W = data.shape
        labels = np.zeros((H, W), dtype=np.int32)
        visited = np.zeros((H, W), dtype=bool)

        neighbors = self.neighbors_8 if self.connectivity == 8 else self.neighbors_4

        for seed_id, (r, c) in enumerate(seeds, start=1):
            if visited[r, c]:
                continue

            queue = deque([(r, c)])
            labels[r, c] = seed_id
            visited[r, c] = True
            seed_val = float(data[r, c])

            while queue:
                r, c = queue.popleft()

                for dr, dc in neighbors:
                    nr, nc = r + dr, c + dc
                    if 0 <= nr < H and 0 <= nc < W and not visited[nr, nc]:
                        dist = abs(float(data[nr, nc]) - seed_val)
                        if dist <= self.threshold:
                            labels[nr, nc] = seed_id
                            visited[nr, nc] = True
                            queue.append((nr, nc))

        return labels

    def _grow_multispectral(
        self, data: np.ndarray, seeds: List[Tuple[int, int]]
    ) -> np.ndarray:
        """Grow regions from seeds in multispectral data."""
        B, H, W = data.shape
        labels = np.zeros((H, W), dtype=np.int32)
        visited = np.zeros((H, W), dtype=bool)

        neighbors = self.neighbors_8 if self.connectivity == 8 else self.neighbors_4

        for seed_id, (r, c) in enumerate(seeds, start=1):
            if visited[r, c]:
                continue

            queue = deque([(r, c)])
            labels[r, c] = seed_id
            visited[r, c] = True
            seed_spectrum = data[:, r, c].astype(float)

            while queue:
                r, c = queue.popleft()

                for dr, dc in neighbors:
                    nr, nc = r + dr, c + dc
                    if 0 <= nr < H and 0 <= nc < W and not visited[nr, nc]:
                        spectrum = data[:, nr, nc].astype(float)
                        dist = self._spectral_distance(seed_spectrum, spectrum)
                        if dist <= self.threshold:
                            labels[nr, nc] = seed_id
                            visited[nr, nc] = True
                            queue.append((nr, nc))

        return labels

    def _spectral_distance(self, v1: np.ndarray, v2: np.ndarray) -> float:
        """Compute spectral distance between two vectors."""
        if self.metric == "euclidean":
            return float(np.sqrt(np.sum((v1 - v2) ** 2)))
        elif self.metric == "manhattan":
            return float(np.sum(np.abs(v1 - v2)))
        elif self.metric == "chebyshev":
            return float(np.max(np.abs(v1 - v2)))
        else:
            raise ValueError(f"Unknown metric: {self.metric}")

    def _compute_stats(self, data: np.ndarray, labels: np.ndarray) -> dict:
        """Compute statistics per region."""
        stats = {}
        unique_labels = np.unique(labels)
        unique_labels = unique_labels[unique_labels > 0]

        for label in unique_labels:
            mask = labels == label
            if data.ndim == 3:
                # Multispectral
                region_data = data[:, mask]
                stats[int(label)] = {
                    "count": np.sum(mask),
                    "mean": region_data.mean(axis=1),
                    "std": region_data.std(axis=1),
                }
            else:
                # Single band
                region_data = data[mask]
                stats[int(label)] = {
                    "count": np.sum(mask),
                    "mean": float(region_data.mean()),
                    "std": float(region_data.std()),
                }

        return stats
