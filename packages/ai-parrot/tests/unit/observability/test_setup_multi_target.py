"""Unit tests for the multi-endpoint OTLP export refactor of setup_telemetry()
(FEAT-462).

Telemetry global state is reset around every test by the package-level
``_isolate_observability_globals`` autouse fixture in ``conftest.py`` (see
``test_setup.py``'s module docstring for details).

Spec: sdd/specs/unified-telemetry-bus.spec.md §3 Module 5.
Task: TASK-2474.
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

from parrot.observability.config import ObservabilityConfig, OtlpTarget
from parrot.observability.setup import setup_telemetry


class TestSetupTelemetryMultiTarget:
    def test_multi_target_creates_multiple_bsps(self) -> None:
        """2 otlp_targets attach 2 BatchSpanProcessors to the TracerProvider."""
        from opentelemetry import trace as otel_trace

        config = ObservabilityConfig(
            enabled=True,
            enable_cost_tracking=False,
            otlp_targets=[
                OtlpTarget(name="a", endpoint="http://a:4318"),
                OtlpTarget(name="b", endpoint="http://b:4318"),
            ],
        )
        setup_telemetry(config)
        tracer_provider = otel_trace.get_tracer_provider()
        processors = tracer_provider._active_span_processor._span_processors
        assert len(processors) == 2

    def test_three_targets_creates_three_bsps(self) -> None:
        from opentelemetry import trace as otel_trace

        config = ObservabilityConfig(
            enabled=True,
            enable_cost_tracking=False,
            otlp_targets=[
                OtlpTarget(name="a", endpoint="http://a:4318"),
                OtlpTarget(name="b", endpoint="http://b:4318"),
                OtlpTarget(name="c", endpoint="http://c:4318"),
            ],
        )
        setup_telemetry(config)
        tracer_provider = otel_trace.get_tracer_provider()
        processors = tracer_provider._active_span_processor._span_processors
        assert len(processors) == 3

    def test_single_endpoint_fallback(self) -> None:
        """When otlp_targets is empty, falls back to a single implicit target
        wrapping otlp_endpoint — identical behavior to pre-FEAT-462 code."""
        from opentelemetry import trace as otel_trace

        config = ObservabilityConfig(
            enabled=True,
            enable_cost_tracking=False,
            otlp_endpoint="http://default:4318",
        )
        setup_telemetry(config)
        tracer_provider = otel_trace.get_tracer_provider()
        processors = tracer_provider._active_span_processor._span_processors
        assert len(processors) == 1

    def test_no_openlit_init(self) -> None:
        """setup_telemetry no longer imports or calls openlit.init, even when
        the deprecated enable_openlit flag is set."""
        fake_openlit = MagicMock()
        with patch.dict(sys.modules, {"openlit": fake_openlit}):
            config = ObservabilityConfig(
                enabled=True,
                enable_cost_tracking=False,
                enable_openlit=True,
            )
            setup_telemetry(config)
            assert fake_openlit.init.call_count == 0

    def test_setup_source_has_no_init_openlit_call(self) -> None:
        """init_openlit is not referenced anywhere in setup.py's source."""
        import parrot.observability.setup as mod

        with open(mod.__file__) as f:
            source = f.read()
        assert "init_openlit" not in source
