"""Unit tests for the multi-endpoint OTLP exporter factory (FEAT-462).

Spec: sdd/specs/unified-telemetry-bus.spec.md §3 Module 2.
Task: TASK-2471.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from parrot.observability.config import ObservabilityConfig, OtlpTarget
from parrot.observability.exporters import (
    make_metric_exporter,
    make_metric_exporters,
    make_span_exporter,
    make_span_exporters,
)


class TestMakeSpanExporters:
    def test_multi_target(self) -> None:
        targets = [
            OtlpTarget(name="a", endpoint="http://a:4318"),
            OtlpTarget(name="b", endpoint="http://b:4318"),
        ]
        with patch("opentelemetry.exporter.otlp.proto.http.trace_exporter.OTLPSpanExporter") as mock_cls:
            mock_cls.return_value = MagicMock()
            result = make_span_exporters(targets)
            assert len(result) == 2
            assert mock_cls.call_count == 2

    def test_empty_targets(self) -> None:
        assert make_span_exporters([]) == []

    def test_headers_passed_through(self) -> None:
        """Headers from the OtlpTarget are forwarded to the exporter.

        NOTE — deviation from the task's illustrative test: the endpoint
        passed to ``OTLPSpanExporter`` carries the ``/v1/traces`` suffix,
        matching ``make_span_exporter()``'s existing HTTP behavior (see
        ``test_http_span_endpoint_suffix`` in ``test_exporters.py``). This is
        required for the TASK-2474 single-target fallback to be identical to
        pre-FEAT-462 behavior, per that task's own acceptance criteria.
        """
        target = OtlpTarget(
            name="authed",
            endpoint="http://x:4318",
            headers={"Authorization": "Bearer tok"},
        )
        with patch("opentelemetry.exporter.otlp.proto.http.trace_exporter.OTLPSpanExporter") as mock_cls:
            mock_cls.return_value = MagicMock()
            make_span_exporters([target])
            mock_cls.assert_called_once_with(
                endpoint="http://x:4318/v1/traces",
                headers={"Authorization": "Bearer tok"},
            )

    def test_grpc_protocol(self) -> None:
        target = OtlpTarget(name="a", endpoint="http://a:4317")
        with patch("opentelemetry.exporter.otlp.proto.grpc.trace_exporter.OTLPSpanExporter") as mock_cls:
            mock_cls.return_value = MagicMock()
            result = make_span_exporters([target], protocol="grpc")
            assert len(result) == 1
            mock_cls.assert_called_once_with(endpoint="http://a:4317", headers=None)

    def test_single_target_matches_make_span_exporter(self) -> None:
        """The single-target fallback path is identical to make_span_exporter().

        Verifies the TASK-2474 requirement that wrapping ``otlp_endpoint``
        into a single-element ``OtlpTarget`` list produces byte-for-byte the
        same exporter endpoint as the existing single-target factory.
        """
        config = ObservabilityConfig(otlp_endpoint="http://default:4318")
        single = make_span_exporter(config)
        fallback_target = OtlpTarget(
            name="default",
            endpoint=config.otlp_endpoint,
            headers=config.otlp_headers,
        )
        fallback = make_span_exporters([fallback_target])[0]
        assert single._endpoint == fallback._endpoint

    def test_multiple_targets_preserve_order(self) -> None:
        targets = [
            OtlpTarget(name="a", endpoint="http://a:4318"),
            OtlpTarget(name="b", endpoint="http://b:4318"),
            OtlpTarget(name="c", endpoint="http://c:4318"),
        ]
        result = make_span_exporters(targets)
        assert len(result) == 3
        endpoints = [e._endpoint for e in result]
        assert endpoints == [
            "http://a:4318/v1/traces",
            "http://b:4318/v1/traces",
            "http://c:4318/v1/traces",
        ]


_HTTP_METRIC = "opentelemetry.exporter.otlp.proto.http.metric_exporter.OTLPMetricExporter"
_GRPC_METRIC = "opentelemetry.exporter.otlp.proto.grpc.metric_exporter.OTLPMetricExporter"


class TestMakeMetricExporters:
    """FEAT-705 — metric twin of TestMakeSpanExporters."""

    def test_multi_target(self) -> None:
        targets = [
            OtlpTarget(name="a", endpoint="http://a:4318"),
            OtlpTarget(name="b", endpoint="http://b:4318"),
        ]
        with patch(_HTTP_METRIC) as mock_cls:
            mock_cls.return_value = MagicMock()
            result = make_metric_exporters(targets)
            assert len(result) == 2
            assert mock_cls.call_count == 2

    def test_empty_targets(self) -> None:
        assert make_metric_exporters([]) == []

    def test_headers_passed_through(self) -> None:
        target = OtlpTarget(
            name="authed",
            endpoint="http://x:4318",
            headers={"Authorization": "Bearer tok"},
        )
        empty_headers_target = OtlpTarget(name="empty", endpoint="http://y:4318")
        with patch(_HTTP_METRIC) as mock_cls:
            mock_cls.return_value = MagicMock()
            make_metric_exporters([target])
            mock_cls.assert_called_once_with(
                endpoint="http://x:4318/v1/metrics",
                headers={"Authorization": "Bearer tok"},
            )
            mock_cls.reset_mock()
            make_metric_exporters([empty_headers_target])
            mock_cls.assert_called_once_with(endpoint="http://y:4318/v1/metrics", headers=None)

    def test_endpoint_suffix_matches_single_helper(self) -> None:
        config = ObservabilityConfig(otlp_endpoint="http://default:4318/")
        assert make_metric_exporter(config)._endpoint == make_metric_exporters(
            [OtlpTarget(name="default", endpoint=config.otlp_endpoint)]
        )[0]._endpoint

    def test_grpc_protocol(self) -> None:
        target = OtlpTarget(name="a", endpoint="http://a:4317", headers={"k": "v"})
        with patch(_GRPC_METRIC) as mock_cls:
            mock_cls.return_value = MagicMock()
            make_metric_exporters([target], protocol="grpc")
            mock_cls.assert_called_once_with(endpoint="http://a:4317", headers=(("k", "v"),))

    def test_multiple_targets_preserve_order(self) -> None:
        targets = [
            OtlpTarget(name="a", endpoint="http://a:4318"),
            OtlpTarget(name="b", endpoint="http://b:4318"),
            OtlpTarget(name="c", endpoint="http://c:4318"),
        ]
        result = make_metric_exporters(targets)
        assert [exporter._endpoint for exporter in result] == [
            "http://a:4318/v1/metrics",
            "http://b:4318/v1/metrics",
            "http://c:4318/v1/metrics",
        ]
