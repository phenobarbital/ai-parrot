"""_LegacyEventBridge — routes new typed events back to legacy _listeners callbacks.

FEAT-176 — Lifecycle Events System.

AbstractBot's legacy API (``add_event_listener`` / ``_trigger_event``) is preserved
by registering a ``_LegacyEventBridge`` subscriber during ``__init__``.  When
an ``AgentStatusChangedEvent`` is dispatched on the bot's ``EventRegistry``, the
bridge invokes every callback stored in ``self._listeners[EVENT_STATUS_CHANGED]``.

This ensures that code written against the legacy string-keyed event system
continues to work unchanged, while new code can subscribe to typed events directly.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from parrot.core.events.lifecycle.events import AgentStatusChangedEvent

if TYPE_CHECKING:
    from navigator_eventbus.lifecycle.registry import EventRegistry

logger = logging.getLogger("parrot.lifecycle.legacy_bridge")


class _LegacyEventBridge:
    """EventProvider that routes typed ``AgentStatusChangedEvent`` back to
    legacy ``_listeners`` callbacks.

    Registered once per bot instance in ``AbstractBot.__init__`` after the
    mixin is initialised.  All existing ``add_event_listener`` users will
    continue to receive notifications with the same ``old=`` / ``new=``
    keyword arguments as before.

    Note:
        Callbacks are invoked with keyword arguments ``old`` (str, enum name)
        and ``new`` (str, enum name).  This differs from the legacy
        ``_trigger_event`` signature which passed ``AgentStatus`` enum
        instances.  Update any listener that compares e.g.
        ``new_status == AgentStatus.WORKING`` to
        ``new_status == AgentStatus.WORKING.name`` or
        ``new_status == "WORKING"``.

        Both sync and async callbacks are supported.  Async callbacks are
        awaited directly within the bridge's ``async def _on_status`` handler.

    Args:
        bot: The ``AbstractBot`` instance whose ``_listeners`` dict is
            consulted for ``EVENT_STATUS_CHANGED`` callbacks.
    """

    def __init__(self, bot: Any) -> None:
        self._bot = bot

    # ------------------------------------------------------------------
    # EventProvider
    # ------------------------------------------------------------------

    def register(self, registry: "EventRegistry") -> None:
        """Subscribe to ``AgentStatusChangedEvent`` on *registry*.

        Args:
            registry: The ``EventRegistry`` to subscribe to.
        """
        registry.subscribe(AgentStatusChangedEvent, self._on_status)

    # ------------------------------------------------------------------
    # Private
    # ------------------------------------------------------------------

    async def _on_status(self, event: AgentStatusChangedEvent) -> None:
        """Invoke every legacy ``EVENT_STATUS_CHANGED`` callback.

        Callbacks are invoked with ``old=<old_status>`` (str, enum name) and
        ``new=<new_status>`` (str, enum name) keyword arguments.  Both sync
        and async callbacks are supported.

        Args:
            event: The ``AgentStatusChangedEvent`` that was dispatched.
        """
        for cb in self._bot._listeners.get(
            self._bot.EVENT_STATUS_CHANGED, []
        ):
            try:
                if asyncio.iscoroutinefunction(cb):
                    await cb(old=event.old_status, new=event.new_status)
                else:
                    cb(old=event.old_status, new=event.new_status)
            except Exception as exc:
                logger.warning(
                    "Legacy EVENT_STATUS_CHANGED listener raised: %s", exc
                )
