from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

from . import indices
from .bands import approximate_band_for_wavelength


@dataclass(frozen=True)
class FormulaDefinition:
    name: str
    display_name: str
    required_bands: List[str]
    compute: Callable[..., Any]
    params: Optional[Dict[str, Any]] = None
    needs_params: bool = False


STANDARD_BAND_MAP = {
    "nir": "nir",
    "red": "red",
    "green": "green",
    "blue": "blue",
}


FORMULAS: List[FormulaDefinition] = [
    FormulaDefinition("ndvi", "NDVI", ["nir", "red"], indices.ndvi),
    FormulaDefinition("evi", "EVI", ["nir", "red", "blue"], indices.evi),
    FormulaDefinition("evi2", "EVI2", ["nir", "red"], indices.evi2),
    FormulaDefinition("savi", "SAVI", ["nir", "red"], indices.savi, params={"l": 0.5}, needs_params=True),
    FormulaDefinition("osavi", "OSAVI", ["nir", "red"], indices.osavi),
    FormulaDefinition("msavi", "MSAVI", ["nir", "red"], indices.msavi),
    FormulaDefinition("rdvi", "RDVI", ["nir", "red"], indices.rdvi),
    FormulaDefinition("ipvi", "IPVI", ["nir", "red"], indices.ipvi),
    FormulaDefinition("dvi", "DVI", ["nir", "red"], indices.dvi),
    FormulaDefinition("rvi", "RVI", ["nir", "red"], indices.rvi),
    FormulaDefinition("ndwi", "NDWI", ["green", "nir"], indices.ndwi),
    FormulaDefinition("wbi", "WBI", ["970", "900"], indices.wbi),
    FormulaDefinition("pwi", "PWI", ["970", "900"], indices.wbi),
    FormulaDefinition("nli", "NLI", ["nir", "red"], indices.nli),
    FormulaDefinition("gndvi", "GNDVI", ["nir", "green"], indices.gndvi),
    FormulaDefinition("sipi", "SIPI", ["800", "445", "680"], indices.sipi),
    FormulaDefinition("cvi", "CVI", ["nir", "red", "green"], indices.cvi),
    FormulaDefinition("mcari", "MCARI", ["700", "670", "550"], indices.mcari),
    FormulaDefinition("arvi", "ARVI", ["nir", "red", "blue"], indices.arvi, params={"y": 0.08}, needs_params=True),
    FormulaDefinition("arvi2", "ARVI2", ["nir", "red"], indices.arvi2),
    FormulaDefinition("atsavi", "ATSAVI", ["nir", "red"], indices.atsavi, params={"a": 1.0, "b": 0.0, "x": 0.08}, needs_params=True),
    FormulaDefinition("wdvi", "WDVI", ["nir", "red"], indices.wdvi, params={"a": 1.0}, needs_params=True),
    FormulaDefinition("wdrvi", "WDRVI", ["nir", "red"], indices.wdrvi, params={"alpha": 0.1}, needs_params=True),
    FormulaDefinition("gli", "GLI", ["green", "red", "blue"], indices.gli),
    FormulaDefinition("ngrdi", "NGRDI", ["green", "red"], indices.ngrdi),
    FormulaDefinition("vari", "VARI", ["green", "red", "blue"], indices.vari),
    FormulaDefinition("gemi", "GEMI", ["nir", "red"], indices.gemi),
    FormulaDefinition("mtvi2", "MTVI2", ["800", "550", "670"], indices.mtvi2),
    FormulaDefinition("tvi", "TVI", ["750", "550", "670"], indices.tvi),
    FormulaDefinition("tndvi", "TNDVI", ["nir", "red"], indices.tndvi),
    FormulaDefinition("logr", "LogR", ["nir", "red"], indices.log_ratio),
]


UNSUPPORTED = {
    "gvmi": "requires SWIR",
    "nbr": "requires SWIR",
    "tasseled_cap": "requires coefficients",
    "vci": "requires time series",
}


def resolve_required_bands(required: List[str]) -> Tuple[Dict[str, str], bool]:
    resolved: Dict[str, str] = {}
    used_approx = False

    for key in required:
        if key in STANDARD_BAND_MAP:
            resolved[key] = STANDARD_BAND_MAP[key]
            continue

        if key.isdigit():
            band_name, approx = approximate_band_for_wavelength(int(key))
            if band_name is None:
                raise ValueError(f"No band found for wavelength {key}")
            resolved[key] = band_name
            used_approx = used_approx or approx
            continue

        if key.lower() == "swir":
            raise ValueError("SWIR not available")

        raise ValueError(f"Unknown band spec: {key}")

    return resolved, used_approx


def shortlist() -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    for formula in FORMULAS:
        status = "supported"
        note = None
        used_approx = False
        try:
            _, used_approx = resolve_required_bands(formula.required_bands)
        except Exception as exc:
            status = "unsupported"
            note = str(exc)

        if used_approx and status == "supported":
            status = "supported_approx"
            note = "uses nearest-band approximation"

        if formula.needs_params and status != "unsupported":
            status = "requires_params"

        results.append(
            {
                "name": formula.name,
                "display_name": formula.display_name,
                "required_bands": formula.required_bands,
                "status": status,
                "note": note,
                "params": formula.params or {},
            }
        )

    for name, reason in UNSUPPORTED.items():
        results.append(
            {
                "name": name,
                "display_name": name.upper(),
                "required_bands": [],
                "status": "unsupported",
                "note": reason,
                "params": {},
            }
        )

    return results


def get_formula(name: str) -> FormulaDefinition:
    for formula in FORMULAS:
        if formula.name == name:
            return formula
    raise KeyError(f"Unknown formula: {name}")
