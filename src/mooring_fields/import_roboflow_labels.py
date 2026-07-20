"""Import Roboflow YOLOv8-OBB exports into data/labels/{train,val}/."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from mooring_fields.label_utils import sanitize_label_text, validate_label_dir
from mooring_fields.paths import IMAGERY_DIR, LABELS_DIR, PRELABELS_DIR, ROOT

# Roboflow: stem_png.rf.<hash>  or  stem.rf.<hash>
_RF_PNG_SUFFIX = re.compile(r"^(.+)_png\.rf\.[^.]+$", re.IGNORECASE)
_RF_SUFFIX = re.compile(r"^(.+)\.rf\.[^.]+$")


def roboflow_stem_to_original(name: str) -> str:
    """Map a Roboflow label/image filename stem to the original imagery stem."""
    stem = Path(name).stem
    # Path.stem on "foo_png.rf.hash.txt" yields "foo_png.rf.hash"
    m = _RF_PNG_SUFFIX.match(stem)
    if m:
        return m.group(1)
    m = _RF_SUFFIX.match(stem)
    if m:
        return m.group(1)
    return stem


def _resolve_source_split(source_dir: Path, split: str) -> Path | None:
    """Return labels dir for train/val; Roboflow uses valid for val."""
    candidates = [source_dir / split / "labels"]
    if split == "val":
        candidates.insert(0, source_dir / "valid" / "labels")
    for path in candidates:
        if path.is_dir():
            return path
    return None


def _count_boxes(text: str) -> int:
    return sum(1 for line in text.splitlines() if line.strip())


def import_roboflow_obb_export(
    source_dir: Path,
    *,
    labels_dir: Path | None = None,
    imagery_dir: Path | None = None,
    prelabels_dir: Path | None = None,
) -> dict[str, Any]:
    """
    Import a Roboflow YOLOv8-OBB zip layout into data/labels.

    Roboflow labels win for every stem present (including empty files).
    Imagery PNGs without a Roboflow label are backfilled from prelabels when
    available; otherwise an empty label file is written.
    """
    source_dir = Path(source_dir)
    if not source_dir.is_absolute():
        source_dir = (ROOT / source_dir).resolve()
    if not source_dir.is_dir():
        raise FileNotFoundError(f"Roboflow export not found: {source_dir}")

    labels_root = labels_dir or LABELS_DIR
    imagery_root = imagery_dir or IMAGERY_DIR
    prelabels_root = prelabels_dir or PRELABELS_DIR

    report: dict[str, Any] = {
        "source": str(source_dir),
        "labels_dir": str(labels_root),
        "splits": {},
    }

    for split in ("train", "val"):
        dest = labels_root / split
        dest.mkdir(parents=True, exist_ok=True)

        src_labels = _resolve_source_split(source_dir, split)
        imported = 0
        empty_imported = 0
        boxes = 0
        from_roboflow: set[str] = set()

        if src_labels is not None:
            for txt in sorted(src_labels.glob("*.txt")):
                orig = roboflow_stem_to_original(txt.name)
                raw = txt.read_text(encoding="utf-8")
                sanitized = sanitize_label_text(raw)
                (dest / f"{orig}.txt").write_text(sanitized, encoding="utf-8")
                from_roboflow.add(orig)
                imported += 1
                if not sanitized.strip():
                    empty_imported += 1
                else:
                    boxes += _count_boxes(sanitized)

        backfilled = 0
        empty_fallback = 0
        img_dir = imagery_root / split
        pre_dir = prelabels_root / split
        imagery_count = 0

        if img_dir.is_dir():
            for png in sorted(img_dir.glob("*.png")):
                imagery_count += 1
                stem = png.stem
                out = dest / f"{stem}.txt"
                if stem in from_roboflow:
                    continue
                pre = pre_dir / f"{stem}.txt"
                if pre.exists():
                    out.write_text(
                        sanitize_label_text(pre.read_text(encoding="utf-8")),
                        encoding="utf-8",
                    )
                    backfilled += 1
                else:
                    out.write_text("", encoding="utf-8")
                    empty_fallback += 1

        errors = validate_label_dir(dest) if dest.exists() else [f"missing {dest}"]
        label_files = len(list(dest.glob("*.txt"))) if dest.exists() else 0

        report["splits"][split] = {
            "roboflow_imported": imported,
            "roboflow_empty": empty_imported,
            "boxes": boxes,
            "imagery_pngs": imagery_count,
            "label_files": label_files,
            "backfilled_from_prelabels": backfilled,
            "empty_fallback_no_prelabel": empty_fallback,
            "validation_errors": errors[:20],
            "valid": len(errors) == 0,
        }

    all_errors = [
        e
        for s in report["splits"].values()
        for e in s.get("validation_errors", [])
    ]
    report["ok"] = all(s.get("valid") for s in report["splits"].values())
    report["validation_error_count"] = len(all_errors)
    return report
