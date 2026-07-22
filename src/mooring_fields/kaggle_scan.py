"""Package cached scan tiles for Kaggle GPU detection and import results.

Local machine (no GPU) is slow for YOLO on hundreds of tiles. Workflow:

1. Locally: generate-candidates → scan fetch (or reuse data/imagery/scan cache)
2. Locally: package-kaggle-scan → upload zip as a Kaggle Dataset
3. Kaggle T4: notebooks/kaggle_scan.ipynb runs detection with --skip-fetch
4. Locally: import-scan merges the downloaded cloud DB into data/mooring_fields.db
5. Locally: enrich-all --only-new (Places + Groq)

The detection step is the only part that needs a GPU.
"""

from __future__ import annotations

import json
import shutil
import zipfile
from pathlib import Path
from typing import Any

from mooring_fields.database import (
    get_boats,
    get_connection,
    init_db,
    insert_boats,
    insert_field,
    insert_scan,
    list_fields,
    list_scans,
)
from mooring_fields.paths import DATA_DIR, DB_PATH, IMAGERY_DIR, ROOT, RUNS_DIR


def _posix(path: Path) -> str:
    return path.as_posix()


def package_kaggle_scan(
    *,
    kml_path: Path,
    imagery_dir: Path | None = None,
    weights: Path | None = None,
    output_zip: Path | None = None,
    include_weights: bool = True,
    only_kml_sites: bool = True,
) -> dict[str, Any]:
    """Build a zip for Kaggle: candidates KML + cached scan imagery (+ optional weights).

    Zip layout (forward slashes for Kaggle):
      candidates.kml
      imagery/scan/*.png + *.json
      weights/best.pt   (optional)
      manifest.json

    When *only_kml_sites* is True (default), only tiles whose metadata ``site_id``
    matches a placemark in the KML are included — so a Cape Cod package does not
    drag in a prior Massachusetts statewide cache.
    """
    from mooring_fields.kml_parser import parse_kml

    kml_path = Path(kml_path)
    if not kml_path.is_file():
        raise FileNotFoundError(f"KML not found: {kml_path}")

    imagery_root = Path(imagery_dir) if imagery_dir else IMAGERY_DIR
    scan_dir = imagery_root / "scan"
    if not scan_dir.is_dir():
        raise FileNotFoundError(
            f"No scan imagery cache at {scan_dir}. "
            "Fetch tiles first (scan or fetch-scan), then package."
        )

    site_ids: set[str] | None = None
    if only_kml_sites:
        site_ids = {s.id for s in parse_kml(kml_path)}
        if not site_ids:
            raise ValueError(f"No placemarks with ids found in {kml_path}")

    pngs: list[Path] = []
    for png in sorted(scan_dir.glob("*.png")):
        if site_ids is None:
            pngs.append(png)
            continue
        meta_path = png.with_suffix(".json")
        if not meta_path.is_file():
            continue
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if meta.get("site_id") in site_ids:
            pngs.append(png)

    if not pngs:
        raise FileNotFoundError(
            f"No PNG tiles in {scan_dir} matching KML site ids. "
            "Fetch imagery for this KML before packaging."
        )

    weights_path = Path(weights) if weights else (RUNS_DIR / "mooring_boats" / "weights" / "best.pt")
    if include_weights and not weights_path.is_file():
        raise FileNotFoundError(
            f"Weights not found: {weights_path}. Pass --weights or train first."
        )

    out = Path(output_zip) if output_zip else (ROOT / "kaggle_scan_payload.zip")
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        out.unlink()

    json_count = 0
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        zf.write(kml_path, arcname="candidates.kml")
        for png in pngs:
            zf.write(png, arcname=f"imagery/scan/{png.name}")
            meta = png.with_suffix(".json")
            if meta.is_file():
                zf.write(meta, arcname=f"imagery/scan/{meta.name}")
                json_count += 1
        if include_weights:
            zf.write(weights_path, arcname="weights/best.pt")
        manifest = {
            "kml": kml_path.name,
            "png_count": len(pngs),
            "json_count": json_count,
            "site_ids": sorted(site_ids) if site_ids is not None else None,
            "only_kml_sites": only_kml_sites,
            "weights_included": include_weights,
            "weights_source": str(weights_path) if include_weights else None,
            "imagery_dir": str(scan_dir),
        }
        zf.writestr("manifest.json", json.dumps(manifest, indent=2))

    return {
        "zip": str(out.resolve()),
        "bytes": out.stat().st_size,
        "png_count": len(pngs),
        "json_count": json_count,
        "sites_matched": len(site_ids) if site_ids is not None else None,
        "weights_included": include_weights,
        "hint": (
            "1) git push so Kaggle can clone this repo. "
            "2) Upload this zip as a Kaggle Dataset (e.g. mooring-scan-capecod). "
            "3) Run notebooks/kaggle_scan.ipynb with GPU T4 + that dataset attached."
        ),
    }


