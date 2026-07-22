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


def import_roboflow_labels_cmd(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Import Roboflow YOLOv8-OBB export into data/labels/{train,val}/"
    )
    parser.add_argument(
        "--source",
        type=Path,
        default=Path("yolov8_new_images"),
        help="Path to Roboflow export root (train/ + valid/ labels)",
    )
    args = parser.parse_args(argv)
    from mooring_fields.import_roboflow_labels import import_roboflow_obb_export

    report = import_roboflow_obb_export(args.source)
    _print(report)
    if not report.get("ok"):
        raise SystemExit(1)


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
    parser.add_argument(
        "--db",
        type=Path,
        default=None,
        help=(
            "SQLite database to save discovered fields into "
            "(default: data/mooring_fields.db, the database the web app reads)"
        ),
    )
    parser.add_argument(
        "--imagery-dir",
        type=Path,
        default=None,
        help=(
            "Persistent directory for scan imagery cache "
            "(default: data/imagery). Re-runs skip already-downloaded tiles."
        ),
    )
    args = parser.parse_args(argv)

    import os
    from dotenv import load_dotenv
    from mooring_fields.cluster_fields import run_on_split
    from mooring_fields.database import save_scan
    from mooring_fields.fetch_imagery import fetch_all as _fetch_all
    from mooring_fields.geocode import Geocoder
    from mooring_fields.kml_export import clusters_to_kml
    from mooring_fields.kml_parser import load_sites_json, parse_kml
    from mooring_fields.paths import DB_PATH, IMAGERY_DIR

    load_dotenv()

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
    # Persistent imagery cache by default so free-tier re-runs are free.
    imagery_base = args.imagery_dir if args.imagery_dir else IMAGERY_DIR
    imagery_base.mkdir(parents=True, exist_ok=True)
    tmp_dir = Path(tempfile.mkdtemp(prefix="mooring_scan_"))
    try:
        # 1. Parse KML to a temp sites.json (does not touch data/sites.json)
        print(f"Parsing KML: {args.kml}")
        parse_result = run_parse_and_split(kml_path=args.kml, output_dir=tmp_dir)
        scan_sites = load_sites_json(path=tmp_dir / "sites.json")
        print(f"  Found {len(scan_sites)} locations")
        print(f"  Planned tiles (up to 5/site): {len(scan_sites) * 5}")
        if args.max_requests:
            print(f"  API cap this run: {args.max_requests}")

        # 2. Fetch imagery into persistent cache (split=scan)
        if not args.skip_fetch:
            print(f"Fetching satellite imagery into {imagery_base / 'scan'} ...")
            fetch_result = _fetch_all(
                input_sites=scan_sites,
                imagery_output_base_dir=imagery_base,
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
            imagery_input_base_dir=imagery_base,
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

        # 6. Persist detections to SQLite (default: the web app's database)
        db_summary = {}
        if clusters:
            db_summary = save_scan(
                clusters,
                source=f"scan:{args.kml.name}",
                weights=str(args.weights) if args.weights else "auto",
                split="scan",
                geocoder=geocoder,
                db_path=args.db if args.db else DB_PATH,
            )
            print(f"  Database saved to: {db_summary.get('db_path')}")

        _print({
            "scanned_locations": len(scan_sites),
            "discovered_clusters": len(clusters),
            "kml_output": str(kml_out) if clusters else None,
            "output_dir": str(args.output_dir),
            "imagery_dir": str(imagery_base),
            "database": db_summary,
            "fetch_summary": fetch_result,
        })

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def query_fields_cmd(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="List detected fields from SQLite")
    parser.add_argument("--db", type=Path, default=None)
    parser.add_argument("--format", choices=["json", "csv"], default="json")
    parser.add_argument("--only-new", action="store_true")
    args = parser.parse_args(argv)
    from mooring_fields.enrichment import query_fields

    result = query_fields(db_path=args.db, fmt=args.format, only_new=args.only_new)
    if args.format == "csv":
        print(result)
    else:
        _print({"fields": result, "count": len(result)})


def estimate_enrichment_cmd(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Estimate Places + Gemini API usage")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--only-new", action="store_true")
    parser.add_argument("--db", type=Path, default=None)
    args = parser.parse_args(argv)
    from mooring_fields.enrichment_config import estimate_enrichment

    _print(
        estimate_enrichment(
            args.limit,
            db_path=args.db,
            only_new=args.only_new,
        )
    )


def enrich_places_cmd(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Enrich fields with Google Places data")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--only-new", action="store_true")
    parser.add_argument("--include-skipped", action="store_true")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--db", type=Path, default=None)
    parser.add_argument("--csv", type=Path, default=None, help="Manual CSV for provider=manual")
    args = parser.parse_args(argv)
    from mooring_fields.enrichment import enrich_places

    _print(
        enrich_places(
            db_path=args.db,
            dry_run=args.dry_run,
            only_new=args.only_new,
            include_skipped=args.include_skipped,
            limit=args.limit,
            csv_path=args.csv,
        )
    )


def enrich_research_cmd(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Research prospects with Gemini")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--only-new", action="store_true")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--db", type=Path, default=None)
    parser.add_argument("--csv", type=Path, default=None)
    args = parser.parse_args(argv)
    from mooring_fields.enrichment import enrich_research

    _print(
        enrich_research(
            db_path=args.db,
            dry_run=args.dry_run,
            only_new=args.only_new,
            limit=args.limit,
            csv_path=args.csv,
        )
    )


def enrich_supply_chain_cmd(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Research upstream suppliers for mooring service companies"
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--only-new", action="store_true", default=True)
    parser.add_argument("--all", action="store_true", help="Re-research even if supply chain exists")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--db", type=Path, default=None)
    args = parser.parse_args(argv)
    from mooring_fields.enrichment import enrich_supply_chain

    _print(
        enrich_supply_chain(
            db_path=args.db,
            dry_run=args.dry_run,
            only_new=not args.all,
            limit=args.limit,
        )
    )


def dedupe_prospects_cmd(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Deduplicate prospect rows")
    parser.add_argument("--db", type=Path, default=None)
    args = parser.parse_args(argv)
    from mooring_fields.enrichment import run_dedupe

    _print(run_dedupe(db_path=args.db))


def export_prospects_cmd(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Export Fields + Prospects Excel/CSV")
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--db", type=Path, default=None)
    parser.add_argument("--min-boat-count", type=int, default=0)
    parser.add_argument("--min-confidence", type=float, default=0.0)
    parser.add_argument("--only-approved", action="store_true")
    args = parser.parse_args(argv)
    from mooring_fields.enrichment_config import load_enrichment_config
    from mooring_fields.export_excel import export_prospects
    from mooring_fields.paths import PROSPECTS_EXPORT

    cfg = load_enrichment_config()
    out = args.output or Path(cfg.get("export_path", str(PROSPECTS_EXPORT)))
    _print(
        export_prospects(
            out,
            db_path=args.db,
            min_boat_count=args.min_boat_count,
            min_confidence=args.min_confidence,
            only_approved=args.only_approved,
        )
    )


def import_prospects_cmd(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Import manual prospect corrections from CSV")
    parser.add_argument("--csv", type=Path, required=True)
    parser.add_argument("--db", type=Path, default=None)
    args = parser.parse_args(argv)
    from mooring_fields.enrichment import import_prospects_csv

    _print(import_prospects_csv(args.csv, db_path=args.db))


def approve_prospect_cmd(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Approve a prospect for export")
    parser.add_argument("--id", type=int, required=True)
    parser.add_argument("--db", type=Path, default=None)
    parser.add_argument("--unapprove", action="store_true")
    args = parser.parse_args(argv)
    from mooring_fields.database import approve_prospect, get_connection, init_db

    conn = get_connection(args.db)
    try:
        init_db(conn)
        approve_prospect(conn, args.id, approved=not args.unapprove)
    finally:
        conn.close()
    _print({"prospect_id": args.id, "approved": not args.unapprove})


def enrich_all_cmd(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run full enrichment pipeline")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--only-new", action="store_true")
    parser.add_argument("--include-skipped", action="store_true")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--db", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--csv", type=Path, default=None)
    args = parser.parse_args(argv)
    from mooring_fields.enrichment import enrich_all

    _print(
        enrich_all(
            db_path=args.db,
            dry_run=args.dry_run,
            only_new=args.only_new,
            include_skipped=args.include_skipped,
            limit=args.limit,
            export_path=args.output,
            csv_path=args.csv,
        )
    )


def diff_scans_cmd(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Compare field counts between two scans")
    parser.add_argument("scan_a", type=int)
    parser.add_argument("scan_b", type=int)
    parser.add_argument("--db", type=Path, default=None)
    args = parser.parse_args(argv)
    from mooring_fields.database import diff_scans, get_connection, init_db

    conn = get_connection(args.db)
    try:
        init_db(conn)
        _print(diff_scans(conn, args.scan_a, args.scan_b))
    finally:
        conn.close()


def delete_scan_cmd(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Delete a detection scan and all linked fields/boats/orphaned prospects"
    )
    parser.add_argument("--scan-id", type=int, required=True)
    parser.add_argument("--db", type=Path, default=None)
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip interactive confirmation",
    )
    args = parser.parse_args(argv)
    from mooring_fields.database import delete_scan, get_connection, init_db, list_scans

    conn = get_connection(args.db)
    try:
        init_db(conn)
        scans = {s["id"]: s for s in list_scans(conn)}
        if args.scan_id not in scans:
            print(f"ERROR: scan_id {args.scan_id} not found", file=sys.stderr)
            sys.exit(1)
        info = scans[args.scan_id]
        print(
            f"Will delete scan {args.scan_id}: source={info.get('source')}, "
            f"weights={info.get('weights')}, fields={info.get('field_count')}"
        )
        if not args.yes:
            reply = input("Type 'yes' to confirm: ").strip().lower()
            if reply != "yes":
                print("Aborted.")
                return
        _print(delete_scan(conn, args.scan_id))
    finally:
        conn.close()


def generate_candidates_cmd(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Generate scan-candidate KML from NOAA Anchorages + OSM marina/mooring "
            "points (ESI MO/M equivalent via REST)."
        )
    )
    parser.add_argument(
        "--state",
        action="append",
        default=[],
        help="US state code to include (repeatable), e.g. --state MA --state RI",
    )
    parser.add_argument(
        "--bbox",
        type=str,
        default=None,
        help="Bounding box west,south,east,north (overrides --state/--region)",
    )
    parser.add_argument(
        "--region",
        type=str,
        default=None,
        help=(
            "Named region bbox (e.g. CapeCod, FL_tampa_sw, FL_keys). "
            "See FL_REGIONS / NAMED_REGIONS in noaa_candidates."
        ),
    )
    parser.add_argument(
        "--types",
        type=str,
        default="MO,M",
        help="Comma-separated ESI-style types: MO (mooring/anchorage), M (marina)",
    )
    parser.add_argument(
        "--dedupe-meters",
        type=float,
        default=150.0,
        help="Spatial dedupe radius in meters (default: 150)",
    )
    parser.add_argument(
        "--max-sites",
        type=int,
        default=None,
        help="Safety cap on candidates after dedupe (recommended ~160 for free-tier)",
    )
    parser.add_argument(
        "--offset",
        type=int,
        default=0,
        help="Skip this many deduped candidates before applying --max-sites (paging)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("candidates.kml"),
        help="Output KML path",
    )
    parser.add_argument(
        "--no-noaa",
        action="store_true",
        help="Skip NOAA Anchorages source",
    )
    parser.add_argument(
        "--no-osm",
        action="store_true",
        help="Skip OpenStreetMap Overpass source",
    )
    args = parser.parse_args(argv)

    from mooring_fields.noaa_candidates import collect_candidates, write_candidates_kml

    bbox = None
    if args.bbox:
        parts = [float(x.strip()) for x in args.bbox.split(",")]
        if len(parts) != 4:
            print("ERROR: --bbox must be west,south,east,north", file=sys.stderr)
            sys.exit(1)
        bbox = (parts[0], parts[1], parts[2], parts[3])
    if not args.state and bbox is None and not args.region:
        print("ERROR: provide --state, --bbox, and/or --region", file=sys.stderr)
        sys.exit(1)

    types = [t.strip() for t in args.types.split(",") if t.strip()]
    result = collect_candidates(
        states=args.state or None,
        bbox=bbox,
        region=args.region,
        types=types,
        dedupe_meters=args.dedupe_meters,
        max_sites=args.max_sites,
        offset=args.offset,
        include_noaa=not args.no_noaa,
        include_osm=not args.no_osm,
    )
    if args.region:
        label = args.region
    elif args.state:
        label = "_".join(args.state)
    else:
        label = "bbox"
    kml_path = write_candidates_kml(
        result["candidates"],
        args.out,
        document_name=f"Candidates {label}",
    )
    summary = {k: v for k, v in result.items() if k != "candidates"}
    summary["kml_output"] = str(kml_path)
    summary["sites_per_run_hint"] = (
        "With max_api_requests_per_run=800 and 5 tiles/site, budget ~160 sites/run."
    )
    _print(summary)


def generate_candidates_batch_cmd(argv: list[str] | None = None) -> None:
    """Write one ≤max-sites KML page per named region (Florida coasts, Cape Cod, …)."""
    parser = argparse.ArgumentParser(
        description=(
            "Generate free-tier-safe candidate KML pages for named coastal regions "
            "(e.g. all FL_REGIONS)."
        )
    )
    parser.add_argument(
        "--regions",
        type=str,
        default="FL_panhandle,FL_big_bend,FL_tampa_sw,FL_keys,FL_se_atlantic,FL_ne_atlantic",
        help="Comma-separated NAMED_REGIONS keys",
    )
    parser.add_argument("--types", type=str, default="MO,M")
    parser.add_argument("--max-sites", type=int, default=160)
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("data"),
        help="Directory for candidates_<region>_pN.kml files",
    )
    parser.add_argument("--no-noaa", action="store_true")
    parser.add_argument("--no-osm", action="store_true")
    args = parser.parse_args(argv)

    from mooring_fields.noaa_candidates import write_region_pages

    regions = [r.strip() for r in args.regions.split(",") if r.strip()]
    types = [t.strip() for t in args.types.split(",") if t.strip()]
    all_pages: list[dict] = []
    for region in regions:
        print(f"Collecting {region}…", flush=True)
        pages = write_region_pages(
            region=region,
            out_dir=args.out_dir,
            types=types,
            max_sites=args.max_sites,
            include_noaa=not args.no_noaa,
            include_osm=not args.no_osm,
        )
        all_pages.extend(pages)
        for p in pages:
            print(
                f"  page {p.get('page')}: sites={p.get('sites')} → {p.get('kml_output')}",
                flush=True,
            )
    _print(
        {
            "regions": regions,
            "max_sites": args.max_sites,
            "pages": all_pages,
            "page_count": len(all_pages),
            "total_sites": sum(int(p.get("sites") or 0) for p in all_pages),
            "next": (
                "For each KML: fetch-scan --max-requests 800 → "
                "package-kaggle-scan → Kaggle GPU notebook → import-scan"
            ),
        }
    )


def package_kaggle_scan_cmd(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Zip cached scan tiles + candidates KML (+ weights) for Kaggle GPU detection"
        )
    )
    parser.add_argument("--kml", type=Path, required=True, help="Candidates KML")
    parser.add_argument(
        "--imagery-dir",
        type=Path,
        default=None,
        help="Imagery root containing scan/ (default: data/imagery)",
    )
    parser.add_argument("--weights", type=Path, default=None)
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("kaggle_scan_payload.zip"),
        help="Output zip path",
    )
    parser.add_argument(
        "--no-weights",
        action="store_true",
        help="Omit model weights from the zip (attach separately on Kaggle)",
    )
    parser.add_argument(
        "--all-cached-tiles",
        action="store_true",
        help="Include every tile in imagery/scan (default: only tiles for this KML)",
    )
    args = parser.parse_args(argv)
    from mooring_fields.kaggle_scan import package_kaggle_scan

    _print(
        package_kaggle_scan(
            kml_path=args.kml,
            imagery_dir=args.imagery_dir,
            weights=args.weights,
            output_zip=args.out,
            include_weights=not args.no_weights,
            only_kml_sites=not args.all_cached_tiles,
        )
    )


def fetch_scan_cmd(argv: list[str] | None = None) -> None:
    """Fetch satellite tiles for a candidates KML into data/imagery/scan (no detection)."""
    parser = argparse.ArgumentParser(
        description=(
            "Download Google Static Maps tiles for a candidates KML into the "
            "persistent scan imagery cache (no YOLO). Use before package-kaggle-scan."
        )
    )
    parser.add_argument("--kml", type=Path, required=True)
    parser.add_argument("--max-requests", type=int, default=None)
    parser.add_argument(
        "--imagery-dir",
        type=Path,
        default=None,
        help="Imagery root (default: data/imagery); tiles go in <root>/scan/",
    )
    args = parser.parse_args(argv)

    import os
    import tempfile
    from dotenv import load_dotenv
    from mooring_fields.fetch_imagery import fetch_all as _fetch_all
    from mooring_fields.kml_parser import load_sites_json
    from mooring_fields.paths import IMAGERY_DIR

    load_dotenv()
    if not args.kml.exists():
        print(f"ERROR: KML not found: {args.kml}", file=sys.stderr)
        sys.exit(1)
    if not os.environ.get("GOOGLE_MAPS_API_KEY", "").strip():
        print("ERROR: GOOGLE_MAPS_API_KEY is not set.", file=sys.stderr)
        sys.exit(1)

    imagery_base = args.imagery_dir if args.imagery_dir else IMAGERY_DIR
    imagery_base.mkdir(parents=True, exist_ok=True)
    tmp_dir = Path(tempfile.mkdtemp(prefix="mooring_fetch_scan_"))
    try:
        print(f"Parsing KML: {args.kml}")
        run_parse_and_split(kml_path=args.kml, output_dir=tmp_dir)
        sites = load_sites_json(path=tmp_dir / "sites.json")
        print(f"  Sites: {len(sites)}  (up to {len(sites) * 5} tiles)")
        result = _fetch_all(
            input_sites=sites,
            imagery_output_base_dir=imagery_base,
            max_requests=args.max_requests,
        )
        _print(
            {
                "sites": len(sites),
                "imagery_dir": str(imagery_base / "scan"),
                "fetch": result,
                "next": (
                    f"python -m mooring_fields.cli package-kaggle-scan "
                    f"--kml {args.kml} --out kaggle_scan_payload.zip"
                ),
            }
        )
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def import_scan_cmd(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Import a scan (fields+boats) from a Kaggle/cloud SQLite DB into the web app DB"
    )
    parser.add_argument("--from-db", type=Path, required=True, help="Source mooring_fields.db")
    parser.add_argument("--db", type=Path, default=None, help="Destination DB (default: data/)")
    parser.add_argument("--scan-id", type=int, default=None, help="Source scan id (default: newest)")
    parser.add_argument(
        "--all",
        action="store_true",
        help="Import every scan in the source DB (use after multi-region Kaggle run)",
    )
    parser.add_argument(
        "--source-label",
        type=str,
        default=None,
        help="Override scans.source label on import",
    )
    args = parser.parse_args(argv)
    from mooring_fields.kaggle_scan import import_scan

    _print(
        import_scan(
            args.from_db,
            dest_db=args.db,
            scan_id=args.scan_id,
            source_label=args.source_label,
            all_scans=args.all,
        )
    )


def main() -> None:
    commands = {
        "parse-kml": parse_kml_cmd,
        "estimate": estimate_cmd,
        "fetch": fetch_imagery_cmd,
        "prelabel": prelabel_cmd,
        "import-roboflow-labels": import_roboflow_labels_cmd,
        "train": train_cmd,
        "evaluate": evaluate_cmd,
        "kaggle-setup": kaggle_setup_cmd,
        "publish-outputs": publish_cmd,
        "scan": scan_cmd,
        "query-fields": query_fields_cmd,
        "estimate-enrichment": estimate_enrichment_cmd,
        "enrich-places": enrich_places_cmd,
        "enrich-research": enrich_research_cmd,
        "enrich-supply-chain": enrich_supply_chain_cmd,
        "dedupe-prospects": dedupe_prospects_cmd,
        "export-prospects": export_prospects_cmd,
        "import-prospects": import_prospects_cmd,
        "approve-prospect": approve_prospect_cmd,
        "enrich-all": enrich_all_cmd,
        "diff-scans": diff_scans_cmd,
        "delete-scan": delete_scan_cmd,
        "generate-candidates": generate_candidates_cmd,
        "generate-candidates-batch": generate_candidates_batch_cmd,
        "fetch-scan": fetch_scan_cmd,
        "package-kaggle-scan": package_kaggle_scan_cmd,
        "import-scan": import_scan_cmd,
    }
    if len(sys.argv) < 2 or sys.argv[1] not in commands:
        print("Usage: python -m mooring_fields.cli <command>")
        print("Commands:", ", ".join(commands))
        sys.exit(1)
    cmd = sys.argv[1]
    commands[cmd](sys.argv[2:])


if __name__ == "__main__":
    main()
