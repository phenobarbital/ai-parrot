"""LoggingSubscriber — logs every LifecycleEvent via the standard logging framework.

FEAT-176 — Lifecycle Events System.

``LoggingSubscriber`` is an ``EventProvider`` that subscribes to the
``LifecycleEvent`` base class (which receives every concrete subclass via
isinstance dispatch) and emits a compact single-line log record per event.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from parrot.core.events.lifecycle.base import LifecycleEvent

if TYPE_CHECKING:
    from parrot.core.events.lifecycle.registry import EventRegistry


class LoggingSubscriber:
    """EventProvider that logs every ``LifecycleEvent`` at a configurable level.

    Conforms to the ``EventProvider`` Protocol (TASK-1188) by exposing a
    synchronous ``register(registry)`` method.  One subscription to
    ``LifecycleEvent`` (the base class) is enough to capture every concrete
    subclass.

    Args:
        level: Python logging level (default ``logging.INFO``).
        logger_name: Name of the logger to write to (default ``"parrot.lifecycle"``).

    Example::

        from parrot.core.events.lifecycle.subscribers.logging import LoggingSubscriber

        registry.add_provider(LoggingSubscriber(level=logging.DEBUG))
    """

    def __init__(
        self,
        *,
        level: int = logging.INFO,
        logger_name: str = "parrot.lifecycle",
    ) -> None:
        self._level = level
        self._logger = logging.getLogger(logger_name)

    def register(self, registry: "EventRegistry") -> None:
        """Register one subscription that captures all LifecycleEvent subclasses.

        Args:
            registry: The ``EventRegistry`` to subscribe to.
        """
        registry.subscribe(LifecycleEvent, self._on_event)

    async def _on_event(self, event: LifecycleEvent) -> None:
        """Async callback invoked for every dispatched lifecycle event.

        Logs a single-line summary without calling ``event.to_dict()``
        (avoids the JSON-serialization overhead on hot paths such as
        ``ClientStreamChunkEvent``).

        Args:
            event: The lifecycle event to log.
        """
        trace_id = event.trace_context.trace_id if event.trace_context else "-"
        cls = type(event).__name__
        self._logger.log(
            self._level,
            "lifecycle %s source=%s/%s trace=%s",
            cls,
            event.source_type or "-",
            event.source_name or "-",
            trace_id,
        )
