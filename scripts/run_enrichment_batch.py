"""Run enrich-all in a loop until no pending fields remain."""

from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "mooring_fields.db"


def pending_count() -> int:
    conn = sqlite3.connect(DB)
    try:
        return int(
            conn.execute(
                "SELECT COUNT(*) FROM fields WHERE enrichment_status = ?",
                ("pending",),
            ).fetchone()[0]
        )
    finally:
        conn.close()


def main() -> None:
    reports: list[dict] = []
    rounds = 0
    while pending_count() > 0 and rounds < 30:
        rounds += 1
        n = pending_count()
        print(f"--- Round {rounds}, pending={n} ---", flush=True)
        result = subprocess.run(
            [sys.executable, "-m", "mooring_fields.cli", "enrich-all", "--only-new"],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        if result.stdout:
            print(result.stdout[-2500:], flush=True)
        if result.stderr:
            print("STDERR:", result.stderr[-800:], flush=True)
        if result.returncode != 0:
            print(f"FAILED exit {result.returncode}", flush=True)
            sys.exit(result.returncode)
        try:
            reports.append(json.loads(result.stdout))
        except json.JSONDecodeError:
            pass
        time.sleep(1)

    out = ROOT / "data" / "enrichment_outputs" / "batch_reports.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(reports, indent=2), encoding="utf-8")
    print(f"FINAL pending={pending_count()} rounds={rounds}", flush=True)


if __name__ == "__main__":
    main()
