"""Unit tests for ObservabilityConfig.from_env()."""

from __future__ import annotations

import logging

from parrot.observability.config import ObservabilityConfig

# Environment hermeticity is provided by the package-level
# ``_hermetic_observability_env`` autouse fixture in ``conftest.py``: it pins
# ``ObservabilityConfig`` to the navconfig-free ``os.environ.get`` getter, so
# these tests see a clean environment plus whatever they set via
# ``monkeypatch.setenv`` — the repo's ``env/.env`` no longer bleeds through.


def test_absent_env_uses_defaults() -> None:
    """With no env vars set, from_env matches the model defaults."""
    cfg = ObservabilityConfig.from_env()
    assert cfg.enabled is False
    assert cfg.usage_backend == "none"
    assert cfg.service_name == "ai-parrot"
    assert cfg.enable_cost_tracking is True


def test_maps_all_env_vars(monkeypatch) -> None:
    """Each recognised env var maps to the correct field with proper parsing."""
    monkeypatch.setenv("OBSERVABILITY_ENABLED", "true")
    monkeypatch.setenv("OBSERVABILITY_BACKEND", "prometheus")
    monkeypatch.setenv("OBSERVABILITY_SERVICE_NAME", "my-agent")
    monkeypatch.setenv("OBSERVABILITY_COST", "false")
    monkeypatch.setenv("OBSERVABILITY_LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("OBSERVABILITY_SAMPLING", "0.1")
    monkeypatch.setenv("OBSERVABILITY_OPENLIT", "1")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://collector:4318")
    monkeypatch.setenv("OBSERVABILITY_PROM_PORT", "9999")
    monkeypatch.setenv("OBSERVABILITY_PROM_ADDR", "127.0.0.1")
    monkeypatch.setenv("PARROT_PRICING_PATH", "/tmp/pricing")

    cfg = ObservabilityConfig.from_env()
    assert cfg.enabled is True
    assert cfg.usage_backend == "prometheus"
    assert cfg.service_name == "my-agent"
    assert cfg.enable_cost_tracking is False
    assert cfg.usage_log_level == logging.DEBUG
    assert cfg.sampling_ratio == 0.1
    assert cfg.enable_openlit is True
    assert cfg.otlp_endpoint == "http://collector:4318"
    assert cfg.prometheus_port == 9999
    assert cfg.prometheus_addr == "127.0.0.1"
    assert cfg.pricing_override_path == "/tmp/pricing"


def test_bad_numbers_fall_back_to_defaults(monkeypatch) -> None:
    """Non-numeric port/sampling fall back to defaults instead of raising."""
    monkeypatch.setenv("OBSERVABILITY_PROM_PORT", "not-a-number")
    monkeypatch.setenv("OBSERVABILITY_SAMPLING", "")
    cfg = ObservabilityConfig.from_env()
    assert cfg.prometheus_port == 9464
    assert cfg.sampling_ratio == 1.0


def test_from_env_does_not_import_opentelemetry(monkeypatch) -> None:
    """The logging-config path must not pull in the OTel SDK."""
    import sys

    monkeypatch.setenv("OBSERVABILITY_ENABLED", "true")
    monkeypatch.setenv("OBSERVABILITY_BACKEND", "logging")
    # If OTel was already imported by another test, this assertion is moot;
    # only assert the call itself adds nothing new.
    had_otel = "opentelemetry" in sys.modules
    ObservabilityConfig.from_env()
    if not had_otel:
        assert "opentelemetry" not in sys.modules
