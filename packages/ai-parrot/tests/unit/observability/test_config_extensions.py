"""Unit tests for FEAT-462 config model extensions.

Covers the new ``OtlpTarget`` model, ``ObservabilityConfig.otlp_targets`` /
``openlit_recorder_endpoint`` fields, the ``OTLP_TARGETS`` /
``OBSERVABILITY_OPENLIT_RECORDER`` env vars, and the deprecation warnings
for ``enable_openlit`` / ``enable_traceloop`` / ``usage_backend="traceloop"``.

Spec: sdd/specs/unified-telemetry-bus.spec.md §3 Module 1.
Task: TASK-2470.
"""

from __future__ import annotations

import json
import warnings

from parrot.observability.config import ObservabilityConfig, OtlpTarget

# Environment hermeticity for OBSERVABILITY_* / OTEL_EXPORTER_OTLP_ENDPOINT /
# PARROT_PRICING_PATH is provided by the package-level
# ``_hermetic_observability_env`` autouse fixture in ``conftest.py``.
# ``OTLP_TARGETS`` is not covered by that fixture, so tests that rely on it
# clear it explicitly via ``monkeypatch.delenv``.


class TestOtlpTarget:
    """Construction/serialization of the new ``OtlpTarget`` model."""

    def test_construction(self) -> None:
        t = OtlpTarget(name="openlit", endpoint="http://localhost:4318")
        assert t.name == "openlit"
        assert t.endpoint == "http://localhost:4318"
        assert t.headers == {}

    def test_with_headers(self) -> None:
        t = OtlpTarget(
            name="tempo",
            endpoint="http://tempo:4318",
            headers={"Authorization": "Bearer tok"},
        )
        assert t.headers["Authorization"] == "Bearer tok"


class TestObservabilityConfigOtlpTargets:
    """``ObservabilityConfig.otlp_targets`` field behavior."""

    def test_accepts_list_of_otlp_target(self) -> None:
        cfg = ObservabilityConfig(otlp_targets=[OtlpTarget(name="a", endpoint="http://a:4318")])
        assert len(cfg.otlp_targets) == 1
        assert cfg.otlp_targets[0].name == "a"

    def test_defaults_to_empty_list(self) -> None:
        cfg = ObservabilityConfig()
        assert cfg.otlp_targets == []


class TestOtlpTargetsEnvParsing:
    """``ObservabilityConfig.from_env()`` reads ``OTLP_TARGETS``."""

    def test_parses_json_list(self, monkeypatch) -> None:
        targets = [{"name": "a", "endpoint": "http://a:4318"}]
        monkeypatch.setenv("OTLP_TARGETS", json.dumps(targets))
        monkeypatch.setenv("OBSERVABILITY_ENABLED", "true")
        cfg = ObservabilityConfig.from_env()
        assert len(cfg.otlp_targets) == 1
        assert cfg.otlp_targets[0].name == "a"

    def test_parses_multiple_targets_with_headers(self, monkeypatch) -> None:
        targets = [
            {"name": "openlit", "endpoint": "http://localhost:4318"},
            {
                "name": "tempo",
                "endpoint": "http://tempo:4318",
                "headers": {"Authorization": "Bearer test-token"},
            },
        ]
        monkeypatch.setenv("OTLP_TARGETS", json.dumps(targets))
        cfg = ObservabilityConfig.from_env()
        assert len(cfg.otlp_targets) == 2
        assert cfg.otlp_targets[1].headers["Authorization"] == "Bearer test-token"

    def test_malformed_json_falls_back(self, monkeypatch) -> None:
        monkeypatch.setenv("OTLP_TARGETS", "not json")
        monkeypatch.setenv("OBSERVABILITY_ENABLED", "true")
        cfg = ObservabilityConfig.from_env()
        assert cfg.otlp_targets == []

    def test_absent_env_var_defaults_to_empty(self, monkeypatch) -> None:
        monkeypatch.delenv("OTLP_TARGETS", raising=False)
        cfg = ObservabilityConfig.from_env()
        assert cfg.otlp_targets == []


class TestOpenlitRecorderEnvParsing:
    """``ObservabilityConfig.from_env()`` reads ``OBSERVABILITY_OPENLIT_RECORDER``."""

    def test_defaults_to_none(self, monkeypatch) -> None:
        monkeypatch.delenv("OBSERVABILITY_OPENLIT_RECORDER", raising=False)
        monkeypatch.delenv("OBSERVABILITY_OPENLIT_RECORDER_ENDPOINT", raising=False)
        cfg = ObservabilityConfig.from_env()
        assert cfg.openlit_recorder_endpoint is None

    def test_true_falls_back_to_otlp_endpoint(self, monkeypatch) -> None:
        monkeypatch.setenv("OBSERVABILITY_OPENLIT_RECORDER", "true")
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://collector:4318")
        cfg = ObservabilityConfig.from_env()
        assert cfg.openlit_recorder_endpoint == "http://collector:4318"

    def test_explicit_endpoint_override(self, monkeypatch) -> None:
        monkeypatch.setenv("OBSERVABILITY_OPENLIT_RECORDER", "true")
        monkeypatch.setenv("OBSERVABILITY_OPENLIT_RECORDER_ENDPOINT", "http://openlit:4318")
        cfg = ObservabilityConfig.from_env()
        assert cfg.openlit_recorder_endpoint == "http://openlit:4318"


class TestDeprecationWarnings:
    """Deprecation behavior for ``enable_openlit``/``enable_traceloop``/``traceloop`` backend."""

    def test_enable_openlit_warns(self) -> None:
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            ObservabilityConfig(enable_openlit=True)
            depr = [x for x in w if issubclass(x.category, DeprecationWarning)]
            assert any("enable_openlit" in str(d.message) for d in depr)

    def test_enable_traceloop_warns(self) -> None:
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            ObservabilityConfig(enable_traceloop=True)
            depr = [x for x in w if issubclass(x.category, DeprecationWarning)]
            assert any("enable_traceloop" in str(d.message) for d in depr)

    def test_no_warning_when_flags_false(self) -> None:
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            ObservabilityConfig()
            depr = [x for x in w if issubclass(x.category, DeprecationWarning)]
            assert depr == []

    def test_traceloop_backend_maps_to_otel(self, monkeypatch) -> None:
        monkeypatch.setenv("OBSERVABILITY_ENABLED", "true")
        monkeypatch.setenv("OBSERVABILITY_BACKEND", "traceloop")
        cfg = ObservabilityConfig.from_env()
        assert cfg.usage_backend == "otel"

    def test_traceloop_backend_maps_to_otel_direct_construction(self) -> None:
        """The mapping also applies when constructing the model directly."""
        cfg = ObservabilityConfig(usage_backend="traceloop")
        assert cfg.usage_backend == "otel"
