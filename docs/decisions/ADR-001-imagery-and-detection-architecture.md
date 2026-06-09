# ADR-001: Imagery API and Two-Stage Detection Architecture

## Status

Accepted

## Date

2026-06-09

## Context

We need to detect mooring fields worldwide. A mooring field is defined as a dense cluster of moored boats visible in satellite imagery — not individual mooring balls. We have 123 labeled KML point locations in New England as ground truth.

Constraints:

- Google Earth Pro ($75/mo) is a desktop/web product and does **not** include free Maps Platform API access
- Earth Pro license prohibits mass imagery download for ML datasets
- Boat-sized objects require sub-meter to ~1 m ground resolution (zoom 18–20)
- Initial scope: validate on held-out KML sites before global coastal scan

## Options Considered

### Option A: Google Maps Static API (`maptype=satellite`)

- Pros: Same imagery family as Google Earth; simple HTTP API; ~10k free requests/month
- Cons: Per-tile billing beyond free tier; ToS restricts bulk storage; EEA accounts may lose satellite maptype

### Option B: Google Earth Engine (NAIP / Sentinel)

- Pros: Legitimate export for ML; NAIP ~0.6 m in US
- Cons: Separate signup/approval; NAIP US-only; Sentinel 10 m too coarse for small boats globally

### Option C: Scrape Google Earth Pro desktop

- Pros: No API cost
- Cons: Violates ToS; not automatable at scale; legally risky

### Detection architectures

1. **Boat detector + spatial clustering** — YOLO-OBB finds boats; DBSCAN groups them into mooring-field candidates
2. **Single image classifier** — classifies whole tile as mooring field or not
3. **Region detector** — one bounding box per field

## Decision

1. **Imagery:** Use **Google Maps Static API** for training and validation tiles. Optionally supplement US training with Earth Engine NAIP exports later.

2. **Detection:** Use **two-stage pipeline** (Option 1):
   - Stage A: Fine-tune YOLO-OBB (`yolov8m-obb`) on boat annotations
   - Stage B: DBSCAN on boat centroids with `min_boats >= 5`, `eps ~ 60 m`

3. **Validation:** KML points are field-level targets. Success metric: **Hit@150 m** — a qualifying cluster within 150 m of each held-out KML point.

4. **API keys:** Store `GOOGLE_MAPS_API_KEY` in `.env`; never commit.

## Consequences

- User must enable Google Cloud billing and Maps Static API (Earth Pro alone is insufficient)
- Phase 1 imagery cost fits free tier (~500–750 tiles)
- Global scan deferred until val Hit@R ≥ 80%
- Human label review required; DOTA pretrained weights need domain fine-tuning

## References

- [Maps Static API](https://developers.google.com/maps/documentation/maps-static)
- [Google Earth Platform Terms](https://www.google.ca/help/terms_maps-earth/)
- [Earth Engine ML guide](https://developers.google.com/earth-engine/guides/machine-learning)
