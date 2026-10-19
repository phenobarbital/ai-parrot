"""FEAT-705 — setup_telemetry() attaches one metric reader per OTLP target.

Global telemetry state is reset around every test by the package conftest.
Reader counts always use the configured provider's own ``_metric_readers``,
never the SDK-wide ``MeterProvider._all_metric_readers`` (spec AC12).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest
from opentelemetry import metrics as otel_metrics
from opentelemetry import trace as otel_trace
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import (
    InMemoryMetricReader,
    MetricExporter,
    MetricExportResult,
)
from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult

from parrot.observability.config import ObservabilityConfig, OtlpTarget
from parrot.observability.setup import setup_telemetry

_HTTP_METRIC = "opentelemetry.exporter.otlp.proto.http.metric_exporter.OTLPMetricExporter"
_HTTP_SPAN = "opentelemetry.exporter.otlp.proto.http.trace_exporter.OTLPSpanExporter"


class _FakeMetricExporter(MetricExporter):
    """Network-free metric exporter that records its constructor kwargs."""

    instances: list["_FakeMetricExporter"] = []

    def __init__(self, endpoint: str | None = None, headers: Any = None, **_: Any) -> None:
        super().__init__()
        self.endpoint = endpoint
        self.headers = headers
        _FakeMetricExporter.instances.append(self)

    def export(self, metrics_data: Any, timeout_millis: float = 10_000, **_: Any) -> MetricExportResult:
        return MetricExportResult.SUCCESS

    def force_flush(self, timeout_millis: float = 10_000) -> bool:
        return True

    def shutdown(self, timeout_millis: float = 30_000, **_: Any) -> None:
        return None


class _FakeSpanExporter(SpanExporter):
    """Network-free span exporter that records its constructor kwargs."""

    instances: list["_FakeSpanExporter"] = []

    def __init__(self, endpoint: str | None = None, headers: Any = None, **_: Any) -> None:
        self.endpoint = endpoint
        self.headers = headers
        _FakeSpanExporter.instances.append(self)

    def export(self, spans: Any) -> SpanExportResult:
        return SpanExportResult.SUCCESS

    def shutdown(self) -> None:
        return None


@pytest.fixture
def fake_exporters():
    """Patch both HTTP exporters at their origin modules."""
    _FakeMetricExporter.instances = []
    _FakeSpanExporter.instances = []
    with patch(_HTTP_METRIC, _FakeMetricExporter), patch(_HTTP_SPAN, _FakeSpanExporter):
        yield _FakeMetricExporter, _FakeSpanExporter


def _readers(provider: Any) -> list[Any]:
    assert hasattr(
        provider, "_metric_readers"
    ), "MeterProvider._metric_readers is missing; this OTel version renamed it — update the test"
    return list(provider._metric_readers)


def _cfg(targets: list[OtlpTarget] | None = None, **kw: Any) -> ObservabilityConfig:
    return ObservabilityConfig(enabled=True, enable_cost_tracking=False, otlp_targets=targets or [], **kw)


class TestSetupTelemetryMetricsFanOut:
    """Verify setup_telemetry's metric reader fan-out behavior."""

    def test_two_targets_attach_two_metric_readers(self, fake_exporters) -> None:
        """Two OTLP targets create two readers on the configured provider."""
        targets = [
            OtlpTarget(name="one", endpoint="http://one:4318"),
            OtlpTarget(name="two", endpoint="http://two:4318"),
        ]

        setup_telemetry(_cfg(targets))

        assert len(_readers(otel_metrics.get_meter_provider())) == 2

    def test_single_endpoint_fallback_one_reader(self, fake_exporters) -> None:
        """The legacy endpoint produces one reader with the metrics suffix."""
        setup_telemetry(_cfg(otlp_endpoint="http://default:4318"))

        readers = _readers(otel_metrics.get_meter_provider())
        assert len(readers) == 1
        assert _FakeMetricExporter.instances[0].endpoint == "http://default:4318/v1/metrics"

    def test_readers_use_configured_interval(self, fake_exporters) -> None:
        """Every per-target reader receives the configured export interval."""
        from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader

        targets = [
            OtlpTarget(name="one", endpoint="http://one:4318"),
            OtlpTarget(name="two", endpoint="http://two:4318"),
        ]
        with patch(
            "opentelemetry.sdk.metrics.export.PeriodicExportingMetricReader",
            wraps=PeriodicExportingMetricReader,
        ) as reader_cls:
            setup_telemetry(_cfg(targets, metric_export_interval_ms=5_000))

        assert reader_cls.call_count == 2
        assert all(call.kwargs["export_interval_millis"] == 5_000 for call in reader_cls.call_args_list)

    def test_span_and_metric_target_counts_match(self, fake_exporters) -> None:
        """The tracer processors and metric readers fan out to the same targets."""
        targets = [
            OtlpTarget(name="one", endpoint="http://one:4318"),
            OtlpTarget(name="two", endpoint="http://two:4318"),
            OtlpTarget(name="three", endpoint="http://three:4318"),
        ]

        setup_telemetry(_cfg(targets))

        tracer_provider = otel_trace.get_tracer_provider()
        processors = tracer_provider._active_span_processor._span_processors
        assert len(processors) == 3
        assert len(_readers(otel_metrics.get_meter_provider())) == 3

    def test_reader_count_excludes_other_providers(self, fake_exporters) -> None:
        """Only readers belonging to the configured provider are counted."""
        unrelated_reader = InMemoryMetricReader()
        unrelated_provider = MeterProvider(metric_readers=[unrelated_reader])
        targets = [
            OtlpTarget(name="one", endpoint="http://one:4318"),
            OtlpTarget(name="two", endpoint="http://two:4318"),
        ]
        try:
            setup_telemetry(_cfg(targets))

            readers = _readers(otel_metrics.get_meter_provider())
            assert len(readers) == 2
            assert unrelated_reader not in readers
        finally:
            unrelated_provider.shutdown()

    def test_explicit_targets_override_single_endpoint_for_both_signals(self, fake_exporters) -> None:
        """Explicit targets replace the legacy endpoint for traces and metrics."""
        targets = [OtlpTarget(name="openlit", endpoint="http://openlit:4318")]

        setup_telemetry(_cfg(targets, otlp_endpoint="http://localhost:9090/api/v1/otlp"))

        for exporter in [*_FakeMetricExporter.instances, *_FakeSpanExporter.instances]:
            assert exporter.endpoint is not None
            assert exporter.endpoint.startswith("http://openlit:4318")
            assert "9090" not in exporter.endpoint

    @pytest.mark.parametrize(
        ("traces", "metrics"),
        [(False, True), (True, False), (False, False)],
        ids=["traces-off", "metrics-off", "both-off"],
    )
    def test_signal_switches_skip_subscribers_keep_providers(self, fake_exporters, traces, metrics) -> None:
        """Signal switches skip subscribers but still create both providers."""
        provider = setup_telemetry(_cfg(enable_traces=traces, enable_metrics=metrics))

        assert provider is not None
        assert (provider._trace is None) == (not traces)
        assert (provider._metrics is None) == (not metrics)
        assert isinstance(otel_metrics.get_meter_provider(), MeterProvider)
        assert len(_readers(otel_metrics.get_meter_provider())) == 1
        tracer_provider = otel_trace.get_tracer_provider()
        assert len(tracer_provider._active_span_processor._span_processors) == 1
