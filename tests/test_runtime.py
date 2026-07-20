"""Tests for runtime / GPU helpers."""

from pathlib import Path
from unittest.mock import patch

from mooring_fields.runtime import (
    resolve_batch,
    resolve_data_payload,
    resolve_device,
    resolve_predict_batch,
)


class TestRuntime:
    def test_resolve_device_cpu_when_no_cuda(self):
        with patch("mooring_fields.runtime.cuda_available", return_value=False):
            assert resolve_device({"device": "auto"}) == "cpu"

    def test_resolve_device_gpu_when_cuda(self):
        with patch("mooring_fields.runtime.cuda_available", return_value=True):
            assert resolve_device({"device": "auto"}) == 0

    def test_resolve_batch_uses_gpu_batch(self):
        cfg = {"batch": 8, "batch_gpu": 16, "batch_cpu": 4}
        with patch("mooring_fields.runtime.cuda_available", return_value=True):
            assert resolve_batch(cfg) == 16
        with patch("mooring_fields.runtime.cuda_available", return_value=False):
            assert resolve_batch(cfg) == 4

    def test_resolve_predict_batch(self):
        cfg = {"predict_batch": 16, "predict_batch_gpu": 32, "predict_batch_cpu": 4}
        with patch("mooring_fields.runtime.cuda_available", return_value=True):
            assert resolve_predict_batch(cfg) == 32

    def test_resolve_data_payload_nested_data_dir(self, tmp_path: Path):
        root = tmp_path / "mooring-field-data"
        train = root / "data" / "imagery" / "train"
        train.mkdir(parents=True)
        (train / "a.png").write_bytes(b"x")
        (root / "data" / "labels" / "train").mkdir(parents=True)
        assert resolve_data_payload(root) == root / "data"

    def test_resolve_data_payload_flat_imagery(self, tmp_path: Path):
        root = tmp_path / "dataset"
        train = root / "imagery" / "train"
        train.mkdir(parents=True)
        (train / "a.png").write_bytes(b"x")
        assert resolve_data_payload(root) == root
