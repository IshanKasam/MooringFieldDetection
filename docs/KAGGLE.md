# Running on Kaggle (GPU)

Use Kaggle for **prelabel**, **train**, and **evaluate** — these steps use the GPU automatically when available.

`fetch` is optional on Kaggle if you upload imagery as a Kaggle Dataset (recommended).

## 1. Push code to GitHub

Commit and push this repo. `data/imagery/`, `data/prelabels/`, and `data/labels/` are gitignored — upload them separately (step 2).

## 2. Create a Kaggle Dataset (one-time)

Zip and upload your local artifacts:

```
data/
  imagery/     # 615 PNGs + JSON sidecars
  labels/      # human-corrected OBB .txt (after import-roboflow-labels)
  prelabels/   # optional if you will re-run prelabel on GPU
  sites.json
```

Name the dataset e.g. `mooring-field-data`. It mounts at `/kaggle/input/mooring-field-data`.

If you exported labels from Roboflow locally, run this **before** zipping:

```bash
python -m mooring_fields.cli import-roboflow-labels --source yolov8_new_images
```

## 3. New Kaggle notebook

- **Settings → Accelerator → GPU** (P100/T4)
- **Settings → Internet → On**
- **Add data →** your `mooring-field-data` dataset
- **Add-ons → Secrets →** add `GOOGLE_MAPS_API_KEY` (only if running `fetch` on Kaggle)

## 4. Notebook cells

```bash
# Clone (replace with your repo URL)
cd /kaggle/working
git clone https://github.com/YOUR_USER/MooringFieldDetection.git
cd MooringFieldDetection
pip install -q -e .
```

```bash
# Bootstrap: link input dataset, load secrets, print GPU info
python -m mooring_fields.cli kaggle-setup
```

Expected output includes `"cuda": true`, `"gpu": "Tesla P100..."`, `"batch": 16`.

```bash
# GPU steps (skip fetch if imagery was linked)
python -m mooring_fields.cli prelabel   # optional if prelabels uploaded
# Prefer corrected labels when data/labels/ is in the dataset:
python -m mooring_fields.cli train --corrected-labels
# Or: python -m mooring_fields.cli train   # uses prelabels only
python -m mooring_fields.cli evaluate --publish
```

Or open `notebooks/kaggle_pipeline.ipynb` in Kaggle (File → Import notebook).

## 5. Download results

Artifacts are copied to `/kaggle/working/mooring_outputs/` when you use `--publish` or:

```bash
python -m mooring_fields.cli publish-outputs
```

Download from the notebook **Output** tab:

- `mooring_boats/` — training run + `weights/best.pt`
- `evaluation_results.json`
- `evaluation_clusters.kml`

## GPU settings

Edit `config/training.yaml`:

| Key | Default | Notes |
|-----|---------|-------|
| `device` | `auto` | Uses GPU 0 on Kaggle |
| `batch_gpu` | `16` | Lower to `8` if OOM on P100 |
| `predict_batch_gpu` | `32` | Batched prelabel inference |
| `amp` | `true` | Mixed precision training |
| `half` | `true` | FP16 inference on GPU |

## Custom input dataset path

```bash
python -m mooring_fields.cli kaggle-setup --input-data /kaggle/input/your-dataset-name
```

Or set environment variable `MOORING_INPUT_DATA=/kaggle/input/your-dataset-name`.
