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
