"""Fine-tune YOLO-OBB boat detector."""

from __future__ import annotations

from pathlib import Path

import yaml
from ultralytics import YOLO

from mooring_fields.export_dataset import export_yolo_dataset
from mooring_fields.label_utils import validate_label_dir
from mooring_fields.paths import CONFIG_DIR, DATASET_DIR, IMAGERY_DIR, LABELS_DIR, PRELABELS_DIR, RUNS_DIR
from mooring_fields.runtime import cuda_available, gpu_name, training_kwargs


def load_training_config() -> dict:
    return yaml.safe_load((CONFIG_DIR / "training.yaml").read_text(encoding="utf-8"))


def train(
    use_corrected_labels: bool = False,
    data_yaml: Path | None = None,
    resume: bool = False,
) -> dict:
    cfg = load_training_config()

    if use_corrected_labels:
        missing = [s for s in ("train", "val") if not (LABELS_DIR / s).exists()]
        if missing:
            raise FileNotFoundError(
                f"--corrected-labels requires data/labels/{{train,val}}/. "
                f"Missing: {missing}. Review prelabels per docs/LABELING.md first."
            )
        for split in ("train", "val"):
            errors = validate_label_dir(LABELS_DIR / split)
            if errors:
                raise ValueError(
                    f"Invalid corrected labels in data/labels/{split}/:\n"
                    + "\n".join(errors[:5])
                )
    else:
        if not PRELABELS_DIR.exists():
            raise FileNotFoundError("Run prelabel before train.")
        for split in ("train", "val"):
            img_dir = IMAGERY_DIR / split
            lbl_dir = PRELABELS_DIR / split
            imgs = sorted(img_dir.glob("*.png")) if img_dir.exists() else []
            if not imgs:
                continue
            missing = [p for p in imgs if not (lbl_dir / p.with_suffix(".txt").name).exists()]
            if missing:
                raise FileNotFoundError(
                    f"Prelabel incomplete for {split}: {len(missing)} images lack labels. "
                    "Run: python -m mooring_fields.cli prelabel"
                )

    export_yolo_dataset(use_corrected_labels=use_corrected_labels)
    yaml_path = data_yaml or DATASET_DIR / "data.yaml"

    if not yaml_path.exists():
        raise FileNotFoundError(f"Dataset not found at {yaml_path}. Run prelabel first.")

    model = YOLO(cfg["model"])
    RUNS_DIR.mkdir(parents=True, exist_ok=True)

    train_kw = training_kwargs(cfg)
    results = model.train(
        data=str(yaml_path),
        task="obb",
        epochs=cfg["epochs"],
        imgsz=cfg["imgsz"],
        patience=cfg["patience"],
        augment=True,
        degrees=cfg.get("degrees", 180),
        mosaic=cfg.get("mosaic", 1.0),
        project=str(RUNS_DIR),
        name="mooring_boats",
        exist_ok=True,
        resume=resume,
        **train_kw,
    )

    best_weights = RUNS_DIR / "mooring_boats" / "weights" / "best.pt"
    return {
        "best_weights": str(best_weights) if best_weights.exists() else None,
        "used_corrected_labels": use_corrected_labels,
        "cuda": cuda_available(),
        "gpu": gpu_name(),
        "device": train_kw.get("device"),
        "batch": train_kw.get("batch"),
        "results": str(results) if results else None,
    }
