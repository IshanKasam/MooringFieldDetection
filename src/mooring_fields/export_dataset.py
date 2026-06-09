"""Export prelabels (or human-corrected labels) to Ultralytics YOLO-OBB dataset layout."""

from __future__ import annotations

import shutil
from pathlib import Path

from mooring_fields.paths import DATASET_DIR, LABELS_DIR, PRELABELS_DIR


def export_yolo_dataset(
    use_corrected_labels: bool = False,
    output_dir: Path | None = None,
) -> Path:
    """
    Build Ultralytics dataset from prelabels or corrected labels.

    When use_corrected_labels=True, reads data/labels/{split}/ if present,
    otherwise falls back to data/prelabels/{split}/.
    """
    out = output_dir or DATASET_DIR
    train_img = out / "images" / "train"
    val_img = out / "images" / "val"
    train_lbl = out / "labels" / "train"
    val_lbl = out / "labels" / "val"

    for d in (train_img, val_img, train_lbl, val_lbl):
        d.mkdir(parents=True, exist_ok=True)

    stats = {"train": 0, "val": 0}
    for split, img_dest, lbl_dest in [
        ("train", train_img, train_lbl),
        ("val", val_img, val_lbl),
    ]:
        if use_corrected_labels and (LABELS_DIR / split).exists():
            src = LABELS_DIR / split
        else:
            src = PRELABELS_DIR / split
        if not src.exists():
            continue
        for png in sorted(src.glob("*.png")):
            shutil.copy2(png, img_dest / png.name)
            lbl = src / f"{png.stem}.txt"
            dest_lbl = lbl_dest / f"{png.stem}.txt"
            if lbl.exists():
                shutil.copy2(lbl, dest_lbl)
            else:
                dest_lbl.write_text("", encoding="utf-8")
            stats[split] += 1

    data_yaml = out / "data.yaml"
    data_yaml.write_text(
        f"path: {out.as_posix()}\n"
        "train: images/train\n"
        "val: images/val\n"
        "names:\n"
        "  0: boat\n",
        encoding="utf-8",
    )
    return out
