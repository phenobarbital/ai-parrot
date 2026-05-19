"""Unit tests for ObservabilityConfig.

FEAT-177 TASK-1228 — validates defaults and Pydantic v2 validation.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from parrot.observability import ObservabilityConfig


def test_config_defaults() -> None:
    """All spec-mandated defaults must match exactly."""
    cfg = ObservabilityConfig()
    assert cfg.enabled is False
    assert cfg.capture_prompts is False
    assert cfg.capture_completions is False
    assert cfg.sampling_ratio == 1.0
    assert cfg.otlp_endpoint == "http://localhost:4318"
    assert cfg.otlp_protocol == "http/protobuf"
    assert cfg.enable_cost_tracking is True
    assert cfg.enable_openlit is False
    assert cfg.enable_traces is True
    assert cfg.enable_metrics is True
    assert cfg.otlp_headers == {}
    assert cfg.metric_export_interval_ms == 60_000
    assert cfg.histogram_buckets is None
    assert cfg.pricing_override_path is None
    assert cfg.service_name == "ai-parrot"
    assert cfg.service_version is None
    assert cfg.service_instance_id is None


def test_config_rejects_invalid_sampling() -> None:
    """sampling_ratio > 1.0 must raise ValidationError."""
    with pytest.raises(ValidationError):
        ObservabilityConfig(sampling_ratio=1.5)


def test_config_rejects_negative_sampling() -> None:
    """sampling_ratio < 0.0 must raise ValidationError."""
    with pytest.raises(ValidationError):
        ObservabilityConfig(sampling_ratio=-0.1)


def test_config_rejects_unknown_protocol() -> None:
    """Unknown otlp_protocol must raise ValidationError."""
    with pytest.raises(ValidationError):
        ObservabilityConfig(otlp_protocol="thrift")  # type: ignore[arg-type]


def test_config_grpc_protocol_accepted() -> None:
    """'grpc' is a valid otlp_protocol."""
    cfg = ObservabilityConfig(otlp_protocol="grpc")
    assert cfg.otlp_protocol == "grpc"


def test_config_enabled_flag() -> None:
    """enabled=True constructs cleanly."""
    cfg = ObservabilityConfig(enabled=True, service_name="my-service")
    assert cfg.enabled is True
    assert cfg.service_name == "my-service"


def test_config_custom_histogram_buckets() -> None:
    """Custom histogram_buckets are stored as-is."""
    buckets = [0.1, 0.5, 1.0, 2.0]
    cfg = ObservabilityConfig(histogram_buckets=buckets)
    assert cfg.histogram_buckets == buckets
