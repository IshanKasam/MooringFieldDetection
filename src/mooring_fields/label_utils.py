"""YOLO-OBB label read/write helpers (Ultralytics polygon format)."""

from __future__ import annotations

from pathlib import Path

# Ultralytics OBB: class + 8 normalized corner coords (x1 y1 x2 y2 x3 y3 x4 y4)
OBB_COLUMNS = 9


def write_obb_labels(result, label_path: Path, class_id: int = 0) -> int:
    """Write normalized xyxyxyxy OBB labels compatible with Ultralytics training."""
    lines: list[str] = []
    if result.obb is not None:
        corners = result.obb.xyxyxyxyn.cpu().numpy()
        for i in range(len(corners)):
            flat = corners[i].reshape(-1)
            clipped = [max(0.0, min(1.0, float(v))) for v in flat]
            parts = " ".join(f"{v:.6f}" for v in clipped)
            lines.append(f"{class_id} {parts}")
    label_path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    return len(lines)


def sanitize_obb_line(line: str) -> str:
    """Clip normalized OBB corners to [0, 1] for Ultralytics training."""
    parts = line.split()
    if len(parts) != OBB_COLUMNS:
        return line
    coords = [max(0.0, min(1.0, float(x))) for x in parts[1:]]
    return f"{parts[0]} " + " ".join(f"{c:.6f}" for c in coords)


def sanitize_label_text(text: str) -> str:
    stripped = text.strip()
    if not stripped:
        return ""
    lines = [sanitize_obb_line(line) for line in stripped.splitlines()]
    return "\n".join(lines) + "\n"


def validate_obb_label_file(label_path: Path) -> list[str]:
    """Return validation errors for a label file (empty files are allowed)."""
    errors: list[str] = []
    if not label_path.exists():
        return [f"missing label file: {label_path}"]
    text = label_path.read_text(encoding="utf-8").strip()
    if not text:
        return errors
    for line_no, line in enumerate(text.splitlines(), start=1):
        parts = line.split()
        if len(parts) != OBB_COLUMNS:
            errors.append(
                f"{label_path.name}:{line_no} expected {OBB_COLUMNS} values, got {len(parts)}"
            )
            continue
        coords = [float(x) for x in parts[1:]]
        if any(c < -0.01 or c > 1.01 for c in coords):
            errors.append(f"{label_path.name}:{line_no} coordinates out of [0,1] range")
    return errors


def validate_label_dir(label_dir: Path) -> list[str]:
    errors: list[str] = []
    txts = list(label_dir.glob("*.txt"))
    if not txts:
        return [f"no label files in {label_dir}"]
    for txt in txts:
        errors.extend(validate_obb_label_file(txt))
    return errors
