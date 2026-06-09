"""Project path helpers."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT / "config"
DATA_DIR = ROOT / "data"
KML_PATH = ROOT / "mooring_fields.kml"
SITES_JSON = DATA_DIR / "sites.json"
IMAGERY_DIR = DATA_DIR / "imagery"
PRELABELS_DIR = DATA_DIR / "prelabels"
LABELS_DIR = DATA_DIR / "labels"
DATASET_DIR = DATA_DIR / "datasets" / "mooring_boats"
RUNS_DIR = ROOT / "runs"
