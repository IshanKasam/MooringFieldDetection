"""Command-line entry points for the mooring field pipeline."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

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
    }
    if len(sys.argv) < 2 or sys.argv[1] not in commands:
        print("Usage: python -m mooring_fields.cli <command>")
        print("Commands:", ", ".join(commands))
        sys.exit(1)
    cmd = sys.argv[1]
    commands[cmd](sys.argv[2:])


if __name__ == "__main__":
    main()
