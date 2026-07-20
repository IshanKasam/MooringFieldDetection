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

1. **Draw candidate areas** in Google Earth and export them as a KML
   (same placemark format as `mooring_fields.kml`).

2. **Scan** — fetches satellite tiles, detects boats, clusters them into
   fields, geocodes, and writes straight into the web app's database
   (`data/mooring_fields.db`). Requires `GOOGLE_MAPS_API_KEY` in `.env`.

   ```bash
   python -m mooring_fields.cli scan --kml new_areas.kml
   # optional: --weights path.pt, --max-requests N, --db other.db
   ```

3. **Enrich** — Google Places lookup + Groq LLM research for each new
   field (requires `GOOGLE_MAPS_API_KEY` and `GROQ_API_KEY` in `.env`).
   Per-run API caps process ~20 fields at a time; repeat until done.

   ```bash
   python -m mooring_fields.cli enrich-all --only-new
   ```

4. **Review in the web app** — start backend + frontend (see above).
   New fields appear as dots on the map and rows in Records; approve
   prospects in the detail drawer, then export from the toolbar.

To re-run detection on the existing validation imagery instead of new
areas: `python -m mooring_fields.cli evaluate` (writes a new scan to the
same database; compare scans with `diff-scans <a> <b>`).
