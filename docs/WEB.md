# Web UI (FastAPI + React)

Map + spreadsheet interface over `data/mooring_fields.db`.

## Local development

```bash
# Backend (from repo root)
pip install -e ".[web]"
mooring-web
# → http://127.0.0.1:8000/docs

# Frontend
cd web-ui
npm install
npm run dev
# → http://127.0.0.1:5173  (proxies /api → :8000)
```

Set `VITE_API_BASE_URL` only when the UI is hosted separately from the API
(e.g. Vercel → Render). Leave empty for same-origin / Docker.

## Deploy (recommended split)

1. **Backend → Render** (Docker + persistent disk at `/data` for the SQLite DB)
   - Connect this repo, use the root `Dockerfile` / `render.yaml`
   - Set `MOORING_CORS_ORIGINS` to your Vercel URL (e.g. `https://your-app.vercel.app`)
   - Upload or sync `mooring_fields.db` onto the `/data` disk (or bake a copy into the image)

2. **Frontend → Vercel**
   - Root directory: `web-ui`
   - Env: `VITE_API_BASE_URL=https://your-render-service.onrender.com`

No login is required for this build.

## Finding new mooring fields (end-to-end loop)

The trained model lives at `runs/mooring_boats/weights/best.pt`
(a copy of `final_mooring_field_detection.pt`; both are gitignored).
Commands below use it automatically when `--weights` is omitted.

### Recommended: NOAA/OSM candidates → scan → enrich

1. **Generate candidates** from NOAA Anchorages + OpenStreetMap
   marina/mooring points (ESI-style `MO` + `M` via REST — no giant
   geodatabase download). Cap sites so one run fits Google's free tier
   (~160 sites × 5 tiles = 800 API calls).

   ```bash
   python -m mooring_fields.cli generate-candidates --state MA --types MO,M \
     --max-sites 160 --out data/candidates_MA.kml
   # also: --state FL --state TX --state CA, or --bbox west,south,east,north
   ```

2. **Scan** — fetches satellite tiles into a **persistent** cache
   (`data/imagery/scan/`), detects boats, clusters them into fields,
   geocodes, and writes into `data/mooring_fields.db`. Requires
   `GOOGLE_MAPS_API_KEY` in `.env`. Re-runs skip already-downloaded tiles.

   ```bash
   python -m mooring_fields.cli scan --kml data/candidates_MA.kml --max-requests 800
   # optional: --imagery-dir PATH, --weights path.pt, --db other.db, --skip-fetch
   ```

3. **Enrich** — Google Places + Groq LLM research for each new field
   (requires `GOOGLE_MAPS_API_KEY` and `GROQ_API_KEY`). Groq searches the
   web using field coordinates/address — it does **not** look at the
   satellite tiles. Caps process ~20 fields/run; repeat until done.

   ```bash
   python -m mooring_fields.cli enrich-all --only-new
   ```

4. **Review in the web app** — start backend + frontend (see above).
   New fields appear as dots on the map and rows in Records; approve
   prospects in the detail drawer, then export from the toolbar.

### Free-tier budgeting

- `config/imagery.yaml`: `max_api_requests_per_run: 800`,
  `google_free_tier_monthly: 10000`
- Prefer `--max-sites 160` on `generate-candidates` and
  `--max-requests 800` on `scan`
- Scan one region per day if staying inside the monthly credit; cached
  tiles make partial re-runs free

### Faster detection on Kaggle GPU (recommended for Cape Cod / more states)

Local CPUs are slow for hundreds of YOLO inferences. Example — full Cape Cod:

```bash
python -m mooring_fields.cli generate-candidates \
  "--bbox=-70.75,41.50,-69.90,42.10" --types MO,M \
  --max-sites 160 --out data/candidates_CapeCod.kml
python -m mooring_fields.cli fetch-scan --kml data/candidates_CapeCod.kml --max-requests 800
python -m mooring_fields.cli package-kaggle-scan --kml data/candidates_CapeCod.kml
# git push; upload kaggle_scan_payload.zip → Kaggle Dataset; run notebooks/kaggle_scan.ipynb (GPU T4)
python -m mooring_fields.cli import-scan --from-db path/to/downloaded/mooring_fields.db
python -m mooring_fields.cli enrich-all --only-new
```

See [docs/KAGGLE.md](KAGGLE.md) § "GPU coastal scan".

### Maintenance

- Delete an old detection scan (and orphaned prospects):
  `python -m mooring_fields.cli delete-scan --scan-id N --yes`
- Compare two scans: `python -m mooring_fields.cli diff-scans A B`
- Re-run detection on existing validation imagery:
  `python -m mooring_fields.cli evaluate` (writes another scan to the same DB)

### Manual KML (optional)

You can still draw candidate placemarks in Google Earth and pass that
KML to `scan` the same way — same format as `mooring_fields.kml`.