def import_scan(
    source_db: Path,
    *,
    dest_db: Path | None = None,
    scan_id: int | None = None,
    source_label: str | None = None,
    all_scans: bool = False,
) -> dict[str, Any]:
    """Copy one scan (or all scans) from a cloud/source DB into the web app DB.

    Does not copy prospects/enrichment — run enrich-all --only-new after import.
    """
    source_db = Path(source_db)
    dest = Path(dest_db) if dest_db else DB_PATH
    if not source_db.is_file():
        raise FileNotFoundError(f"Source DB not found: {source_db}")

    if all_scans and scan_id is not None:
        raise ValueError("Pass either scan_id or all_scans=True, not both")

    src = get_connection(source_db)
    dst = get_connection(dest)
    try:
        init_db(src)
        init_db(dst)
        scans = list_scans(src)
        if not scans:
            raise ValueError(f"No scans in {source_db}")

        if all_scans:
            # list_scans is newest-first; import oldest→newest for stable ids
            to_import = list(reversed(scans))
        elif scan_id is None:
            to_import = [scans[0]]
        else:
            chosen = next((s for s in scans if int(s["id"]) == int(scan_id)), None)
            if chosen is None:
                raise ValueError(f"scan_id {scan_id} not in {source_db}")
            to_import = [chosen]

        imported: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        for chosen in to_import:
            sid = int(chosen["id"])
            new_source = source_label or f"import:{chosen.get('source') or sid}"
            fingerprint = f"imported from {source_db.name} scan_id={sid}"
            existing = dst.execute(
                "SELECT id FROM scans WHERE notes = ? LIMIT 1",
                (fingerprint,),
            ).fetchone()
            if existing is not None:
                skipped.append(
                    {
                        "source_scan_id": sid,
                        "dest_scan_id": int(existing[0]),
                        "skipped": True,
                        "reason": "already_imported",
                        "source_label": new_source,
                    }
                )
                continue

            new_scan_id = insert_scan(
                dst,
                source=new_source,
                weights=chosen.get("weights"),
                split=chosen.get("split") or "scan",
                notes=fingerprint,
            )

            fields = list_fields(src, scan_id=sid)
            boats_saved = 0
            for row in fields:
                field_id = insert_field(
                    dst,
                    scan_id=new_scan_id,
                    latitude=float(row["latitude"]),
                    longitude=float(row["longitude"]),
                    boat_count=int(row["boat_count"] or 0),
                    mean_confidence=float(row["mean_confidence"] or 0.0),
                    location_name=row["location_name"],
                    country=row["country"],
                )
                dst.execute(
                    "UPDATE fields SET enrichment_status = ? WHERE id = ?",
                    ("pending", field_id),
                )
                old_field_id = int(row["id"])
                boat_rows = get_boats(src, field_id=old_field_id, limit=100000)

                class _B:
                    __slots__ = ("lat", "lon", "confidence", "image_stem")

                    def __init__(self, r: dict[str, Any]):
                        self.lat = float(r["latitude"])
                        self.lon = float(r["longitude"])
                        self.confidence = float(r.get("confidence") or 0.0)
                        self.image_stem = r.get("image_stem") or ""

                insert_boats(dst, new_scan_id, field_id, [_B(b) for b in boat_rows])
                boats_saved += len(boat_rows)

            imported.append(
                {
                    "source_scan_id": sid,
                    "dest_scan_id": new_scan_id,
                    "fields_imported": len(fields),
                    "boats_imported": boats_saved,
                    "source_label": new_source,
                }
            )
        dst.commit()

        return {
            "source_db": str(source_db),
            "dest_db": str(dest),
            "scans_imported": len(imported),
            "scans_skipped": len(skipped),
            "imports": imported,
            "skipped": skipped,
            "next": "python -m mooring_fields.cli enrich-all --only-new  # optional",
        }
    finally:
        src.close()
        dst.close()


def materialize_kaggle_scan_input(payload_dir: Path, work_dir: Path | None = None) -> dict[str, Any]:
    """On Kaggle: copy/link a mounted scan payload into a writable work layout.

    Expects payload_dir to contain candidates.kml and imagery/scan/ (and optional weights/).
    """
    payload_dir = Path(payload_dir)
    work = Path(work_dir) if work_dir else Path("/kaggle/working/scan_run")
    work.mkdir(parents=True, exist_ok=True)

    kml_src = payload_dir / "candidates.kml"
    if not kml_src.is_file():
        # tolerate nested data/ layout
        matches = list(payload_dir.rglob("candidates.kml"))
        if not matches:
            raise FileNotFoundError(f"candidates.kml not found under {payload_dir}")
        kml_src = matches[0]
        payload_dir = kml_src.parent

    kml_dst = work / "candidates.kml"
    shutil.copy2(kml_src, kml_dst)

    img_src = payload_dir / "imagery"
    img_dst = work / "imagery"
    if img_dst.exists():
        shutil.rmtree(img_dst)
    if not (img_src / "scan").is_dir():
        raise FileNotFoundError(f"imagery/scan not found under {payload_dir}")
    shutil.copytree(img_src, img_dst)

    weights_src = payload_dir / "weights" / "best.pt"
    weights_dst = work / "weights" / "best.pt"
    if weights_src.is_file():
        weights_dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(weights_src, weights_dst)

    png_count = len(list((img_dst / "scan").glob("*.png")))
    return {
        "work_dir": str(work),
        "kml": str(kml_dst),
        "imagery_dir": str(img_dst),
        "weights": str(weights_dst) if weights_dst.is_file() else None,
        "png_count": png_count,
        "db_out": str(work / "mooring_fields.db"),
    }
