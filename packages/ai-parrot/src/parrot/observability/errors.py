"""Custom exceptions for parrot.observability.

FEAT-177 TASK-1235.
"""

from __future__ import annotations


class ConfigurationError(Exception):
    """Raised when ``setup_telemetry`` receives an invalid or conflicting configuration.

    Examples:
        - ``setup_telemetry`` is called twice with different ``ObservabilityConfig``
          instances (hash conflict).
        - A forbidden ``SimpleSpanProcessor`` is detected in the span-processor
          pipeline after provider construction.
    """
