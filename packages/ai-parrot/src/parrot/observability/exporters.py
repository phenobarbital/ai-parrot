"""OTLP exporter factory helpers.

FEAT-177 TASK-1234.

Factory functions returning OTLP span and metric exporters configured from
``ObservabilityConfig``. Supports both ``http/protobuf`` (default) and
``grpc`` protocols. gRPC exporters are lazy-imported so users without
``grpcio`` installed are not broken when they choose the HTTP default.

Spec §3 Module 7.
"""

from __future__ import annotations

from typing import Any

from parrot.observability.config import ObservabilityConfig


def make_span_exporter(config: ObservabilityConfig) -> Any:
    """Return an OTLP span exporter configured from *config*.

    Args:
        config: ``ObservabilityConfig`` instance providing endpoint, protocol,
            and optional headers.

    Returns:
        An ``OTLPSpanExporter`` instance (HTTP or gRPC variant).

    Raises:
        ImportError: When ``protocol="grpc"`` is requested but the gRPC
            exporter package is not installed.
    """
    if config.otlp_protocol == "grpc":
        try:
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (  # noqa: PLC0415
                OTLPSpanExporter as GrpcSpanExporter,
            )
        except ImportError as exc:
            raise ImportError(
                "gRPC OTLP exporter requires the 'observability' extra with grpcio. "
                "Install with: pip install 'ai-parrot[observability]' grpcio"
            ) from exc
        headers = tuple(config.otlp_headers.items()) or None
        return GrpcSpanExporter(
            endpoint=config.otlp_endpoint,
            headers=headers,
        )

    # Default: http/protobuf
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import (  # noqa: PLC0415
        OTLPSpanExporter,
    )
    endpoint = f"{config.otlp_endpoint.rstrip('/')}/v1/traces"
    headers = config.otlp_headers or None
    return OTLPSpanExporter(endpoint=endpoint, headers=headers)


def make_metric_exporter(config: ObservabilityConfig) -> Any:
    """Return an OTLP metric exporter configured from *config*.

    Args:
        config: ``ObservabilityConfig`` instance providing endpoint, protocol,
            and optional headers.

    Returns:
        An ``OTLPMetricExporter`` instance (HTTP or gRPC variant).

    Raises:
        ImportError: When ``protocol="grpc"`` is requested but the gRPC
            exporter package is not installed.
    """
    if config.otlp_protocol == "grpc":
        try:
            from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import (  # noqa: PLC0415
                OTLPMetricExporter as GrpcMetricExporter,
            )
        except ImportError as exc:
            raise ImportError(
                "gRPC OTLP metric exporter requires the 'observability' extra with grpcio. "
                "Install with: pip install 'ai-parrot[observability]' grpcio"
            ) from exc
        headers = tuple(config.otlp_headers.items()) or None
        return GrpcMetricExporter(
            endpoint=config.otlp_endpoint,
            headers=headers,
        )

    # Default: http/protobuf
    from opentelemetry.exporter.otlp.proto.http.metric_exporter import (  # noqa: PLC0415
        OTLPMetricExporter,
    )
    endpoint = f"{config.otlp_endpoint.rstrip('/')}/v1/metrics"
    headers = config.otlp_headers or None
    return OTLPMetricExporter(endpoint=endpoint, headers=headers)
