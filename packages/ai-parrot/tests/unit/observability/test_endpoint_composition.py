"""OTLP endpoint composition and the sampling kill-switch.

FEAT-548 AC-1/AC-6. The endpoint in .env is a BASE url; the exporter appends the
signal path. Traces are silenced by sampling because ``enable_traces`` is not
env-settable (config.py:132).
"""
from __future__ import annotations

import pytest

pytest.importorskip("opentelemetry")  # needs the `observability` extra

from parrot.observability.config import ObservabilityConfig  # noqa: E402
from parrot.observability import exporters  # noqa: E402

PROM_BASE = "http://localhost:9090/api/v1/otlp"


def _spy_metric_exporter(monkeypatch, captured: dict[str, str]) -> None:
    """Patch OTLPMetricExporter where make_metric_exporter looks it up.

    ``make_metric_exporter`` does a function-local
    ``from opentelemetry.exporter.otlp.proto.http.metric_exporter import
    OTLPMetricExporter`` on every call (exporters.py:148), so patching the
    symbol on the *origin* module — not on ``exporters`` — is what actually
    intercepts it.
    """
    from opentelemetry.exporter.otlp.proto.http import metric_exporter as http_metric_exporter

    class _Spy:
        def __init__(self, endpoint: str, headers=None):
            captured["endpoint"] = endpoint

    monkeypatch.setattr(http_metric_exporter, "OTLPMetricExporter", _Spy)


def test_otlp_endpoint_composes_to_prometheus_path(monkeypatch):
    """The Prometheus base URL must yield exactly .../api/v1/otlp/v1/metrics."""
    captured: dict[str, str] = {}
    _spy_metric_exporter(monkeypatch, captured)

    make = exporters.make_metric_exporter
    make(ObservabilityConfig(otlp_endpoint=PROM_BASE))
    assert captured["endpoint"] == f"{PROM_BASE}/v1/metrics"


@pytest.mark.parametrize("given", [PROM_BASE, PROM_BASE + "/"])
def test_trailing_slash_is_tolerated(monkeypatch, given):
    """A trailing slash must not produce a doubled separator."""
    captured: dict[str, str] = {}
    _spy_metric_exporter(monkeypatch, captured)

    exporters.make_metric_exporter(ObservabilityConfig(otlp_endpoint=given))
    assert captured["endpoint"] == f"{PROM_BASE}/v1/metrics"
    assert "//v1/" not in captured["endpoint"]


def test_zero_sampling_emits_no_spans():
    """sampling_ratio=0.0 stops span export while metrics keep recording.

    Asserting only "no spans" would also pass if telemetry were entirely broken,
    so this must assert the metric side still works.
    """
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.metrics.export import InMemoryMetricReader
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
    from opentelemetry.sdk.trace.sampling import TraceIdRatioBased

    # --- trace side: built exactly as setup_telemetry does (setup.py:144-146) ---
    span_exporter = InMemorySpanExporter()
    tracer_provider = TracerProvider(sampler=TraceIdRatioBased(0.0))
    tracer_provider.add_span_processor(SimpleSpanProcessor(span_exporter))
    tracer = tracer_provider.get_tracer(__name__)

    with tracer.start_as_current_span("kill-switch-probe") as span:
        assert span.is_recording() is False

    assert span_exporter.get_finished_spans() == (), (
        "sampling_ratio=0.0 must produce zero exported spans — "
        "TraceIdRatioBased(0.0) marks every span non-recording (AC-6)"
    )

    # --- metric side: independent MeterProvider must still record -------------
    metric_reader = InMemoryMetricReader()
    meter_provider = MeterProvider(metric_readers=[metric_reader])
    meter = meter_provider.get_meter(__name__)
    counter = meter.create_counter("kill_switch_probe_total")
    counter.add(1)

    data = metric_reader.get_metrics_data()
    data_points = [
        dp
        for rm in data.resource_metrics
        for sm in rm.scope_metrics
        for m in sm.metrics
        for dp in m.data.data_points
    ]
    assert len(data_points) == 1, (
        "metrics must keep recording while traces are silenced — sampling is a "
        "trace-only kill-switch (AC-6)"
    )
