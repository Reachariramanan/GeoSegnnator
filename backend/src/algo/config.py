from pathlib import Path

# algo -> src -> backend -> GeoSegmenter
WORKSPACE_ROOT = Path(__file__).resolve().parents[3]
BAND_METADATA_PATH = WORKSPACE_ROOT / "data" / "superdove_metadata_report.json"
OUTPUT_DIR = WORKSPACE_ROOT / "backend" / "data" / "outputs"

DEFAULT_SCALE_FACTOR = 10000.0
SCALE_MAX_CUTOFF = 1.5

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
