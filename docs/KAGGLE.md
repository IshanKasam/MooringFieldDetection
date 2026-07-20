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
