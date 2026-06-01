from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np
from PIL import Image


DEFAULT_PERCENTILES = (2.0, 98.0)


@dataclass(frozen=True)
class RampStop:
    pos: float
    color: str
    alpha: float = 1.0


RAMP_PRESETS: Dict[str, Dict] = {
    "diverging": {
        "name": "Diverging (Teal-Orange)",
        "stops": [
            RampStop(0.0, "#0b4f6c"),
            RampStop(0.5, "#f4f1e9"),
            RampStop(1.0, "#d8572a"),
        ],
    },
    "sequential": {
        "name": "Sequential (Terrain)",
        "stops": [
            RampStop(0.0, "#0e2f2a"),
            RampStop(0.45, "#3b8a5a"),
            RampStop(0.75, "#a8c686"),
            RampStop(1.0, "#f2d492"),
        ],
    },
    "mask": {
        "name": "Mask (Accent)",
        "stops": [
            RampStop(0.0, "#000000", alpha=0.0),
            RampStop(1.0, "#f26522", alpha=0.9),
        ],
    },
}


INDEX_DEFAULTS: Dict[str, Dict] = {
    "ndvi": {"ramp": "diverging", "range_mode": "fixed", "range": (-1.0, 1.0)},
    "ndwi": {"ramp": "diverging", "range_mode": "fixed", "range": (-1.0, 1.0)},
    "gndvi": {"ramp": "diverging", "range_mode": "fixed", "range": (-1.0, 1.0)},
    "ngrdi": {"ramp": "diverging", "range_mode": "fixed", "range": (-1.0, 1.0)},
    "vari": {"ramp": "diverging", "range_mode": "fixed", "range": (-1.0, 1.0)},
    "arvi": {"ramp": "diverging", "range_mode": "fixed", "range": (-1.0, 1.0)},
    "arvi2": {"ramp": "diverging", "range_mode": "fixed", "range": (-1.0, 1.0)},
    "wdrvi": {"ramp": "diverging", "range_mode": "fixed", "range": (-1.0, 1.0)},
    "rdvi": {"ramp": "diverging", "range_mode": "fixed", "range": (-1.0, 1.0)},
    "nli": {"ramp": "diverging", "range_mode": "fixed", "range": (-1.0, 1.0)},
    "gemi": {"ramp": "diverging", "range_mode": "fixed", "range": (-1.0, 1.0)},
    "ipvi": {"ramp": "sequential", "range_mode": "fixed", "range": (0.0, 1.0)},
    "tndvi": {"ramp": "sequential", "range_mode": "fixed", "range": (0.0, 1.5)},
    "evi": {"ramp": "sequential", "range_mode": "percentile"},
    "evi2": {"ramp": "sequential", "range_mode": "percentile"},
    "savi": {"ramp": "sequential", "range_mode": "percentile"},
    "osavi": {"ramp": "sequential", "range_mode": "percentile"},
    "msavi": {"ramp": "sequential", "range_mode": "percentile"},
    "dvi": {"ramp": "sequential", "range_mode": "percentile"},
    "rvi": {"ramp": "sequential", "range_mode": "percentile"},
    "sipi": {"ramp": "sequential", "range_mode": "percentile"},
    "cvi": {"ramp": "sequential", "range_mode": "percentile"},
    "mcari": {"ramp": "sequential", "range_mode": "percentile"},
    "mtvi2": {"ramp": "sequential", "range_mode": "percentile"},
    "tvi": {"ramp": "sequential", "range_mode": "percentile"},
    "logr": {"ramp": "diverging", "range_mode": "percentile"},
    "wbi": {"ramp": "sequential", "range_mode": "percentile"},
    "pwi": {"ramp": "sequential", "range_mode": "percentile"},
}


def get_ramps() -> Dict[str, Dict]:
    ramps: Dict[str, Dict] = {}
    for ramp_id, data in RAMP_PRESETS.items():
        ramps[ramp_id] = {
            "name": data["name"],
            "stops": [
                {"pos": stop.pos, "color": stop.color, "alpha": stop.alpha}
                for stop in data["stops"]
            ],
        }
    return ramps


def get_index_defaults() -> Dict[str, Dict]:
    return INDEX_DEFAULTS.copy()


def get_default_for_index(index_name: str) -> Dict:
    return INDEX_DEFAULTS.get(index_name, {"ramp": "sequential", "range_mode": "percentile"})


