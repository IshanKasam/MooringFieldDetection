# Mooring Field Detection

Detect mooring fields from satellite imagery by finding dense clusters of boats (YOLO-OBB + DBSCAN).

## Setup

```bash
# Install (from project root)
pip install -e ".[dev]"

# Configure API key
copy .env.example .env
# Edit .env and set GOOGLE_MAPS_API_KEY
```

Enable **Maps Static API** in Google Cloud Console. Earth Pro subscription does not replace API billing.

## Pipeline

```bash
# 1. Parse KML and create train/val split
python -m mooring_fields.cli parse-kml

# 2. Download satellite tiles
python -m mooring_fields.cli fetch

# 3. Pre-label boats with YOLO-OBB
python -m mooring_fields.cli prelabel

# 4. Human-review labels (see docs/LABELING.md), then train
python -m mooring_fields.cli train
# Or with corrected labels:
python -m mooring_fields.cli train --corrected-labels

# 5. Evaluate Hit@150m on validation KML sites
python -m mooring_fields.cli evaluate
```

## Tests

```bash
pytest
```

## Project layout

- `mooring_fields.kml` — 123 labeled mooring field points
- `config/` — imagery, clustering, training, split settings
- `src/mooring_fields/` — pipeline modules
- `data/` — sites manifest, imagery, labels, datasets
- `docs/decisions/` — architecture decision records
