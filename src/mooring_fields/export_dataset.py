"""Export prelabels (or human-corrected labels) to Ultralytics YOLO-OBB dataset layout."""

from __future__ import annotations

import shutil
from pathlib import Path

from mooring_fields.label_utils import sanitize_label_text, validate_label_dir
from mooring_fields.paths import DATASET_DIR, IMAGERY_DIR, LABELS_DIR, PRELABELS_DIR


def export_yolo_dataset(
    use_corrected_labels: bool = False,
    output_dir: Path | None = None,
    validate: bool = True,
) -> Path:
    """
    Build Ultralytics OBB dataset from prelabels or corrected labels.

    Labels must use Ultralytics OBB format: class + 8 normalized corner coordinates.
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
        img_src = IMAGERY_DIR / split
        if use_corrected_labels and (LABELS_DIR / split).exists():
            lbl_src = LABELS_DIR / split
        else:
            lbl_src = PRELABELS_DIR / split
        if not img_src.exists():
            continue
        if validate and lbl_src.exists() and list(lbl_src.glob("*.txt")):
            errors = validate_label_dir(lbl_src)
            if errors:
                raise ValueError(
                    f"Invalid OBB labels in {lbl_src}:\n" + "\n".join(errors[:5])
                )
        for png in sorted(img_src.glob("*.png")):
            shutil.copy2(png, img_dest / png.name)
            lbl = lbl_src / f"{png.stem}.txt" if lbl_src.exists() else None
            dest_lbl = lbl_dest / f"{png.stem}.txt"
            if lbl and lbl.exists():
                dest_lbl.write_text(
                    sanitize_label_text(lbl.read_text(encoding="utf-8")),
                    encoding="utf-8",
                )
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
