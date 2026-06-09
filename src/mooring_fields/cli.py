"""Command-line entry points for the mooring field pipeline."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from mooring_fields.evaluate import evaluate_val
from mooring_fields.fetch_imagery import fetch_all
from mooring_fields.prelabel_boats import prelabel_all
from mooring_fields.split_sites import run_parse_and_split
from mooring_fields.train_boats import train


def _print(data: dict) -> None:
    print(json.dumps(data, indent=2))


def parse_kml_cmd(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Parse KML and create train/val split")
    parser.add_argument("--kml", type=Path, default=None)
    args = parser.parse_args(argv)
    _print(run_parse_and_split(args.kml))


def fetch_imagery_cmd(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Fetch satellite tiles from Maps Static API")
    parser.add_argument("--split", choices=["train", "val"], default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    _print(fetch_all(split=args.split, dry_run=args.dry_run))


def prelabel_cmd(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Pre-label boats with YOLO-OBB")
    parser.parse_args(argv)
    _print(prelabel_all())


def train_cmd(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Fine-tune YOLO-OBB boat detector")
    parser.add_argument("--corrected-labels", action="store_true")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args(argv)
    _print(train(use_corrected_labels=args.corrected_labels, resume=args.resume))


def evaluate_cmd(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Evaluate mooring field Hit@R on val sites")
    parser.add_argument("--weights", type=Path, default=None)
    args = parser.parse_args(argv)
    _print(evaluate_val(weights=args.weights))


def main() -> None:
    commands = {
        "parse-kml": parse_kml_cmd,
        "fetch": fetch_imagery_cmd,
        "prelabel": prelabel_cmd,
        "train": train_cmd,
        "evaluate": evaluate_cmd,
    }
    if len(sys.argv) < 2 or sys.argv[1] not in commands:
        print("Usage: python -m mooring_fields.cli <command>")
        print("Commands:", ", ".join(commands))
        sys.exit(1)
    cmd = sys.argv[1]
    commands[cmd](sys.argv[2:])


if __name__ == "__main__":
    main()
