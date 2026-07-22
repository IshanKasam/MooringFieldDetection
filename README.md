# Mooring Field Detection

In-app coastal prospecting: pick a coastline → scan satellite imagery → review mooring fields on a map → enrich contacts → export a spreadsheet.

## Product loop (web app)

```bash
pip install -e ".[web]"
# set GOOGLE_MAPS_API_KEY and GROQ_API_KEY in .env
mooring-web          # API :8000
cd web-ui && npm install && npm run dev   # UI :5173
```

In the toolbar:

1. **Scan coast** — choose a named region (Cape Cod, FL_*), respect Maps quota chip
2. Watch the map refresh when the job finishes
3. **Enrich** places / research / supply chain
4. Approve prospects in the detail drawer; **Export Excel**

Detection needs a GPU for large coasts (CUDA on the same machine as `mooring-web`). Without CUDA, expect slow runs. Kaggle remains an ops escape hatch — see [docs/KAGGLE.md](docs/KAGGLE.md).

## Pipeline / training (CLI)

```bash
pip install -e ".[dev]"
python -m mooring_fields.cli parse-kml
python -m mooring_fields.cli fetch
python -m mooring_fields.cli train
python -m mooring_fields.cli evaluate
```

Full command list: `python -m mooring_fields.cli --help` (or see [docs/WEB.md](docs/WEB.md)).

## Docs

| Doc | Topic |
|-----|--------|
| [docs/WEB.md](docs/WEB.md) | Web UI, deploy, in-app scan |
| [docs/KAGGLE.md](docs/KAGGLE.md) | GPU coastal scan (optional) |
| [docs/ENRICHMENT.md](docs/ENRICHMENT.md) | Places + Groq/Gemini |
| [docs/GOOGLE_SETUP.md](docs/GOOGLE_SETUP.md) | Maps Static API key |

## Architecture note

Shared scan logic lives in `mooring_fields.scan_pipeline` (CLI + `/api/jobs/scan`). Cloud GPU adapters: `mooring_fields.cloud_gpu` (pluggable; local passthrough by default).
