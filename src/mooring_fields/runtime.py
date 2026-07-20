"""Runtime helpers: Kaggle detection, GPU device selection, data bootstrap."""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

import yaml

from mooring_fields.paths import CONFIG_DIR, DATA_DIR, DATASET_DIR, ROOT


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


def _split_png_count(imagery_root: Path, split: str) -> int:
    d = imagery_root / split
    if not d.is_dir():
        return 0
    return sum(1 for _ in d.glob("*.png"))


def _split_txt_count(labels_root: Path, split: str) -> int:
    d = labels_root / split
    if not d.is_dir():
        return 0
    return sum(1 for _ in d.glob("*.txt"))


def _has_imagery() -> bool:
    return _split_png_count(DATA_DIR / "imagery", "train") > 0 and _split_png_count(
        DATA_DIR / "imagery", "val"
    ) > 0


def _has_labels() -> bool:
    return _split_txt_count(DATA_DIR / "labels", "train") > 0 and _split_txt_count(
        DATA_DIR / "labels", "val"
    ) > 0


def _is_payload_dir(path: Path) -> bool:
    """True if path contains imagery/train/*.png (Kaggle zip layout)."""
    return _split_png_count(path / "imagery", "train") > 0


def resolve_data_payload(root: Path) -> Path | None:
    """
    Find the directory that contains imagery/ (and usually labels/).

    Accepts:
      root/data/imagery/...
      root/imagery/...
      root/<nested>/data/imagery/...
    """
    if not root.exists():
        return None
    candidates = [root / "data", root]
    if root.is_dir():
        for child in sorted(root.iterdir()):
            if child.is_dir():
                candidates.extend([child / "data", child])
    for candidate in candidates:
        if _is_payload_dir(candidate):
            return candidate
    return None


def discover_kaggle_input_data(explicit: Path | None = None) -> Path | None:
    """Locate an attached Kaggle dataset mount that contains mooring imagery."""
    if explicit is not None:
        return resolve_data_payload(explicit) if explicit.exists() else None

    if os.environ.get("MOORING_INPUT_DATA"):
        p = Path(os.environ["MOORING_INPUT_DATA"])
        payload = resolve_data_payload(p) if p.exists() else None
        if payload is not None:
            return payload

    kaggle_cfg = load_kaggle_config()
    for candidate in kaggle_cfg.get("input_datasets", []):
        p = Path(candidate)
        payload = resolve_data_payload(p) if p.exists() else None
        if payload is not None:
            return payload

    input_root = Path("/kaggle/input")
    if not input_root.is_dir():
        return None

    preferred = [Path(c).name for c in kaggle_cfg.get("input_datasets", [])]
    preferred.extend(["mooring-field-data", "mooringfielddetection-data"])

    ordered: list[Path] = []
    for name in preferred:
        p = input_root / name
        if p.exists() and p not in ordered:
            ordered.append(p)
    for p in sorted(input_root.iterdir()):
        if p.is_dir() and p not in ordered:
            ordered.append(p)

    for mount in ordered:
        payload = resolve_data_payload(mount)
        if payload is not None:
            return payload
    return None


def _link_or_copy_tree(src: Path, dest: Path) -> str:
    if dest.exists() or dest.is_symlink():
        return f"skip existing {dest.name}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    if is_kaggle():
        dest.symlink_to(src, target_is_directory=src.is_dir())
        return f"linked {dest.name}"
    if src.is_dir():
        shutil.copytree(src, dest)
    else:
        shutil.copy2(src, dest)
    return f"copied {dest.name}"


def link_or_copy_data(src_data: Path, dest_data: Path) -> list[str]:
    """Link (preferred on Kaggle) or copy data artifacts into the repo data/ tree."""
    dest_data.mkdir(parents=True, exist_ok=True)
    actions: list[str] = []

    for name in ("imagery", "prelabels", "labels"):
        src = src_data / name
        dest = dest_data / name
        if not src.exists():
            continue
        action = _link_or_copy_tree(src, dest)
        actions.append(action.replace(dest.name, name) if dest.name != name else action)

    sites_src = src_data / "sites.json"
    sites_dest = dest_data / "sites.json"
    if sites_src.exists() and not sites_dest.exists() and not sites_dest.is_symlink():
        actions.append(_link_or_copy_tree(sites_src, sites_dest))

    return actions


