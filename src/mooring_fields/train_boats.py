"""Fine-tune YOLO-OBB boat detector."""

from __future__ import annotations

from pathlib import Path

import yaml
from ultralytics import YOLO

from mooring_fields.export_dataset import export_yolo_dataset
from mooring_fields.paths import CONFIG_DIR, DATASET_DIR, RUNS_DIR


def load_training_config() -> dict:
    return yaml.safe_load((CONFIG_DIR / "training.yaml").read_text(encoding="utf-8"))


def train(
    use_corrected_labels: bool = False,
    data_yaml: Path | None = None,
    resume: bool = False,
) -> dict:
    cfg = load_training_config()
    export_yolo_dataset(use_corrected_labels=use_corrected_labels)
    yaml_path = data_yaml or DATASET_DIR / "data.yaml"

    if not yaml_path.exists():
        raise FileNotFoundError(f"Dataset not found at {yaml_path}. Run prelabel first.")

    model = YOLO(cfg["model"])
    RUNS_DIR.mkdir(parents=True, exist_ok=True)

    results = model.train(
        data=str(yaml_path),
        epochs=cfg["epochs"],
        imgsz=cfg["imgsz"],
        batch=cfg["batch"],
        patience=cfg["patience"],
        augment=True,
        degrees=cfg.get("degrees", 180),
        mosaic=cfg.get("mosaic", 1.0),
        project=str(RUNS_DIR),
        name="mooring_boats",
        exist_ok=True,
        resume=resume,
    )

    best_weights = RUNS_DIR / "mooring_boats" / "weights" / "best.pt"
    return {
        "best_weights": str(best_weights) if best_weights.exists() else None,
        "results": str(results) if results else None,
    }
