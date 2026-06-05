"""AbstractLogger — the pluggable usage-recording interface.

Every usage backend (logging, Prometheus, …) implements this single async
surface so that swapping backends is a configuration change, not a code change.
``UsageRecordingSubscriber`` builds one ``UsageRecord`` per LLM call and calls
``record`` on each configured backend.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from parrot.observability.recorders.models import UsageRecord


class AbstractLogger(ABC):
    """Abstract base for pluggable usage/token/cost recorders.

    Implementations MUST be cheap and non-blocking on the hot path: ``record``
    runs inside the event-dispatch coroutine of every LLM call. Backends that
    perform network I/O should buffer and flush out-of-band, or rely on a
    pull-based exposition model (e.g. Prometheus).

    Attributes:
        name: Short identifier for the backend (used in logs/diagnostics).
    """

    name: str = "abstract"

    @abstractmethod
    async def record(self, record: UsageRecord) -> None:
        """Record a single normalized usage record.

        Args:
            record: The per-call ``UsageRecord`` to persist/emit.
        """
        raise NotImplementedError

    async def aclose(self) -> None:
        """Flush and release any resources. Default implementation is a no-op.

        Stateful backends (buffered exporters, HTTP servers) override this to
        flush on shutdown. Called by ``shutdown_usage_recording``.
        """
        return None
