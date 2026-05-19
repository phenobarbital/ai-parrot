"""Unit tests for OTLP exporter factory helpers.

FEAT-177 TASK-1234.
"""

from __future__ import annotations

import pytest

from parrot.observability import ObservabilityConfig
from parrot.observability.exporters import make_metric_exporter, make_span_exporter


def test_default_http_span_exporter() -> None:
    """Default protocol produces an HTTP/protobuf OTLPSpanExporter."""
    exp = make_span_exporter(ObservabilityConfig())
    assert "proto.http" in type(exp).__module__


def test_grpc_span_exporter() -> None:
    """grpc protocol produces a gRPC OTLPSpanExporter."""
    exp = make_span_exporter(ObservabilityConfig(otlp_protocol="grpc"))
    assert "proto.grpc" in type(exp).__module__


def test_http_span_endpoint_suffix() -> None:
    """HTTP span exporter endpoint ends with /v1/traces."""
    exp = make_span_exporter(ObservabilityConfig(otlp_endpoint="http://otel:4318"))
    # The endpoint URL is stored internally; inspect via repr/vars
    exp_repr = repr(vars(exp)) if hasattr(exp, '__dict__') else repr(exp)
    assert "/v1/traces" in exp_repr


def test_default_http_metric_exporter() -> None:
    """Default protocol produces an HTTP/protobuf OTLPMetricExporter."""
    exp = make_metric_exporter(ObservabilityConfig())
    assert "proto.http" in type(exp).__module__


def test_grpc_metric_exporter() -> None:
    """grpc protocol produces a gRPC OTLPMetricExporter."""
    exp = make_metric_exporter(ObservabilityConfig(otlp_protocol="grpc"))
    assert "proto.grpc" in type(exp).__module__


def test_metric_exporter_not_none() -> None:
    """make_metric_exporter returns a non-None object."""
    exp = make_metric_exporter(ObservabilityConfig())
    assert exp is not None


def test_http_metric_endpoint_suffix() -> None:
    """HTTP metric exporter endpoint ends with /v1/metrics."""
    exp = make_metric_exporter(ObservabilityConfig(otlp_endpoint="http://otel:4318"))
    exp_repr = repr(vars(exp)) if hasattr(exp, '__dict__') else repr(exp)
    assert "/v1/metrics" in exp_repr
