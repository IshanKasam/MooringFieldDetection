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
DB_PATH = DATA_DIR / "mooring_fields.db"
GEOCODE_CACHE = DATA_DIR / "geocode_cache.json"
PLACES_CACHE = DATA_DIR / "places_cache.json"
GEMINI_CACHE = DATA_DIR / "gemini_cache.json"
PROSPECTS_EXPORT = DATA_DIR / "prospects_export.xlsx"
