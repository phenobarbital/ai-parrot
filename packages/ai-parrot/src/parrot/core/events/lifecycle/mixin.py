"""EventEmitterMixin — uniform self.events interface for AbstractBot, AbstractClient, AbstractTool.

FEAT-176 — Lifecycle Events System.

Mixin providing a per-instance ``EventRegistry`` accessible as ``self.events``.
The registry is lazily created on first access (fallback) or eagerly created when
``_init_events()`` is called from the host class ``__init__``.

By default, each instance's registry forwards events to the process-wide global
registry (see :mod:`parrot.core.events.lifecycle.global_registry`), enabling
cross-agent observability.  Opt out with ``forward_to_global=False``.
"""

from __future__ import annotations

import logging
from typing import Optional

from parrot.core.events.lifecycle.registry import EventRegistry

logger = logging.getLogger("parrot.core.events.lifecycle.mixin")


class EventEmitterMixin:
    """Mixin providing a uniform ``self.events: EventRegistry`` interface.

    Usage::

        class MyAgent(EventEmitterMixin, SomeBase):
            def __init__(self, **kwargs):
                super().__init__(**kwargs)
                self._init_events()   # call AFTER super().__init__()

    Subclasses MUST call :meth:`_init_events` from their ``__init__`` after
    their base class initialisation.  The mixin itself does NOT call
    ``super().__init__()`` to avoid disturbing the host class's MRO.

    If a host class accesses ``self.events`` without calling ``_init_events()``,
    a default registry is lazily created (forwards to global) so no
    ``AttributeError`` is raised.
    """

    _events_registry: Optional[EventRegistry]

    def _init_events(
        self,
        *,
        event_bus: Optional[object] = None,
        forward_to_global: bool = True,
    ) -> None:
        """Eagerly initialise the per-instance event registry.

        Args:
            event_bus: Optional ``EventBus`` instance for dual-emit subscribers.
            forward_to_global: When ``True`` (default), emitted events are
                also forwarded to the global registry.  Set ``False`` for
                isolated agents or test fixtures.
        """
        self._events_registry = EventRegistry(
            event_bus=event_bus,  # type: ignore[arg-type]
            forward_to_global=forward_to_global,
        )
        # Env-driven observability auto-boot (idempotent; near-zero cost when
        # disabled). Runs on the first bot/client/tool construction so the usage
        # recorder is registered on the global registry before any LLM call.
        # Guarded so a bootstrap failure can never break construction.
        try:
            from parrot.observability.bootstrap import (
                ensure_observability_bootstrapped,
            )

            ensure_observability_bootstrapped()
        except Exception:  # noqa: BLE001
            logger.debug("observability bootstrap skipped", exc_info=True)

    @property
    def events(self) -> EventRegistry:
        """The per-instance event registry.

        Lazily creates a default registry (forwards to global) if
        :meth:`_init_events` was never called.
        """
        reg = getattr(self, "_events_registry", None)
        if reg is None:
            # Defensive fallback: caller forgot to invoke _init_events.
            # Forward to global so observability still works.
            logger.debug(
                "%s accessed self.events without calling _init_events; "
                "creating default EventRegistry.",
                type(self).__name__,
            )
            self._events_registry = EventRegistry(forward_to_global=True)
            reg = self._events_registry
        return reg
