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

Copy reviewed pairs to:

```
data/labels/train/
data/labels/val/
```

Keep the same filenames as in `data/prelabels/`.

## 4. Train on corrected labels

```bash
python -m mooring_fields.cli train --corrected-labels
```

## 5. Hard negatives (recommended)

Add 30–50 tiles from nearby marinas or empty water (not on KML points) with empty `.txt` label files to reduce false mooring-field clusters.