def hex_to_rgba(color: str, alpha: float = 1.0) -> Tuple[int, int, int, int]:
    color = color.lstrip("#")
    r = int(color[0:2], 16)
    g = int(color[2:4], 16)
    b = int(color[4:6], 16)
    a = int(max(0.0, min(1.0, alpha)) * 255)
    return r, g, b, a


def ramp_to_arrays(stops: List[RampStop]) -> Tuple[np.ndarray, np.ndarray]:
    positions = np.array([stop.pos for stop in stops], dtype=float)
    colors = np.array([hex_to_rgba(stop.color, stop.alpha) for stop in stops], dtype=float)
    return positions, colors


def compute_stats(values: np.ndarray, percentile_low: float, percentile_high: float) -> Dict[str, float]:
    valid = values[np.isfinite(values)]
    if valid.size == 0:
        return {"min": 0.0, "max": 1.0, "p_low": 0.0, "p_high": 1.0}
    return {
        "min": float(np.min(valid)),
        "max": float(np.max(valid)),
        "p_low": float(np.percentile(valid, percentile_low)),
        "p_high": float(np.percentile(valid, percentile_high)),
    }


def resolve_range(values: np.ndarray, range_mode: str, default_range: Optional[Tuple[float, float]], percentile_low: float, percentile_high: float, range_min: Optional[float], range_max: Optional[float]) -> Tuple[float, float]:
    if range_mode == "auto" and default_range is not None:
        return default_range

    if range_mode == "fixed":
        if range_min is not None and range_max is not None:
            return range_min, range_max
        if default_range is not None:
            return default_range

    stats = compute_stats(values, percentile_low, percentile_high)
    if range_mode in ("percentile", "auto"):
        return stats["p_low"], stats["p_high"]

    return stats["min"], stats["max"]


def apply_ramp(values: np.ndarray, ramp_id: str, range_min: float, range_max: float, transparent_zero: bool = False) -> np.ndarray:
    ramp = RAMP_PRESETS[ramp_id]
    positions, colors = ramp_to_arrays(ramp["stops"])

    values = values.astype(float)
    denom = range_max - range_min
    if denom == 0:
        denom = 1.0
    norm = (values - range_min) / denom
    norm = np.clip(norm, 0.0, 1.0)

    flat = norm.reshape(-1)
    rgba = np.zeros((flat.size, 4), dtype=float)
    for channel in range(4):
        rgba[:, channel] = np.interp(flat, positions, colors[:, channel])

    rgba = rgba.reshape(values.shape + (4,))

    if transparent_zero:
        mask = values == 0
        rgba[mask, 3] = 0

    nan_mask = ~np.isfinite(values)
    if np.any(nan_mask):
        rgba[nan_mask, 3] = 0

    return rgba.astype(np.uint8)


def apply_custom_ramp(values: np.ndarray, stops: List[Dict], range_min: float, range_max: float, transparent_zero: bool = False) -> np.ndarray:
    """Apply an ad-hoc color ramp defined inline as a list of dict stops.

    Each stop: {"pos": float in [0,1], "color": "#rrggbb", "alpha": float in [0,1]}.
    Mirrors apply_ramp() but bypasses the RAMP_PRESETS registry so custom
    ramps from the UI can be rendered without server-side registration.
    """
    if not stops:
        raise ValueError("Custom ramp requires at least one stop")

    ramp_stops = [
        RampStop(
            pos=float(s.get("pos", 0.0)),
            color=str(s.get("color", "#000000")),
            alpha=float(s.get("alpha", 1.0)),
        )
        for s in stops
    ]
    ramp_stops.sort(key=lambda s: s.pos)
    positions, colors = ramp_to_arrays(ramp_stops)

    values = values.astype(float)
    denom = range_max - range_min
    if denom == 0:
        denom = 1.0
    norm = (values - range_min) / denom
    norm = np.clip(norm, 0.0, 1.0)

    flat = norm.reshape(-1)
    rgba = np.zeros((flat.size, 4), dtype=float)
    for channel in range(4):
        rgba[:, channel] = np.interp(flat, positions, colors[:, channel])

    rgba = rgba.reshape(values.shape + (4,))

    if transparent_zero:
        mask = values == 0
        rgba[mask, 3] = 0

    nan_mask = ~np.isfinite(values)
    if np.any(nan_mask):
        rgba[nan_mask, 3] = 0

    return rgba.astype(np.uint8)


def rgba_to_png_bytes(rgba: np.ndarray) -> bytes:
    img = Image.fromarray(rgba, mode="RGBA")
    from io import BytesIO

    buffer = BytesIO()
    img.save(buffer, format="PNG")
    return buffer.getvalue()
