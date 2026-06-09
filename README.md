# Mooring Field Detection

Detect mooring fields from satellite imagery by finding dense clusters of boats (YOLO-OBB + DBSCAN).

## Quick start

```bash
pip install -e ".[dev]"
```

1. Follow [docs/GOOGLE_SETUP.md](docs/GOOGLE_SETUP.md) to create a Maps Static API key
2. Paste your key in `.env`:

```
GOOGLE_MAPS_API_KEY=your_key_here
```

3. Run the pipeline:

```bash
python -m mooring_fields.cli parse-kml
python -m mooring_fields.cli estimate    # preview API usage (free: 10k/month)
python -m mooring_fields.cli fetch       # ~615 tiles, capped at 800 calls/run
python -m mooring_fields.cli prelabel
# Human-review labels → docs/LABELING.md
python -m mooring_fields.cli train --corrected-labels
python -m mooring_fields.cli evaluate
# Writes data/evaluation_results.json and data/evaluation_clusters.kml
```

## Cost safety

- Google free tier: **10,000** Static Maps requests/month
- This project needs **~615** requests once (123 sites × 5 directions)
- `fetch` skips cached tiles and refuses to exceed `max_api_requests_per_run` (800) in `config/imagery.yaml`
- Set Google Cloud **quota cap** and **$1 budget alert** — see [docs/GOOGLE_SETUP.md](docs/GOOGLE_SETUP.md)

## Tests

```bash
pytest
```

## Project layout

- `mooring_fields.kml` — 123 labeled mooring field points
- `.env` — your API key (not committed)
- `config/` — imagery, clustering, training, split settings
- `src/mooring_fields/` — pipeline modules
- `data/` — sites manifest, imagery, labels, datasets
