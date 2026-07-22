# Running on Kaggle (GPU)

Use Kaggle for **train** (and optional **evaluate**). GPU is selected automatically via `config/training.yaml` (`device: auto`) in `src/mooring_fields/runtime.py`.

Imagery and corrected labels are **not** in GitHub — upload them as a Kaggle Dataset, then clone this repo for code.

## 1. Push code to GitHub

Commit and push this repo. `data/imagery/`, `data/prelabels/`, and `data/labels/` are gitignored.

## 2. Create a Kaggle Dataset (one-time)

Upload a zip whose paths use **forward slashes** and look like:

```
data/
  imagery/     # PNGs + JSON sidecars
  labels/      # corrected OBB .txt (after import-roboflow-labels)
  sites.json
```

Name it e.g. `mooring-field-data` → mounts at `/kaggle/input/mooring-field-data`.

If you exported labels from Roboflow locally, run this **before** zipping:

```bash
python -m mooring_fields.cli import-roboflow-labels --source yolov8_new_images
```

## 3. New Kaggle notebook

- **Settings → Accelerator → GPU T4** (or P100)
- **Settings → Internet → On**
- **Add data →** your `mooring-field-data` dataset
- **Add-ons → Secrets →** `GOOGLE_MAPS_API_KEY` only if running `evaluate` / `fetch`

**Recommended:** File → Import Notebook → upload `notebooks/kaggle_pipeline.ipynb` from this repo (or copy cells below).

## 4. Notebook cells (call package code)

```python
# Cell 1 — clone + install
import subprocess, sys, shutil
from pathlib import Path
REPO = "/kaggle/working/MooringFieldDetection"
URL = "https://github.com/IshanKasam/MooringFieldDetection.git"
if Path(REPO).exists():
    shutil.rmtree(REPO)
subprocess.run(["git", "clone", URL, REPO], check=True)
%cd /kaggle/working/MooringFieldDetection
subprocess.run([sys.executable, "-m", "pip", "install", "-q", "-e", "."], check=True)
```

```python
# Cell 2 — link dataset + GPU check  (runtime.bootstrap_kaggle)
import json
from mooring_fields.runtime import bootstrap_kaggle
print(json.dumps(bootstrap_kaggle(), indent=2))
```

```python
# Cell 3 — train on corrected labels  (train_boats.train)
import json
from mooring_fields.train_boats import train
from mooring_fields.runtime import publish_outputs

report = train(use_corrected_labels=True)
report["published"] = publish_outputs()
print(json.dumps({k: v for k, v in report.items() if k != "results"}, indent=2))
```

```python
# Cell 4 — evaluate (optional)  (evaluate.evaluate_val)
import json
from mooring_fields.evaluate import evaluate_val
from mooring_fields.runtime import publish_outputs

report = evaluate_val()
report["published"] = publish_outputs()
print(json.dumps({k: v for k, v in report.items() if k not in ("per_site", "clusters")}, indent=2))
```

Equivalent CLI (same entry points):

```bash
python -m mooring_fields.cli kaggle-setup
python -m mooring_fields.cli train --corrected-labels --publish
python -m mooring_fields.cli evaluate --publish
```

Skip `fetch` / `prelabel` when the dataset already has `data/imagery` + `data/labels`.

## 5. Download results

Artifacts land in `/kaggle/working/mooring_outputs/` via `publish_outputs()`.

From the notebook **Output** tab:

- `mooring_boats/weights/best.pt`
- `evaluation_results.json` / `evaluation_clusters.kml` (if evaluate ran)

## GPU coastal scan (multi-state, cached tiles)

Local CPUs are slow for hundreds of YOLO inferences. Use a **separate** notebook
[`notebooks/kaggle_scan.ipynb`](../notebooks/kaggle_scan.ipynb) to detect on
already-fetched tiles with a free T4. Code clones from **GitHub**; tiles + weights
come from a Kaggle Dataset you upload.

Stay under ~**160 sites × 5 tiles = 800** Google Static Maps calls per free-tier day
(~12 such runs/month under the 10 000 monthly cap).

