"""Tests for OBB label utilities."""

from pathlib import Path
from unittest.mock import MagicMock

import numpy as np

from mooring_fields.label_utils import OBB_COLUMNS, validate_obb_label_file, write_obb_labels


class TestLabelUtils:
    def test_write_obb_labels_format(self, tmp_path: Path):
        result = MagicMock()
        corners = np.array([[[0.1, 0.2], [0.3, 0.2], [0.3, 0.4], [0.1, 0.4]]], dtype=np.float32)
        obb = MagicMock()
        obb.xyxyxyxyn.cpu.return_value.numpy.return_value = corners
        result.obb = obb

        label_path = tmp_path / "test.txt"
        count = write_obb_labels(result, label_path, class_id=0)
        assert count == 1
        parts = label_path.read_text(encoding="utf-8").strip().split()
        assert len(parts) == OBB_COLUMNS
        assert parts[0] == "0"

    def test_validate_rejects_wrong_column_count(self, tmp_path: Path):
        bad = tmp_path / "bad.txt"
        bad.write_text("0 0.1 0.2 0.3 0.4 0.5\n", encoding="utf-8")
        errors = validate_obb_label_file(bad)
        assert errors

    def test_validate_accepts_valid_label(self, tmp_path: Path):
        good = tmp_path / "good.txt"
        good.write_text(
            "0 0.10 0.20 0.30 0.20 0.30 0.40 0.10 0.40\n",
            encoding="utf-8",
        )
        assert validate_obb_label_file(good) == []
