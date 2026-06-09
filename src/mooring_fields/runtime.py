"""Runtime helpers: Kaggle detection, GPU device selection, data bootstrap."""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

import yaml

from mooring_fields.paths import CONFIG_DIR, DATA_DIR, ROOT


def is_kaggle() -> bool:
    return os.environ.get("KAGGLE_KERNEL_RUN_TYPE") is not None


def cuda_available() -> bool:
    try:
        import torch

        return bool(torch.cuda.is_available())
    except ImportError:
        return False


def gpu_name() -> str | None:
    if not cuda_available():
        return None
    import torch

    return torch.cuda.get_device_name(0)


def load_kaggle_config() -> dict:
    path = CONFIG_DIR / "kaggle.yaml"
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def load_training_config() -> dict:
    return yaml.safe_load((CONFIG_DIR / "training.yaml").read_text(encoding="utf-8"))


def resolve_device(cfg: dict | None = None) -> str | int:
    """Pick Ultralytics device: 0 for CUDA, 'cpu' otherwise."""
    cfg = cfg or load_training_config()
    device = cfg.get("device", "auto")
    if device == "auto":
        return 0 if cuda_available() else "cpu"
    return device


def resolve_batch(cfg: dict | None = None) -> int:
    cfg = cfg or load_training_config()
    if cuda_available():
        return int(cfg.get("batch_gpu", cfg.get("batch", 8)))
    return int(cfg.get("batch_cpu", cfg.get("batch", 8)))


def resolve_workers(cfg: dict | None = None) -> int:
    cfg = cfg or load_training_config()
    if cuda_available():
        return int(cfg.get("workers_gpu", cfg.get("workers", 4)))
    return int(cfg.get("workers_cpu", cfg.get("workers", 2)))


def resolve_predict_batch(cfg: dict | None = None) -> int:
    cfg = cfg or load_training_config()
    if cuda_available():
        return int(cfg.get("predict_batch_gpu", cfg.get("predict_batch", 16)))
    return int(cfg.get("predict_batch_cpu", cfg.get("predict_batch", 4)))


def inference_kwargs(cfg: dict | None = None) -> dict[str, Any]:
    """Keyword args for YOLO.predict on the current runtime."""
    cfg = cfg or load_training_config()
    kwargs: dict[str, Any] = {"device": resolve_device(cfg), "verbose": False}
    if cuda_available() and cfg.get("half", True):
        kwargs["half"] = True
    return kwargs


def training_kwargs(cfg: dict | None = None) -> dict[str, Any]:
    """Extra keyword args for YOLO.train on the current runtime."""
    cfg = cfg or load_training_config()
    kwargs: dict[str, Any] = {
        "device": resolve_device(cfg),
        "batch": resolve_batch(cfg),
        "workers": resolve_workers(cfg),
    }
    if cuda_available():
        kwargs["amp"] = cfg.get("amp", True)
    return kwargs


def load_kaggle_secrets() -> dict[str, bool]:
    """Load GOOGLE_MAPS_API_KEY from Kaggle Secrets if available."""
    loaded: dict[str, bool] = {"GOOGLE_MAPS_API_KEY": False}
    if os.environ.get("GOOGLE_MAPS_API_KEY", "").strip():
        loaded["GOOGLE_MAPS_API_KEY"] = True
        return loaded
    try:
        from kaggle_secrets import UserSecretsClient

        key = UserSecretsClient().get_secret("GOOGLE_MAPS_API_KEY")
        if key:
            os.environ["GOOGLE_MAPS_API_KEY"] = key.strip()
            loaded["GOOGLE_MAPS_API_KEY"] = True
    except Exception:
        pass
    return loaded


def _input_data_root(explicit: Path | None = None) -> Path | None:
    if explicit and explicit.exists():
        return explicit
    if os.environ.get("MOORING_INPUT_DATA"):
        p = Path(os.environ["MOORING_INPUT_DATA"])
        if p.exists():
            return p
    kaggle_cfg = load_kaggle_config()
    for candidate in kaggle_cfg.get("input_datasets", []):
        p = Path(candidate)
        if p.exists():
            return p
    default = Path("/kaggle/input/mooring-field-data")
    if default.exists():
        return default
    return None


def _has_imagery() -> bool:
    for split in ("train", "val"):
        d = DATA_DIR / "imagery" / split
        if d.exists() and any(d.glob("*.png")):
            return True
    return False


def link_or_copy_data(src_data: Path, dest_data: Path) -> list[str]:
    """Link (preferred on Kaggle) or copy data artifacts into the repo data/ tree."""
    dest_data.mkdir(parents=True, exist_ok=True)
    actions: list[str] = []

    for name in ("imagery", "prelabels", "labels"):
        src = src_data / name
        dest = dest_data / name
        if not src.exists() or dest.exists():
            continue
        if is_kaggle():
            dest.symlink_to(src, target_is_directory=True)
            actions.append(f"linked {name}")
        else:
            if src.is_dir():
                shutil.copytree(src, dest)
            else:
                shutil.copy2(src, dest)
            actions.append(f"copied {name}")

    sites_src = src_data / "sites.json"
    sites_dest = dest_data / "sites.json"
    if sites_src.exists() and not sites_dest.exists():
        if is_kaggle():
            sites_dest.symlink_to(sites_src)
        else:
            shutil.copy2(sites_src, sites_dest)
        actions.append("linked sites.json" if is_kaggle() else "copied sites.json")

    return actions


def bootstrap_kaggle(input_data: Path | None = None) -> dict:
    """
    Prepare a Kaggle notebook runtime: secrets, optional input dataset, cwd.

    Call once after cloning the repo into /kaggle/working.
    """
    os.chdir(ROOT)
    info: dict[str, Any] = {
        "root": str(ROOT),
        "kaggle": is_kaggle(),
        "cuda": cuda_available(),
        "gpu": gpu_name(),
        "device": resolve_device(),
        "batch": resolve_batch(),
        "predict_batch": resolve_predict_batch(),
        "has_imagery": _has_imagery(),
        "data_actions": [],
        "secrets": {},
    }

    if is_kaggle():
        info["secrets"] = load_kaggle_secrets()

    src = _input_data_root(input_data)
    if src and not _has_imagery():
        src_data = src / "data" if (src / "data").exists() else src
        if src_data.exists():
            info["data_actions"] = link_or_copy_data(src_data, DATA_DIR)
            info["has_imagery"] = _has_imagery()

    return info


def publish_outputs(dest: Path | None = None) -> dict:
    """Copy pipeline artifacts to a persistent output directory (Kaggle working)."""
    kaggle_cfg = load_kaggle_config()
    default_dest = Path(
        os.environ.get(
            "MOORING_OUTPUT_DIR",
            kaggle_cfg.get("output_dir", "/kaggle/working/mooring_outputs"),
        )
    )
    out = dest or default_dest
    out.mkdir(parents=True, exist_ok=True)

    copied: list[str] = []
    candidates = [
        ROOT / "runs" / "mooring_boats",
        DATA_DIR / "evaluation_results.json",
        DATA_DIR / "evaluation_clusters.kml",
        DATA_DIR / "prelabels",
        DATA_DIR / "datasets" / "mooring_boats",
    ]
    for src in candidates:
        if not src.exists():
            continue
        target = out / src.name
        if src.is_dir():
            shutil.copytree(src, target, dirs_exist_ok=True)
        else:
            shutil.copy2(src, target)
        copied.append(src.name)

    return {"output_dir": str(out), "copied": copied}
