"""Tests for YOLO-OBB dataset export."""

from pathlib import Path

import pytest

import mooring_fields.export_dataset as export_dataset
from mooring_fields.export_dataset import export_yolo_dataset

VALID_OBB = "0 0.10 0.10 0.20 0.10 0.20 0.20 0.10 0.20\n"


def _point_paths_at(monkeypatch: pytest.MonkeyPatch, dataset_dir: Path) -> None:
    """Make IMAGERY_DIR/LABELS_DIR resolve to the export destination (src == dst)."""
    monkeypatch.setattr(export_dataset, "DATASET_DIR", dataset_dir)
    monkeypatch.setattr(export_dataset, "IMAGERY_DIR", dataset_dir / "images")
    monkeypatch.setattr(export_dataset, "LABELS_DIR", dataset_dir / "labels")
    monkeypatch.setattr(export_dataset, "PRELABELS_DIR", dataset_dir / "prelabels")


class TestExportSelfCopy:
    def test_export_does_not_raise_when_src_equals_dst(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        dataset_dir = tmp_path / "mooring_boats"
        for split in ("train", "val"):
            img = dataset_dir / "images" / split
            lbl = dataset_dir / "labels" / split
            img.mkdir(parents=True)
            lbl.mkdir(parents=True)
            (img / "a.png").write_bytes(b"\x89PNG\r\n")
            (lbl / "a.txt").write_text(VALID_OBB, encoding="utf-8")

        _point_paths_at(monkeypatch, dataset_dir)

        # Mirrors the Kaggle clone-only fallback where imagery/labels already
        # live in the export destination. Must not raise SameFileError.
        out = export_yolo_dataset(use_corrected_labels=True)

        assert (out / "data.yaml").exists()
        assert (out / "images" / "train" / "a.png").exists()
        assert (out / "labels" / "train" / "a.txt").read_text(encoding="utf-8").strip()
        assert (out / "images" / "val" / "a.png").exists()

    def test_export_copies_when_src_differs_from_dst(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        src = tmp_path / "src"
        dataset_dir = tmp_path / "mooring_boats"
        for split in ("train", "val"):
            img = src / "imagery" / split
            lbl = src / "labels" / split
            img.mkdir(parents=True)
            lbl.mkdir(parents=True)
            (img / "b.png").write_bytes(b"\x89PNG\r\n")
            (lbl / "b.txt").write_text(VALID_OBB, encoding="utf-8")

        monkeypatch.setattr(export_dataset, "DATASET_DIR", dataset_dir)
        monkeypatch.setattr(export_dataset, "IMAGERY_DIR", src / "imagery")
        monkeypatch.setattr(export_dataset, "LABELS_DIR", src / "labels")
        monkeypatch.setattr(export_dataset, "PRELABELS_DIR", src / "prelabels")

        out = export_yolo_dataset(use_corrected_labels=True)

        assert (out / "images" / "train" / "b.png").exists()
        assert (out / "labels" / "train" / "b.txt").exists()
