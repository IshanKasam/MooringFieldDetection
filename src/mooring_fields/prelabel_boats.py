"""Pre-label boats in imagery using YOLO-OBB (DOTA pretrained)."""

from __future__ import annotations

import shutil
from pathlib import Path

import yaml
from ultralytics import YOLO

from mooring_fields.paths import CONFIG_DIR, IMAGERY_DIR, PRELABELS_DIR


def load_training_config() -> dict:
    return yaml.safe_load((CONFIG_DIR / "training.yaml").read_text(encoding="utf-8"))


def write_obb_labels(result, label_path: Path, class_id: int = 0) -> int:
    """Write YOLO OBB labels from a single prediction result."""
    lines: list[str] = []
    if result.obb is not None:
        xywhr = result.obb.xywhr.cpu().numpy()
        for box in xywhr:
            cx, cy, w, h, angle = box
            lines.append(f"{class_id} {cx:.6f} {cy:.6f} {w:.6f} {h:.6f} {angle:.6f}")
    label_path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    return len(lines)


def prelabel_split(
    split: str,
    model_name: str | None = None,
    conf: float | None = None,
    output_dir: Path | None = None,
) -> dict:
    cfg = load_training_config()
    model_path = model_name or cfg["model"]
    confidence = conf if conf is not None else cfg.get("conf_prelabel", 0.25)

    src_dir = IMAGERY_DIR / split
    if not src_dir.exists():
        raise FileNotFoundError(f"No imagery at {src_dir}. Run fetch first.")

    out_root = output_dir or PRELABELS_DIR / split
    out_root.mkdir(parents=True, exist_ok=True)

    images = sorted(src_dir.glob("*.png"))
    if not images:
        return {"split": split, "images": 0, "detections": 0}

    model = YOLO(model_path)
    total_detections = 0

    for img in images:
        dest_img = out_root / img.name
        if not dest_img.exists():
            shutil.copy2(img, dest_img)

        results = model.predict(str(img), conf=confidence, verbose=False)
        label_path = out_root / f"{img.stem}.txt"
        total_detections += write_obb_labels(results[0], label_path)

    return {
        "split": split,
        "images": len(images),
        "detections": total_detections,
        "output_dir": str(out_root),
    }


def prelabel_all(splits: list[str] | None = None) -> dict:
    splits = splits or ["train", "val"]
    return {split: prelabel_split(split) for split in splits}
