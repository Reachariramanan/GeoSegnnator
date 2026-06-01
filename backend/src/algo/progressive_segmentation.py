"""Progressive road segmentation with multi-seed region growing and ML generalization.

This module supports:
- Multi-seed region growing for road segmentation in mountainous terrain
- Progressive optimization of region boundaries
- Formula generalization using logistic regression
- ROI-based dimming for interactive segmentation
"""
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from scipy import ndimage
from rasterio.transform import rowcol

from .segmentation_algo import normalize_index, region_grow, parse_geojson_seeds
from .registry import get_formula, resolve_required_bands
from .training import learn_road_segmentation_formula


def progressive_region_grow(
    index_map: np.ndarray,
    threshold: float,
    pos_points: List[Tuple[int, int]],
    neg_points: List[Tuple[int, int]],
    max_iterations: int = 10,
    convergence_threshold: float = 0.01,
    min_region_size: int = 10,
    expand_threshold: float = 0.5,
) -> Tuple[np.ndarray, Dict[str, Any]]:
    """Progressive region growing with iterative optimization.

    Args:
        index_map: Normalized index map for segmentation
        threshold: Initial threshold for seed expansion
        pos_points: List of (row, col) positive seed points
        neg_points: List of (row, col) negative seed points
        max_iterations: Maximum iterations for optimization
        convergence_threshold: Change threshold for convergence
        min_region_size: Minimum region size to keep
        expand_threshold: Additional threshold for expansion phase

    Returns:
        Tuple of (final_mask, metadata including iteration count and changes)
    """
    normalized = normalize_index(index_map)
    height, width = normalized.shape

    # Initialize with seed points
    seed_mask = np.zeros_like(normalized, dtype=np.uint8)
    for row, col in pos_points:
        if 0 <= row < height and 0 <= col < width:
            seed_mask[row, col] = 1

    for row, col in neg_points:
        if 0 <= row < height and 0 <= col < width:
            seed_mask[row, col] = 2  # Negative seed marker

    metadata = {
        "iterations": 0,
        "final_threshold": threshold,
        "regions_found": 0,
        "pixels_segmented": 0,
        "converged": False,
    }

    for iteration in range(max_iterations):
        # Current region based on seeds
        labeled, num = ndimage.label(seed_mask == 1)
        metadata["regions_found"] = num

        # Remove small regions
        if num > 0:
            sizes = np.bincount(labeled.ravel())
            sizes[0] = 0  # Ignore background
            mask = sizes >= min_region_size
            keep_labels = np.where(mask)[0]
            if len(keep_labels) == 0:
                seed_mask = np.zeros_like(seed_mask, dtype=np.uint8)
            else:
                seed_mask = np.isin(labeled, keep_labels).astype(np.uint8)

        # Calculate statistics for current region
        current_region = normalized * seed_mask
        valid = current_region[current_region > 0] if np.any(seed_mask) else np.array([])

        if valid.size < 10:
            break  # Not enough pixels for meaningful optimization

        # Adjust threshold based on statistics
        mean_val = float(np.mean(valid))
        std_val = float(np.std(valid)) if np.std(valid) > 0 else 0.1

        # Progressive threshold adjustment
        new_threshold = mean_val - 0.5 * std_val
        new_threshold = max(0.1, min(0.9, new_threshold))

        # Check for convergence
        threshold_change = abs(new_threshold - threshold)
        threshold = new_threshold

        if threshold_change < convergence_threshold:
            metadata["converged"] = True
            break

        # Expand region based on new threshold
        candidate = normalized >= threshold

        # Preserve existing positive seeds
        expanded_mask = np.where(seed_mask == 1, 1, 0)
        expanded_mask = np.where((candidate == 1) & (seed_mask == 0), 1, expanded_mask)

        # Remove negative seed regions
        neg_labeled, _ = ndimage.label(seed_mask == 2)
        neg_labels = set(neg_labeled[neg_labeled > 0])
        if neg_labels:
            expanded_mask = np.where(np.isin(labeled, list(neg_labels)), 0, expanded_mask)

        # Check for convergence based on pixel count change
        prev_count = np.sum(seed_mask == 1)
        new_count = np.sum(expanded_mask == 1)
        count_change = abs(new_count - prev_count) / (prev_count + 1e-8)

        seed_mask = expanded_mask
        metadata["iterations"] = iteration + 1
        metadata["pixels_segmented"] = np.sum(seed_mask == 1)

        if count_change < convergence_threshold and iteration > 0:
            metadata["converged"] = True
            break

    metadata["final_threshold"] = threshold
    metadata["pixels_segmented"] = np.sum(seed_mask == 1)

    return seed_mask, metadata


