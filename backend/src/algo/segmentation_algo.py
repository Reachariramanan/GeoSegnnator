from typing import Dict, Iterable, List, Tuple

import numpy as np
from scipy import ndimage
from rasterio.transform import rowcol


def normalize_index(index_map: np.ndarray) -> np.ndarray:
    valid = np.isfinite(index_map)
    if not np.any(valid):
        return np.zeros_like(index_map, dtype=float)

    min_val = float(np.nanmin(index_map))
    max_val = float(np.nanmax(index_map))
    if max_val - min_val == 0:
        return np.zeros_like(index_map, dtype=float)

    normalized = (index_map - min_val) / (max_val - min_val)
    normalized[~valid] = 0.0
    return normalized


def region_grow(index_map: np.ndarray, threshold: float, pos_points: Iterable[Tuple[int, int]], neg_points: Iterable[Tuple[int, int]]) -> np.ndarray:
    normalized = normalize_index(index_map)
    candidate = normalized >= threshold

    labeled, num = ndimage.label(candidate)
    if num == 0:
        return np.zeros_like(candidate, dtype=np.uint8)

    pos_labels = set()
    neg_labels = set()
    pos_in_candidate = []
    neg_in_candidate = []
    pos_out_of_bounds = []
    neg_out_of_bounds = []

    for row, col in pos_points:
        if 0 <= row < labeled.shape[0] and 0 <= col < labeled.shape[1]:
            label = labeled[row, col]
            pos_in_candidate.append((row, col, label))
            if label != 0:
                pos_labels.add(label)
        else:
            pos_out_of_bounds.append((row, col))

    for row, col in neg_points:
        if 0 <= row < labeled.shape[0] and 0 <= col < labeled.shape[1]:
            label = labeled[row, col]
            neg_in_candidate.append((row, col, label))
            if label != 0:
                neg_labels.add(label)
        else:
            neg_out_of_bounds.append((row, col))

    keep_labels = pos_labels - neg_labels

    # Log diagnostic info when keep_labels is empty
    import logging
    logger = logging.getLogger(__name__)
    if not keep_labels:
        logger.warning(
            f"region_grow: empty keep_labels. "
            f"pos_labels={pos_labels}, neg_labels={neg_labels}, "
            f"pos_in_candidate={len(pos_in_candidate)}, neg_in_candidate={len(neg_in_candidate)}, "
            f"candidate_regions={num}, threshold={threshold:.3f}, "
            f"pos_out_of_bounds={len(pos_out_of_bounds)}, neg_out_of_bounds={len(neg_out_of_bounds)}"
        )
        if pos_labels == neg_labels and pos_labels:
            logger.warning("All positive seeds are in regions marked by negative seeds (conflict)")
        return np.zeros_like(candidate, dtype=np.uint8)

    mask = np.isin(labeled, list(keep_labels))
    return mask.astype(np.uint8)


def parse_geojson_seeds(geojson: Dict, seed_mode: str, transform) -> Tuple[List[Tuple[int, int]], List[Tuple[int, int]]]:
    pos_points: List[Tuple[int, int]] = []
    neg_points: List[Tuple[int, int]] = []

    for feature in geojson.get("features", []):
        geom = feature.get("geometry") or {}
        if geom.get("type") != "Point":
            continue
        coords = geom.get("coordinates", [])
        if len(coords) < 2:
            continue
        x, y = coords[0], coords[1]
        if seed_mode == "crs":
            row, col = rowcol(transform, x, y)
        else:
            col, row = int(x), int(y)
        props = feature.get("properties") or {}
        label = str(props.get("label", props.get("class", props.get("value", "")))).lower()
        if label in ("positive", "pos", "1", "true"):
            pos_points.append((int(row), int(col)))
        elif label in ("negative", "neg", "0", "false"):
            neg_points.append((int(row), int(col)))

    return pos_points, neg_points
