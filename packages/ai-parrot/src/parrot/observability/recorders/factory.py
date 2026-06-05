"""build_recorders_from_config — map an ObservabilityConfig to recorder backends.

Used by the auto-boot (``ensure_observability_bootstrapped``) to instantiate the
pluggable recorders for the selected ``usage_backend`` without the caller knowing
about concrete backend classes.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from parrot.observability.recorders.logging_recorder import LoggingUsageRecorder

if TYPE_CHECKING:
    from parrot.observability.config import ObservabilityConfig
    from parrot.observability.recorders.base import AbstractLogger

logger = logging.getLogger(__name__)


def build_recorders_from_config(
    config: "ObservabilityConfig",
) -> "list[AbstractLogger]":
    """Return the recorder backends for ``config.usage_backend``.

    Only the lightweight (non-OTel) backends are built here: ``"logging"`` and
    ``"prometheus"``. The ``"otel"`` and ``"none"`` backends are handled by the
    bootstrap (delegate to ``setup_telemetry`` / no-op respectively) and yield no
    recorders.

    Args:
        config: The observability configuration.

    Returns:
        A list of ``AbstractLogger`` instances (possibly empty).
    """
    backend = config.usage_backend
    recorders: "list[AbstractLogger]" = []

    if backend == "logging":
        recorders.append(
            LoggingUsageRecorder(
                level=config.usage_log_level,
                logger_name=config.usage_log_logger_name,
            )
        )
    elif backend == "prometheus":
        from parrot.observability.recorders.prometheus_recorder import (  # noqa: PLC0415
            PrometheusUsageRecorder,
        )

        recorders.append(
            PrometheusUsageRecorder(
                port=config.prometheus_port,
                addr=config.prometheus_addr,
            )
        )
    else:
        logger.debug(
            "build_recorders_from_config: backend=%r yields no recorders.", backend
        )

    return recorders
