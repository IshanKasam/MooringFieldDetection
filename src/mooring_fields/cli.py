"""Command-line entry points for the mooring field pipeline."""

from __future__ import annotations

import argparse
import json
import shutil
import tempfile
from pathlib import Path
import sys

from mooring_fields.evaluate import evaluate_val
from mooring_fields.fetch_imagery import estimate_fetch, fetch_all
from mooring_fields.prelabel_boats import prelabel_all
from mooring_fields.runtime import bootstrap_kaggle, publish_outputs
from mooring_fields.split_sites import run_parse_and_split
from mooring_fields.train_boats import train


def _print(data: dict) -> None:
    print(json.dumps(data, indent=2))


def parse_kml_cmd(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Parse KML and create train/val split")
    parser.add_argument("--kml", type=Path, default=None)
    args = parser.parse_args(argv)
    _print(run_parse_and_split(args.kml))


def estimate_cmd(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Estimate Maps Static API usage before fetch")
    parser.add_argument("--split", choices=["train", "val"], default=None)
    args = parser.parse_args(argv)
    _print(estimate_fetch(split=args.split))


def fetch_imagery_cmd(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Fetch satellite tiles from Maps Static API")
    parser.add_argument("--split", choices=["train", "val"], default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--max-requests",
        type=int,
        default=None,
        help="Override max API calls this run (default from config/imagery.yaml)",
    )
    args = parser.parse_args(argv)
    _print(
        fetch_all(
            split=args.split,
            dry_run=args.dry_run,
            max_requests=args.max_requests,
        )
    )


def prelabel_cmd(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Pre-label boats with YOLO-OBB")
    parser.parse_args(argv)
    _print(prelabel_all())


def train_cmd(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Fine-tune YOLO-OBB boat detector")
    parser.add_argument("--corrected-labels", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--publish", action="store_true", help="Copy outputs to Kaggle working dir")
    args = parser.parse_args(argv)
    report = train(use_corrected_labels=args.corrected_labels, resume=args.resume)
    if args.publish:
        report["published"] = publish_outputs()
    _print(report)


def evaluate_cmd(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Evaluate mooring field Hit@R on val sites")
    parser.add_argument("--weights", type=Path, default=None)
    parser.add_argument("--publish", action="store_true", help="Copy outputs to Kaggle working dir")
    args = parser.parse_args(argv)
    report = evaluate_val(weights=args.weights)
    if args.publish:
        report["published"] = publish_outputs()
    _print(report)


def kaggle_setup_cmd(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Bootstrap Kaggle runtime (GPU, secrets, input dataset)"
    )
    parser.add_argument(
        "--input-data",
        type=Path,
        default=None,
        help="Kaggle input dataset root (contains data/ or imagery/)",
    )
    args = parser.parse_args(argv)
    _print(bootstrap_kaggle(input_data=args.input_data))


def publish_cmd(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Copy artifacts to Kaggle working output")
    parser.add_argument("--dest", type=Path, default=None)
    args = parser.parse_args(argv)
    _print(publish_outputs(dest=args.dest))


def scan_cmd(argv: list[str] | None = None) -> None:
    """Scan new KML locations for mooring fields without touching training data."""
    parser = argparse.ArgumentParser(
        description=(
            "Detect mooring fields in a new KML of candidate locations using a "
            "trained model. Does NOT overwrite data/sites.json or config/split.yaml."
        )
    )
    parser.add_argument("--kml", type=Path, required=True, help="KML file with candidate locations")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("./scan_results"),
        help="Directory to save discovered_fields.kml (default: ./scan_results)",
    )
    parser.add_argument(
        "--weights",
        type=Path,
        default=None,
        help="Path to trained model weights (default: auto-detect best.pt)",
    )
    parser.add_argument(
        "--max-requests",
        type=int,
        default=None,
        help="Max Google Maps API calls for fetching scan imagery",
    )
    parser.add_argument(
        "--skip-fetch",
        action="store_true",
        help="Skip fetching imagery (use if tiles already downloaded into output-dir)",
    )
    args = parser.parse_args(argv)

    import os
    from mooring_fields.cluster_fields import run_on_split
    from mooring_fields.database import save_scan
    from mooring_fields.fetch_imagery import fetch_all as _fetch_all
    from mooring_fields.geocode import Geocoder
    from mooring_fields.kml_export import clusters_to_kml
    from mooring_fields.kml_parser import load_sites_json, parse_kml

    if not args.kml.exists():
        print(f"ERROR: KML file not found: {args.kml}", file=sys.stderr)
        sys.exit(1)

    api_key = os.environ.get("GOOGLE_MAPS_API_KEY", "").strip()
    if not api_key and not args.skip_fetch:
        print(
            "ERROR: GOOGLE_MAPS_API_KEY environment variable is not set. "
            "Set it before running scan (or use --skip-fetch if imagery already exists).",
            file=sys.stderr,
        )
        sys.exit(1)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    tmp_dir = Path(tempfile.mkdtemp(prefix="mooring_scan_"))
    try:
        # 1. Parse KML to a temp sites.json (does not touch data/sites.json)
        print(f"Parsing KML: {args.kml}")
        parse_result = run_parse_and_split(kml_path=args.kml, output_dir=tmp_dir)
        scan_sites = load_sites_json(path=tmp_dir / "sites.json")
        print(f"  Found {len(scan_sites)} locations")

        # 2. Fetch imagery for scan sites into a temp imagery dir
        tmp_imagery = tmp_dir / "imagery"
        if not args.skip_fetch:
            print("Fetching satellite imagery for scan locations...")
            fetch_result = _fetch_all(
                input_sites=scan_sites,
                imagery_output_base_dir=tmp_imagery,
                max_requests=args.max_requests,
            )
            print(f"  Downloaded: {fetch_result['downloaded']}, cached: {fetch_result['skipped_cached']}")
        else:
            fetch_result = {}
            print("--skip-fetch: skipping imagery download")

        # 3. Run detection and clustering
        print("Running mooring field detection...")
        clusters = run_on_split(
            split="scan",
            weights=args.weights,
            input_sites=scan_sites,
            imagery_input_base_dir=tmp_imagery,
        )
        print(f"  Detected {len(clusters)} qualifying mooring fields")

        # 4. Reverse-geocode location names
        geocoder = Geocoder(cache_path=args.output_dir / "geocode_cache.json")
        names = {id(c): geocoder(c.lat, c.lon).get("location_name") for c in clusters}

        # 5. Export to KML in the output dir
        kml_out = args.output_dir / "discovered_fields.kml"
        if clusters:
            clusters_to_kml(
                clusters,
                kml_out,
                document_name=f"Mooring scan: {args.kml.name}",
                names=names,
            )
            print(f"  KML saved to: {kml_out}")
        else:
            print("  No mooring fields detected — KML not written.")

        # 6. Persist detections to a SQLite database in the output dir
        db_summary = {}
        if clusters:
            db_summary = save_scan(
                clusters,
                source=f"scan:{args.kml.name}",
                weights=str(args.weights) if args.weights else "auto",
                split="scan",
                geocoder=geocoder,
                db_path=args.output_dir / "mooring_fields.db",
            )
            print(f"  Database saved to: {db_summary.get('db_path')}")

        _print({
            "scanned_locations": len(scan_sites),
            "discovered_clusters": len(clusters),
            "kml_output": str(kml_out) if clusters else None,
            "output_dir": str(args.output_dir),
            "database": db_summary,
            "fetch_summary": fetch_result,
        })

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def main() -> None:
    commands = {
        "parse-kml": parse_kml_cmd,
        "estimate": estimate_cmd,
        "fetch": fetch_imagery_cmd,
        "prelabel": prelabel_cmd,
        "train": train_cmd,
        "evaluate": evaluate_cmd,
        "kaggle-setup": kaggle_setup_cmd,
        "publish-outputs": publish_cmd,
        "scan": scan_cmd,
    }
    if len(sys.argv) < 2 or sys.argv[1] not in commands:
        print("Usage: python -m mooring_fields.cli <command>")
        print("Commands:", ", ".join(commands))
        sys.exit(1)
    cmd = sys.argv[1]
    commands[cmd](sys.argv[2:])


if __name__ == "__main__":
    main()
