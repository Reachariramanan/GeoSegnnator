"""
GPU-accelerated region growing using PyTorch.
Uses dilate kernels via conv2d for expansion.
"""

from typing import Tuple, List
import numpy as np

try:
    import torch
    import torch.nn.functional as F
    HAS_PYTORCH = True
except ImportError:
    HAS_PYTORCH = False
    torch = None

from dataclasses import dataclass
import logging
import time

logger = logging.getLogger(__name__)


@dataclass
class PyTorchSegmentationResult:
    """Result of PyTorch GPU segmentation."""
    labels: np.ndarray  # CPU numpy array
    seeds: List[Tuple[int, int]]
    compute_time: float
    memory_peak: float


class PyTorchRegionGrowing:
    """GPU region growing using PyTorch convolution kernels."""

    def __init__(
        self,
        connectivity: int = 4,
        intensity_threshold: float = 20.0,
        spectral_distance_metric: str = "euclidean",
        device: str = "cuda",
    ):
        """
        Initialize PyTorch region growing.

        Args:
            device: 'cuda' or 'cpu'
        """
        if not HAS_PYTORCH:
            raise RuntimeError("PyTorch not installed. Install with: pip install torch torchvision")

        self.connectivity = connectivity
        self.threshold = intensity_threshold
        self.metric = spectral_distance_metric
        self.device = device

    def grow(
        self,
        data: np.ndarray,
        seeds: List[Tuple[int, int]],
    ) -> PyTorchSegmentationResult:
        """
        PyTorch GPU region growing.

        Args:
            data: CPU numpy array (H, W) or (B, H, W)
            seeds: List of (row, col) seed points

        Returns:
            PyTorchSegmentationResult with labels on CPU
        """
        start = time.time()

        # Transfer to GPU
        if self.device == "cuda":
            torch_data = torch.from_numpy(data).float().to(self.device)
        else:
            torch_data = torch.from_numpy(data).float()

        if torch_data.ndim == 3:
            labels = self._grow_multispectral_pytorch(torch_data, seeds)
        else:
            labels = self._grow_single_band_pytorch(torch_data, seeds)

        # Transfer back to CPU
        labels_np = labels.cpu().numpy().astype(np.int32)

        elapsed = time.time() - start

        # Estimate memory usage
        memory_mb = (data.nbytes + labels_np.nbytes) / (1024 ** 2)
        logger.info(f"PyTorch segmentation: {elapsed:.2f}s, ~{memory_mb:.1f}MB transferred")

        return PyTorchSegmentationResult(labels_np, seeds, elapsed, memory_mb)

    def _grow_single_band_pytorch(
        self, torch_data: "torch.Tensor", seeds: List[Tuple[int, int]]
    ) -> "torch.Tensor":
        """Single-band region growing using PyTorch."""
        H, W = torch_data.shape
        labels = torch.zeros((H, W), dtype=torch.int32, device=self.device)

        dilation_kernel = self._get_dilation_kernel()

        for seed_id, (r, c) in enumerate(seeds, start=1):
            if labels[r, c] > 0:
                continue

            frontier = torch.zeros((1, 1, H, W), dtype=torch.bool, device=self.device)
            frontier[0, 0, r, c] = True
            labels[r, c] = seed_id
            seed_val = torch_data[r, c]

            for _ in range(max(H, W)):  # max iterations
                if not frontier.any():
                    break

                # Dilate frontier
                expanded = F.max_pool2d(
                    frontier.float(), kernel_size=3, stride=1, padding=1
                ).bool()

                # Only expand to unlabeled pixels
                new_frontier = (
                    expanded[0, 0] & (labels == 0) & (frontier[0, 0] == False)
                )

                if new_frontier.any():
                    # Compute distances
                    distances = torch.abs(torch_data[new_frontier] - seed_val)
                    add_mask = new_frontier.clone()
                    add_mask[new_frontier] = distances <= self.threshold
                    labels[add_mask] = seed_id

                    # Update frontier
                    frontier[0, 0] = add_mask
                else:
                    frontier = torch.zeros_like(frontier)

        return labels

    def _grow_multispectral_pytorch(
        self, torch_data: "torch.Tensor", seeds: List[Tuple[int, int]]
    ) -> "torch.Tensor":
        """Multispectral region growing using PyTorch."""
        B, H, W = torch_data.shape
        labels = torch.zeros((H, W), dtype=torch.int32, device=self.device)

        for seed_id, (r, c) in enumerate(seeds, start=1):
            if labels[r, c] > 0:
                continue

            frontier = torch.zeros((1, 1, H, W), dtype=torch.bool, device=self.device)
            frontier[0, 0, r, c] = True
            labels[r, c] = seed_id
            seed_spectrum = torch_data[:, r, c]

            for _ in range(max(H, W)):
                if not frontier.any():
                    break

                expanded = F.max_pool2d(
                    frontier.float(), kernel_size=3, stride=1, padding=1
                ).bool()
                new_frontier = (
                    expanded[0, 0] & (labels == 0) & (frontier[0, 0] == False)
                )

                if new_frontier.any():
                    distances = self._spectral_distance_pytorch(
                        torch_data[:, new_frontier], seed_spectrum
                    )
                    add_mask = new_frontier.clone()
                    add_mask[new_frontier] = distances <= self.threshold
                    labels[add_mask] = seed_id
                    frontier[0, 0] = add_mask
                else:
                    frontier = torch.zeros_like(frontier)

        return labels

    def _spectral_distance_pytorch(
        self, spectrum_array: "torch.Tensor", seed_spectrum: "torch.Tensor"
    ) -> "torch.Tensor":
        """Compute spectral distance on GPU."""
        if self.metric == "euclidean":
            return torch.sqrt(
                torch.sum(
                    (spectrum_array - seed_spectrum.unsqueeze(1)) ** 2, dim=0
                )
            )
        elif self.metric == "manhattan":
            return torch.sum(
                torch.abs(spectrum_array - seed_spectrum.unsqueeze(1)), dim=0
            )
        elif self.metric == "chebyshev":
            return torch.max(
                torch.abs(spectrum_array - seed_spectrum.unsqueeze(1)), dim=0
            )[0]
        else:
            raise ValueError(f"Unknown metric: {self.metric}")

    def _get_dilation_kernel(self) -> "torch.Tensor":
        """Get dilation kernel for connectivity."""
        if self.connectivity == 4:
            kernel = torch.tensor(
                [[0, 1, 0], [1, 1, 1], [0, 1, 0]], dtype=torch.float32
            )
        else:  # 8
            kernel = torch.ones((3, 3), dtype=torch.float32)
        return kernel.to(self.device)
