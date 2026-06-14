"""Geographic train/validation split for mooring field sites."""

from __future__ import annotations

import json
from pathlib import Path

import yaml
from sklearn.cluster import KMeans

from mooring_fields.kml_parser import Site, load_sites_json, parse_kml, write_sites_json
from mooring_fields.paths import CONFIG_DIR, SITES_JSON


def geographic_split(
    sites: list[Site],
    train_ratio: float = 0.8,
    random_seed: int = 42,
    n_clusters: int | None = None,
) -> tuple[list[str], list[str]]:
    """
    Split sites by geographic clusters so adjacent mooring fields
  don't all land in the same split.
    """
    if not sites:
        return [], []

    n_clusters = n_clusters or min(max(5, int(len(sites) ** 0.5)), len(sites))
    coords = [[s.latitude, s.longitude] for s in sites]
    labels = KMeans(n_clusters=n_clusters, random_state=random_seed, n_init=10).fit_predict(coords)

    train_ids: list[str] = []
    val_ids: list[str] = []

    for cluster_id in range(n_clusters):
        cluster_sites = [s for s, lbl in zip(sites, labels) if lbl == cluster_id]
        cluster_sites.sort(key=lambda s: s.id)
        n_val = max(1, round(len(cluster_sites) * (1 - train_ratio)))
        if len(cluster_sites) <= 2:
            n_val = 1
        val_ids.extend(s.id for s in cluster_sites[:n_val])
        train_ids.extend(s.id for s in cluster_sites[n_val:])

    return train_ids, val_ids


def update_split_config(train_ids: list[str], val_ids: list[str], config_path: Path | None = None) -> Path:
    path = config_path or CONFIG_DIR / "split.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["train_ids"] = train_ids
    data["val_ids"] = val_ids
    path.write_text(yaml.dump(data, default_flow_style=False, sort_keys=False), encoding="utf-8")
    return path


def run_parse_and_split(kml_path: Path | None = None, output_dir: Path | None = None) -> dict:
    """Parse a KML and write sites.json + update split config.

    If *output_dir* is given the results are written there instead of the
    default ``data/`` / ``config/`` locations, so the main training data is
    never overwritten (useful for the scan workflow).
    """
    sites = parse_kml(kml_path)

    sites_out = (output_dir / "sites.json") if output_dir else None
    write_sites_json(sites, sites_out)

    if output_dir is None:
        config_path = CONFIG_DIR / "split.yaml"
        cfg = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        train_ids, val_ids = geographic_split(
            sites,
            train_ratio=cfg.get("train_ratio", 0.8),
            random_seed=cfg.get("random_seed", 42),
        )
        update_split_config(train_ids, val_ids)
        return {
            "sites_count": len(sites),
            "train_count": len(train_ids),
            "val_count": len(val_ids),
            "sites_json": str(SITES_JSON),
        }

    return {
        "sites_count": len(sites),
        "sites_json": str(output_dir / "sites.json"),
    }


def sites_for_split(sites: list[Site], split: str) -> list[Site]:
    cfg = yaml.safe_load((CONFIG_DIR / "split.yaml").read_text(encoding="utf-8"))
    ids = set(cfg["train_ids"] if split == "train" else cfg["val_ids"])
    return [s for s in sites if s.id in ids]
