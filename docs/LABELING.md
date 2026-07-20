# Human Label Review Workflow

After running pre-labeling, correct boat annotations before fine-tuning.

## 1. Pre-label

```bash
python -m mooring_fields.cli prelabel
```

Outputs land in `data/prelabels/{train,val}/` as image + `.txt` YOLO-OBB pairs.

## 2. Review in an annotation tool

Pick one:

| Tool | Notes |
|------|-------|
| [Roboflow](https://roboflow.com) | Import folder, export Ultralytics OBB format |
| [Label Studio](https://labelstud.io) | Self-hosted; supports oriented boxes |
| [CVAT](https://www.cvat.ai) | Free tier; rotation boxes |

### Label format (important)

Each `.txt` line must be **Ultralytics OBB format**:

```text
0 x1 y1 x2 y2 x3 y3 x4 y4
```

- Class `0` = boat
- Eight normalized corner coordinates (0–1), not width/height format
- Prelabels from `prelabel` already use this format

### What to fix

- Add missed moored boats (small leisure craft)
- Remove false positives: waves, docks, buoys, mooring balls
- Correct corner points if the box rotation is wrong
- Single class: `boat` (id 0)

## 3. Save corrected labels

### Roboflow (recommended)

1. Export the project as **YOLOv8 Oriented Object Detection** (OBB), unzip into e.g. `yolov8_new_images/`.
2. Import into the repo (renames Roboflow filenames, maps `valid` → `val`, backfills any imagery tiles missing from the export from `data/prelabels/`):

```bash
python -m mooring_fields.cli import-roboflow-labels --source yolov8_new_images
```

This writes:

```
data/labels/train/
data/labels/val/
```

Empty `.txt` files from Roboflow are kept as-is (genuine no-boat tiles).

### Manual copy

Copy reviewed pairs to `data/labels/train/` and `data/labels/val/`. Keep the same filenames as in `data/prelabels/` (e.g. `MF_6_032D13F8_south_z18.txt`).

## 4. Train on corrected labels

```bash
python -m mooring_fields.cli train --corrected-labels
```

On Kaggle, upload `data/labels/` with `data/imagery/` and use the same flag (see [KAGGLE.md](KAGGLE.md)).

## 5. Hard negatives (recommended)

Add 30–50 tiles from nearby marinas or empty water (not on KML points) with empty `.txt` label files to reduce false mooring-field clusters.