Enrichment after import uses **Groq** for harbor research and supply chain
(`research_provider: groq` in `config/enrichment.yaml`). Places stays on Google.
Loop `enrich-all --only-new` / `enrich-supply-chain` until the queue is empty.

### Local prep — Cape Cod

```bash
# Named region (same bbox as --bbox=-70.75,41.50,-69.90,42.10)
python -m mooring_fields.cli generate-candidates \
  --region CapeCod --types MO,M --max-sites 160 --out data/candidates_CapeCod.kml

python -m mooring_fields.cli fetch-scan \
  --kml data/candidates_CapeCod.kml --max-requests 800

python -m mooring_fields.cli package-kaggle-scan \
  --kml data/candidates_CapeCod.kml --out kaggle_scan_CapeCod.zip

git push   # so Kaggle Cell 1 clones latest code
```

Upload `kaggle_scan_CapeCod.zip` as a Kaggle Dataset (e.g. `mooring-scan-capecod`).
Existing cache: **53 sites / 265 tiles** for Cape Cod.

### Local prep — Florida (regional pages, do not use one statewide cap)

A single `--state FL --max-sites 160` **silently drops** the rest of the coast.
Use named `FL_*` regions and auto-paging:

| Region | Intent |
|--------|--------|
| `FL_panhandle` | Pensacola–Apalachicola |
| `FL_big_bend` | Steinhatchee–Cedar Key |
| `FL_tampa_sw` | Tampa Bay–Naples |
| `FL_keys` | Keys |
| `FL_se_atlantic` | Miami–West Palm |
| `FL_ne_atlantic` | Space Coast–Jacksonville |

```bash
# Write candidates_<region>_pN.kml for every FL coast (≤160 sites each)
python -m mooring_fields.cli generate-candidates-batch \
  --regions FL_panhandle,FL_big_bend,FL_tampa_sw,FL_keys,FL_se_atlantic,FL_ne_atlantic \
  --max-sites 160 --out-dir data

# One free-tier Maps day per page (example: Tampa page 0)
python -m mooring_fields.cli fetch-scan \
  --kml data/candidates_FL_tampa_sw_p0.kml --max-requests 800
python -m mooring_fields.cli package-kaggle-scan \
  --kml data/candidates_FL_tampa_sw_p0.kml --out kaggle_scan_FL_tampa_sw_p0.zip
```

Or page manually: `--region FL_tampa_sw --max-sites 160 --offset 160`.

### Free-tier calendar (Maps Static)

- **Day 1:** Cape Cod (often already cached) → Kaggle detect → import → enrich
- **Days 2+:** one FL `*_pN.kml` fetch (≤800 new calls) → package → Kaggle → import → enrich
- Cached tiles are free on re-fetch; prefer one 800-run per day if staying inside monthly credit

### On Kaggle

- Settings → **GPU T4**, Internet **On**
- **Add data** → that batch’s dataset (Cape Cod or one FL page)
- Import / copy [`notebooks/kaggle_scan.ipynb`](../notebooks/kaggle_scan.ipynb), run cells in order
- Save Version → download `scan_out/mooring_fields.db`

Detection uses `scan --skip-fetch` so **no Google Static Maps calls** happen on Kaggle.
Do **not** run enrich on Kaggle.

### Merge back locally

```bash
python -m mooring_fields.cli import-scan --from-db path/to/downloaded/mooring_fields.db
python -m mooring_fields.cli enrich-all --only-new   # Places + Groq; repeat until done
# If supply chain was blocked earlier:
python -m mooring_fields.cli enrich-supply-chain
```

Then hard-refresh the web app.

## GPU settings

Edit `config/training.yaml`:

| Key | Default | Notes |
|-----|---------|-------|
| `device` | `auto` | Uses GPU 0 on Kaggle |
| `batch_gpu` | `8` | Lower to `4` if OOM |
| `predict_batch_gpu` | `32` | Batched prelabel inference |
| `amp` | `true` | Mixed precision training |
| `half` | `true` | FP16 inference on GPU |

## Custom input dataset path

```bash
python -m mooring_fields.cli kaggle-setup --input-data /kaggle/input/your-dataset-name
```

Or set `MOORING_INPUT_DATA=/kaggle/input/your-dataset-name`.
