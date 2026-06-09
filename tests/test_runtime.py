"""Tests for runtime / GPU helpers."""

from unittest.mock import patch

from mooring_fields.runtime import resolve_batch, resolve_device, resolve_predict_batch


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
