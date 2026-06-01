import json
import os
from functools import lru_cache
from typing import Dict, List, Optional, Tuple

from .config import BAND_METADATA_PATH


@lru_cache(maxsize=1)
def load_band_metadata() -> Dict:
    with BAND_METADATA_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


@lru_cache(maxsize=1)
def load_band_definitions() -> List[Dict]:
    return load_band_metadata().get("band_definitions", [])


def get_band_index_by_name_for_path(path: str) -> Dict[str, int]:
    """Look up the band-name -> band-index map for a TIFF.

    Matches by filename basename (case-insensitive) because the metadata JSON
    may have been authored on a different machine with absolute paths.
    """
    metadata = load_band_metadata()
    target = os.path.basename(path).lower()
    for entry in metadata.get("files", []):
        entry_name = os.path.basename(entry.get("path", "")).lower()
        if entry_name == target:
            return entry.get("band_index_by_name", {})
    return {}


def approximate_band_for_wavelength(wavelength_nm: int) -> Tuple[Optional[str], bool]:
    # Explicit approximations for common indices.
    explicit = {
        445: "coastal_blue",
        430: "coastal_blue",
        490: "blue",
        550: "green",
        531: "green_i",
        565: "green",
        610: "yellow",
        670: "red",
        680: "red",
        700: "rededge",
        705: "rededge",
        750: "rededge",
        800: "nir",
        865: "nir",
        900: "nir",
        970: "nir",
    }
    if wavelength_nm in explicit:
        return explicit[wavelength_nm], True

    # Nearest by center wavelength.
    defs = load_band_definitions()
    best = None
    best_delta = None
    for band in defs:
        center = band.get("wavelength_nm")
        name = band.get("name")
        if center is None or not name:
            continue
        delta = abs(center - wavelength_nm)
        if best is None or delta < best_delta:
            best = name
            best_delta = delta
    return (best, True) if best else (None, False)
