"""StorageMetrics protocol and no-op default implementation.

Defines the two-method observability seam used by ``InstrumentedBackend``.
Production callers plug in their own adapter (Prometheus, OpenTelemetry,
statsd) by implementing this protocol and pointing ``PARROT_STORAGE_METRICS``
at a module-level instance.

FEAT-116: dynamodb-fallback-redis — Module 8 (observability hooks).
"""

from typing import Protocol, runtime_checkable


@runtime_checkable
class StorageMetrics(Protocol):
    """Protocol for storage-backend metric collection.

    Implementers plug in Prometheus / OpenTelemetry / statsd in their own code.
    AI-Parrot ships a no-op default and an ``InstrumentedBackend`` wrapper that
    calls these methods around every backend operation.

    Example Prometheus adapter — see docs/storage-backends.md §Observability.
    """

    def record_latency(
        self,
        backend_name: str,
        method: str,
        duration_ms: float,
    ) -> None:
        """Record the latency of a single backend method call.

        Args:
            backend_name: Class name of the backend (e.g. ``"ConversationSQLiteBackend"``).
            method: Name of the method called (e.g. ``"put_thread"``).
            duration_ms: Wall-clock duration in milliseconds.
        """
        ...

    def record_error(
        self,
        backend_name: str,
        method: str,
        error_type: str,
    ) -> None:
        """Record that a backend method raised an exception.

        Args:
            backend_name: Class name of the backend.
            method: Name of the method that raised.
            error_type: ``type(exc).__name__`` of the exception.
        """
        ...


class NoopStorageMetrics:
    """Default metrics implementation — records nothing.

    Used when ``PARROT_STORAGE_METRICS`` is unset (the common case).
    Zero overhead: every method is a Python ``...`` no-op.
    """

    def record_latency(
        self, backend_name: str, method: str, duration_ms: float
    ) -> None: ...

    def record_error(
        self, backend_name: str, method: str, error_type: str
    ) -> None: ...
