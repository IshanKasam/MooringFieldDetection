"""Evaluate mooring field detection against held-out KML validation sites."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import yaml

from mooring_fields.cluster_fields import MooringFieldCluster, run_on_split
from mooring_fields.geo_utils import haversine_m
from mooring_fields.kml_export import clusters_to_kml
from mooring_fields.kml_parser import Site, load_sites_json
from mooring_fields.paths import CONFIG_DIR, DATA_DIR
from mooring_fields.split_sites import sites_for_split

RESULTS_JSON = DATA_DIR / "evaluation_results.json"
RESULTS_KML = DATA_DIR / "evaluation_clusters.kml"


def load_cluster_config() -> dict:
    return yaml.safe_load((CONFIG_DIR / "cluster.yaml").read_text(encoding="utf-8"))


def hit_at_radius(
    site: Site,
    clusters: list[MooringFieldCluster],
    radius_m: float,
    min_boats: int,
) -> bool:
    for cluster in clusters:
        if cluster.boat_count < min_boats:
            continue
        dist = haversine_m(site.latitude, site.longitude, cluster.lat, cluster.lon)
        if dist <= radius_m:
            return True
    return False


def evaluate_val(weights: Path | None = None, export_kml: bool = True) -> dict:
    cfg = load_cluster_config()
    sites = sites_for_split(load_sites_json(), "val")
    all_clusters, clusters_by_site = run_on_split("val", weights=weights, per_site=True)

    radius = cfg["hit_radius_meters"]
    min_boats = cfg["min_boats"]

    hits = 0
    per_site: list[dict] = []
    for site in sites:
        site_clusters = clusters_by_site.get(site.id, [])
        hit = hit_at_radius(site, site_clusters, radius, min_boats)
        hits += int(hit)
        nearest = None
        for c in site_clusters:
            d = haversine_m(site.latitude, site.longitude, c.lat, c.lon)
            if nearest is None or d < nearest["distance_m"]:
                nearest = {
                    "distance_m": d,
                    "boat_count": c.boat_count,
                    "cluster_lat": c.lat,
                    "cluster_lon": c.lon,
                }
        per_site.append(
            {
                "site_id": site.id,
                "site_name": site.name,
                "hit": hit,
                "site_clusters": len(site_clusters),
                "nearest_cluster": nearest,
            }
        )

    n = len(sites) or 1
    report = {
        "val_sites": len(sites),
        "qualifying_clusters": len(all_clusters),
        "hits": hits,
        f"hit_at_{int(radius)}m": hits / n,
        "hit_rate_pct": round(100 * hits / n, 1),
        "eval_tile_direction": cfg.get("eval_tile_direction", "center"),
        "dedupe_radius_meters": cfg.get("dedupe_radius_meters", 25),
        "per_site": per_site,
        "clusters": [asdict(c) for c in all_clusters],
    }

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    RESULTS_JSON.write_text(json.dumps(report, indent=2), encoding="utf-8")
    if export_kml and all_clusters:
        clusters_to_kml(all_clusters, RESULTS_KML, document_name="Validation mooring fields")
        report["kml_output"] = str(RESULTS_KML)
    elif RESULTS_KML.exists():
        RESULTS_KML.unlink()
        report["kml_note"] = "No clusters found; stale KML removed."
    report["json_output"] = str(RESULTS_JSON)
    return report