def materialize_from_exported_dataset() -> list[str]:
    """
    If data/datasets/mooring_boats already has images/labels (checked into git),
    expose them as data/imagery and data/labels for train(use_corrected_labels=True).
    """
    actions: list[str] = []
    for split in ("train", "val"):
        img_src = DATASET_DIR / "images" / split
        lbl_src = DATASET_DIR / "labels" / split
        img_dest = DATA_DIR / "imagery" / split
        lbl_dest = DATA_DIR / "labels" / split
        if img_src.is_dir() and _split_png_count(DATASET_DIR / "images", split) > 0:
            if not img_dest.exists() and not img_dest.is_symlink():
                img_dest.parent.mkdir(parents=True, exist_ok=True)
                actions.append(_link_or_copy_tree(img_src, img_dest))
        if lbl_src.is_dir() and _split_txt_count(DATASET_DIR / "labels", split) > 0:
            if not lbl_dest.exists() and not lbl_dest.is_symlink():
                lbl_dest.parent.mkdir(parents=True, exist_ok=True)
                actions.append(_link_or_copy_tree(lbl_src, lbl_dest))
    return actions


def rewrite_dataset_yaml_path() -> str | None:
    """Ensure data.yaml path matches this machine (fixes Windows path committed in git)."""
    yaml_path = DATASET_DIR / "data.yaml"
    if not yaml_path.exists():
        return None
    text = (
        f"path: {DATASET_DIR.resolve().as_posix()}\n"
        "train: images/train\n"
        "val: images/val\n"
        "names:\n"
        "  0: boat\n"
    )
    yaml_path.write_text(text, encoding="utf-8")
    return str(yaml_path)


def _count_report() -> dict[str, Any]:
    return {
        "imagery_train": _split_png_count(DATA_DIR / "imagery", "train"),
        "imagery_val": _split_png_count(DATA_DIR / "imagery", "val"),
        "labels_train": _split_txt_count(DATA_DIR / "labels", "train"),
        "labels_val": _split_txt_count(DATA_DIR / "labels", "val"),
    }


def bootstrap_kaggle(input_data: Path | None = None) -> dict:
    """
    Prepare a Kaggle notebook runtime: secrets, input dataset, cwd.

    Call once after cloning the repo into /kaggle/working.

    Resolves training data in order:
      1. Explicit --input-data / MOORING_INPUT_DATA
      2. Attached Kaggle datasets under /kaggle/input (any slug with data/imagery)
      3. Fallback: data/datasets/mooring_boats checked into the repo
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
        "has_labels": _has_labels(),
        "data_actions": [],
        "input_payload": None,
        "secrets": {},
        "counts": _count_report(),
    }

    if is_kaggle():
        info["secrets"] = load_kaggle_secrets()
        input_root = Path("/kaggle/input")
        info["kaggle_inputs"] = (
            sorted(p.name for p in input_root.iterdir()) if input_root.is_dir() else []
        )

    if not _has_imagery() or not _has_labels():
        payload = discover_kaggle_input_data(input_data)
        if payload is not None:
            info["input_payload"] = str(payload)
            info["data_actions"].extend(link_or_copy_data(payload, DATA_DIR))

    if not _has_imagery() or not _has_labels():
        info["data_actions"].extend(materialize_from_exported_dataset())

    yaml_path = rewrite_dataset_yaml_path()
    if yaml_path:
        info["data_actions"].append(f"rewrote {yaml_path}")

    info["has_imagery"] = _has_imagery()
    info["has_labels"] = _has_labels()
    info["counts"] = _count_report()

    if not info["has_imagery"] or not info["has_labels"]:
        inputs = info.get("kaggle_inputs", [])
        raise FileNotFoundError(
            "Training data not available after bootstrap. Need data/imagery/{train,val} "
            "and data/labels/{train,val}. "
            f"has_imagery={info['has_imagery']} has_labels={info['has_labels']} "
            f"counts={info['counts']} kaggle_inputs={inputs} actions={info['data_actions']}. "
            "Attach the mooring-field-data dataset (Add data) or ensure "
            "data/datasets/mooring_boats is present in the clone."
        )

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
        DATA_DIR / "mooring_fields.db",
        DATA_DIR / "geocode_cache.json",
        DATA_DIR / "prelabels",
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
