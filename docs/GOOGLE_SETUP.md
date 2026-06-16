# Google Maps Platform Setup

## APIs used

| API | Pipeline step |
|-----|----------------|
| Maps Static API | `fetch` — satellite tiles |
| Geocoding API | `evaluate`, `scan` — reverse geocode fields |
| Places API (New) | `enrich-places` — marina/harbor lookup |

## 1. Create key

1. Open [Google Cloud Console](https://console.cloud.google.com/)
2. Create or select a project
3. Enable billing (card required; you stay at $0 within free tier)
4. Go to **APIs & Services → Library** → enable **Maps Static API**, **Geocoding API**, and **Places API (New)**
5. Go to **Credentials → Create credentials → API key**
6. **Regenerate** any key that was ever shared publicly

## 2. Paste key in `.env`

Open `.env` in the project root:

```
GOOGLE_MAPS_API_KEY=paste_your_key_here
GEMINI_API_KEY=paste_your_gemini_key_here
```

Save the file. Never commit `.env` or paste the key in chat.

## 3. Restrict the key

Edit the key in Credentials:

- **API restrictions:** Maps Static API, Geocoding API, Places API (New)
- **Application restrictions:** IP address (recommended) or None for local dev

## 4. Cap quota (prevents surprise charges)

**APIs & Services → Maps Static API → Quotas**

Set **Requests per day** to a low number (e.g. `100`). Your full download needs ~615 calls total; at 100/day you finish in about a week, all free.

## 5. Billing alert

**Billing → Budgets → Create budget** → set `$1` alert at 50%, 90%, 100%.

## 6. Run the pipeline

```bash
python -m mooring_fields.cli estimate    # check cost before downloading
python -m mooring_fields.cli fetch       # download tiles (cached after first run)
python -m mooring_fields.cli prelabel
# Review labels in data/prelabels/ → copy fixes to data/labels/
python -m mooring_fields.cli train --corrected-labels
python -m mooring_fields.cli evaluate
```

## Enrichment (customer list)

After detection, build a prospect Excel from `mooring_fields.db`:

```bash
pip install -e ".[enrichment]"
python -m mooring_fields.cli estimate-enrichment
python -m mooring_fields.cli enrich-all --limit 5   # mock provider by default
python -m mooring_fields.cli export-prospects
```

See [docs/ENRICHMENT.md](docs/ENRICHMENT.md).
