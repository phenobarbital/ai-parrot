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

from parrot.observability.config import ObservabilityConfig, OtlpTarget


def make_span_exporters(
    targets: list[OtlpTarget],
    protocol: str = "http/protobuf",
) -> list[Any]:
    """Return one OTLP span exporter per *targets* entry (FEAT-462).

    Multi-endpoint counterpart to :func:`make_span_exporter`. Each target
    gets its own exporter built from its ``endpoint``/``headers``; all
    targets share the same *protocol*. This is how ``setup_telemetry()``
    attaches one ``BatchSpanProcessor`` per target to a single shared
    ``TracerProvider`` — there is no ``CompositeSpanExporter`` in the OTel
    SDK.

    Args:
        targets: List of OTLP export destinations.
        protocol: Shared transport protocol for all targets
            (``"http/protobuf"`` or ``"grpc"``).

    Returns:
        A list of exporter instances, one per target, in the same order as
        *targets*. Empty list when *targets* is empty.

    Raises:
        ImportError: When ``protocol="grpc"`` is requested but the gRPC
            exporter package is not installed.
    """
    exporters: list[Any] = []
    for target in targets:
        if protocol == "grpc":
            try:
                from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
                    OTLPSpanExporter as GrpcSpanExporter,
                )
            except ImportError as exc:
                raise ImportError(
                    "gRPC OTLP exporter requires the 'observability' extra "
                    "with grpcio. Install with: pip install "
                    "'ai-parrot[observability]' grpcio"
                ) from exc
            headers = tuple(target.headers.items()) or None
            exporters.append(GrpcSpanExporter(endpoint=target.endpoint, headers=headers))
            continue

        # Default: http/protobuf — mirror make_span_exporter()'s /v1/traces
        # endpoint suffixing so the single-target fallback in
        # setup_telemetry() (TASK-2474) is byte-for-byte identical to the
        # pre-FEAT-462 behavior.
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter,
        )

        endpoint = f"{target.endpoint.rstrip('/')}/v1/traces"
        headers = target.headers or None
        exporters.append(OTLPSpanExporter(endpoint=endpoint, headers=headers))
    return exporters


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