def progressive_region_grow_with_ROI(
    index_map: np.ndarray,
    threshold: float,
    pos_points: List[Tuple[int, int]],
    neg_points: List[Tuple[int, int]],
    roi_mask: Optional[np.ndarray] = None,
    max_iterations: int = 10,
    convergence_threshold: float = 0.01,
    min_region_size: int = 10,
    roi_dimming: float = 0.3,
) -> Tuple[np.ndarray, np.ndarray, Dict[str, Any]]:
    """Progressive region growing constrained by ROI with dimming.

    Args:
        index_map: Normalized index map
        threshold: Initial threshold
        pos_points: Positive seed points
        neg_points: Negative seed points
        roi_mask: Binary mask defining ROI (1 = ROI, 0 = outside)
        max_iterations: Maximum iterations
        convergence_threshold: Change threshold for convergence
        min_region_size: Minimum region size
        roi_dimming: Dimming factor for non-ROI (0 = fully dim, 1 = no dim)

    Returns:
        Tuple of (segmentation_mask, RGBA visualization, metadata)
    """
    normalized = normalize_index(index_map)
    height, width = normalized.shape

    # Apply ROI constraint
    if roi_mask is not None:
        # Dim non-ROI areas for processing
        dimmed_map = normalized.copy()
        dimmed_map[roi_mask == 0] *= roi_dimming
        process_map = dimmed_map
    else:
        process_map = normalized

    # Run progressive region growing
    mask, metadata = progressive_region_grow(
        process_map,
        threshold,
        pos_points,
        neg_points,
        max_iterations,
        convergence_threshold,
        min_region_size,
    )

    # Apply ROI constraint to final mask
    if roi_mask is not None:
        mask = mask * roi_mask

    # Create visualization with dimming
    rgb = np.zeros((height, width, 3), dtype=np.uint8)
    for c in range(3):
        scaled = np.clip((process_map * 255), 0, 255).astype(np.uint8)
        rgb[:, :, c] = scaled

    rgba = np.zeros((height, width, 4), dtype=np.uint8)
    rgba[:, :, :3] = rgb

    # Apply ROI-based alpha
    if roi_mask is not None:
        roi_valid = roi_mask.astype(bool)
        rgba[roi_valid, 3] = 255
        rgba[~roi_valid, 3] = int(255 * roi_dimming)

    # Highlight segmentation result
    mask_valid = mask.astype(bool)
    rgba[mask_valid, 3] = 255
    rgba[mask_valid, :3] = [255, 0, 0]  # Red for segmentation

    return mask, rgba, metadata


def compute_multiple_indices(
    band_arrays: Dict[str, np.ndarray],
    index_names: List[str],
) -> Dict[str, np.ndarray]:
    """Compute multiple spectral indices from band arrays using the formula registry."""
    indices: Dict[str, np.ndarray] = {}

    for name in index_names:
        try:
            formula = get_formula(name)
            band_map, _ = resolve_required_bands(formula.required_bands)
        except (KeyError, ValueError):
            continue

        resolved_names = list(band_map.values())
        if not all(b in band_arrays for b in resolved_names):
            continue

        ordered_args = [band_arrays[b] for b in resolved_names]
        params = formula.params or {}
        try:
            indices[name] = formula.compute(*ordered_args, **params)
        except Exception:
            continue

    if not indices and band_arrays:
        first_band = next(iter(band_arrays.values()))
        indices[index_names[0] if index_names else "band"] = normalize_index(first_band)

    return indices
