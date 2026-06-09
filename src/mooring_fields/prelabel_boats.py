"""Pre-label boats in imagery using YOLO-OBB (DOTA pretrained)."""

from __future__ import annotations

import shutil
from pathlib import Path

import yaml
from ultralytics import YOLO

from mooring_fields.label_utils import write_obb_labels
from mooring_fields.paths import CONFIG_DIR, IMAGERY_DIR, PRELABELS_DIR
from mooring_fields.runtime import cuda_available, gpu_name, inference_kwargs, resolve_predict_batch


def load_training_config() -> dict:
    return yaml.safe_load((CONFIG_DIR / "training.yaml").read_text(encoding="utf-8"))


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
    predict_kw = inference_kwargs(cfg)
    batch_size = resolve_predict_batch(cfg)
    total_detections = 0
    skipped = 0
    pending: list[Path] = []

    for img in images:
        dest_img = out_root / img.name
        label_path = out_root / f"{img.stem}.txt"
        if not dest_img.exists():
            shutil.copy2(img, dest_img)

        if label_path.exists():
            skipped += 1
            total_detections += sum(
                1 for line in label_path.read_text(encoding="utf-8").splitlines() if line.strip()
            )
        else:
            pending.append(img)

    for start in range(0, len(pending), batch_size):
        chunk = pending[start : start + batch_size]
        results = model.predict(
            [str(p) for p in chunk],
            conf=confidence,
            batch=min(batch_size, len(chunk)),
            **predict_kw,
        )
        for img, result in zip(chunk, results):
            label_path = out_root / f"{img.stem}.txt"
            total_detections += write_obb_labels(result, label_path)

        done = skipped + min(start + batch_size, len(pending))
        if done % 25 < batch_size or start + batch_size >= len(pending):
            print(f"  [{split}] {done}/{len(images)} images", flush=True)

    labeled = len(list(out_root.glob("*.txt")))
    return {
        "split": split,
        "images": len(images),
        "labeled": labeled,
        "skipped_existing": skipped,
        "complete": labeled >= len(images),
        "detections": total_detections,
        "cuda": cuda_available(),
        "gpu": gpu_name(),
        "predict_batch": batch_size,
        "output_dir": str(out_root),
    }


def prelabel_all(splits: list[str] | None = None) -> dict:
    splits = splits or ["train", "val"]
    return {split: prelabel_split(split) for split in splits}
