"""Detect mooring fields as dense clusters of boat detections."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import yaml
from sklearn.cluster import DBSCAN
from ultralytics import YOLO

from mooring_fields.geo_utils import haversine_m
from mooring_fields.paths import CONFIG_DIR, IMAGERY_DIR, RUNS_DIR
from mooring_fields.runtime import inference_kwargs, load_training_config


@dataclass
class BoatDetection:
    lat: float
    lon: float
    confidence: float
    image_stem: str


@dataclass
class MooringFieldCluster:
    lat: float
    lon: float
    boat_count: int
    mean_confidence: float
    boat_ids: list[int]


def load_cluster_config() -> dict:
    return yaml.safe_load((CONFIG_DIR / "cluster.yaml").read_text(encoding="utf-8"))


def resolve_model(weights: Path | None = None) -> YOLO:
    if weights and weights.exists():
        return YOLO(str(weights))
    best = RUNS_DIR / "mooring_boats" / "weights" / "best.pt"
    if best.exists():
        return YOLO(str(best))
    print("WARNING: no trained best.pt found, using pretrained model fallback.")
    return YOLO(load_training_config()["model"])


def obb_center_to_latlon(cx: float, cy: float, meta: dict) -> tuple[float, float]:
    """Map normalized image coordinates to lat/lon using tile metadata bounds."""
    b = meta["bounds"]
    lon = b["west"] + cx * (b["east"] - b["west"])
    lat = b["north"] - cy * (b["north"] - b["south"])
    return lat, lon


def obb_centroid_latlon(result_obb, index: int, meta: dict) -> tuple[float, float]:
    """Centroid of normalized OBB corners mapped to geographic coordinates."""
    corners = result_obb.xyxyxyxyn.cpu().numpy()[index]
    cx = float(corners[:, 0].mean())
    cy = float(corners[:, 1].mean())
    return obb_center_to_latlon(cx, cy, meta)


def detect_boats_in_tile(
    model: YOLO,
    image_path: Path,
    meta_path: Path,
    conf: float,
) -> list[BoatDetection]:
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    results = model.predict(str(image_path), conf=conf, **inference_kwargs())
    boats: list[BoatDetection] = []

    for result in results:
        if result.obb is None:
            continue
        confs = result.obb.conf.cpu().numpy()
        for i in range(len(result.obb)):
            lat, lon = obb_centroid_latlon(result.obb, i, meta)
            boats.append(
                BoatDetection(
                    lat=lat,
                    lon=lon,
                    confidence=float(confs[i]),
                    image_stem=image_path.stem,
                )
            )
    return boats


def dedupe_boats(boats: list[BoatDetection], min_dist_m: float) -> list[BoatDetection]:
    """Remove duplicate detections from overlapping tiles; keep highest confidence."""
    kept: list[BoatDetection] = []
    for boat in sorted(boats, key=lambda b: -b.confidence):
        if all(haversine_m(boat.lat, boat.lon, k.lat, k.lon) > min_dist_m for k in kept):
            kept.append(boat)
    return kept


def cluster_boats(
    boats: list[BoatDetection],
    eps_m: float,
    min_samples: int,
) -> list[MooringFieldCluster]:
    if len(boats) < min_samples:
        return []

    coords = np.array([[b.lat, b.lon] for b in boats])
    mean_lat = float(coords[:, 0].mean())
    x = np.radians(coords[:, 1]) * np.cos(np.radians(mean_lat)) * 6_378_137
    y = np.radians(coords[:, 0]) * 6_378_137
    xy = np.column_stack([x, y])

    labels = DBSCAN(eps=eps_m, min_samples=min_samples).fit_predict(xy)
    clusters: list[MooringFieldCluster] = []

    for label in set(labels):
        if label < 0:
            continue
        mask = labels == label
        cluster_boats_list = [b for b, m in zip(boats, mask) if m]
        lats = [b.lat for b in cluster_boats_list]
        lons = [b.lon for b in cluster_boats_list]
        clusters.append(
            MooringFieldCluster(
                lat=float(np.mean(lats)),
                lon=float(np.mean(lons)),
                boat_count=len(cluster_boats_list),
                mean_confidence=float(np.mean([b.confidence for b in cluster_boats_list])),
                boat_ids=[],
            )
        )
    return clusters


def is_qualifying_field(cluster: MooringFieldCluster, min_boats: int) -> bool:
    return cluster.boat_count >= min_boats


def iter_tiles_for_clustering(split: str, cfg: dict, imagery_input_base_dir: Path | None = None) -> list[Path]:
    """Select imagery tiles for clustering (center-only by default to avoid duplicates)."""
    img_dir = (imagery_input_base_dir or IMAGERY_DIR) / split
    direction = cfg.get("eval_tile_direction", "center")
    if direction == "all":
        return sorted(img_dir.glob("*.png"))
    suffix = f"_{direction}_"
    return sorted(p for p in img_dir.glob("*.png") if suffix in p.stem)


def clusters_from_boats(boats: list[BoatDetection], cfg: dict) -> list[MooringFieldCluster]:
    boats = dedupe_boats(boats, cfg.get("dedupe_radius_meters", 25))
    clusters = cluster_boats(boats, cfg["eps_meters"], cfg["min_samples"])
    min_boats = cfg["min_boats"]
    return [c for c in clusters if is_qualifying_field(c, min_boats)]


def run_for_site(
    site_id: str,
    split: str = "val",
    weights: Path | None = None,
    imagery_input_base_dir: Path | None = None,
) -> list[MooringFieldCluster]:
    """Detect and cluster boats in the center tile for one mooring field site."""
    cfg = load_cluster_config()
    model = resolve_model(weights)
    img_dir = (imagery_input_base_dir or IMAGERY_DIR) / split
    if not img_dir.exists():
        return []

    direction = cfg.get("eval_tile_direction", "center")
    for png in sorted(img_dir.glob("*.png")):
        if f"_{direction}_" not in png.stem:
            continue
        meta_path = img_dir / f"{png.stem}.json"
        if not meta_path.exists():
            continue
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if meta.get("site_id") != site_id:
            continue
        boats = detect_boats_in_tile(model, png, meta_path, cfg["confidence_threshold"])
        return clusters_from_boats(boats, cfg)
    return []


def _dedupe_clusters(
    clusters: list[MooringFieldCluster],
    eps_m: float,
) -> list[MooringFieldCluster]:
    unique: list[MooringFieldCluster] = []
    for cluster in clusters:
        if all(
            haversine_m(cluster.lat, cluster.lon, u.lat, u.lon) > eps_m for u in unique
        ):
            unique.append(cluster)
    return unique


def run_on_split(
    split: str = "val",
    weights: Path | None = None,
    per_site: bool = False,
    input_sites: list | None = None,
    imagery_input_base_dir: Path | None = None,
) -> "list[MooringFieldCluster] | tuple[list[MooringFieldCluster], dict[str, list[MooringFieldCluster]]]":
    """All qualifying clusters across a split (per-site, deduplicated globally).

    *input_sites* overrides loading from sidecar JSON (used by scan workflow).
    *imagery_input_base_dir* overrides IMAGERY_DIR (used by scan workflow).
    """
    cfg = load_cluster_config()
    img_dir = (imagery_input_base_dir or IMAGERY_DIR) / split
    if not img_dir.exists():
        return ([], {}) if per_site else []

    site_ids: set[str] = set()
    for meta_path in img_dir.glob("*.json"):
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        site_id = meta.get("site_id")
        if site_id and meta.get("direction") == cfg.get("eval_tile_direction", "center"):
            if input_sites is None or any(s.id == site_id for s in input_sites):
                site_ids.add(site_id)

    by_site: dict[str, list[MooringFieldCluster]] = {}
    all_clusters: list[MooringFieldCluster] = []
    for site_id in sorted(site_ids):
        site_clusters = run_for_site(site_id, split, weights, imagery_input_base_dir)
        by_site[site_id] = site_clusters
        all_clusters.extend(site_clusters)

    unique = _dedupe_clusters(all_clusters, cfg["eps_meters"])
    if per_site:
        return unique, by_site
    return unique
