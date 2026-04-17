"""Telegram-aware HumanTool.

Resolves the ``HumanInteractionManager`` lazily from the process-wide
default (set at integration startup) and auto-fills ``target_humans``
from the current Telegram chat id stored in a ContextVar by
:class:`TelegramAgentWrapper`.

This lets agents declare a ``HumanTool`` inside ``agent_tools()`` —
before the integration layer has had a chance to wire the HITL manager —
and still have the right manager + recipient resolved at invocation time.
"""
from __future__ import annotations

from typing import Any, List, Optional

from ...human import HumanTool, get_default_human_manager
from .context import get_current_telegram_chat_id


class TelegramHumanTool(HumanTool):
    """A :class:`HumanTool` that auto-resolves manager + target from Telegram context.

    Resolution order for the manager:
        1. ``self.manager`` if provided at construction.
        2. ``get_default_human_manager()`` (set by IntegrationBotManager).

    Resolution order for ``target_humans`` on each invocation:
        1. Explicit ``target_humans`` from the LLM call.
        2. ``self.default_targets`` from construction.
        3. The current Telegram chat id (ContextVar set by the wrapper).
    """

    def __init__(
        self,
        *,
        default_channel: Optional[str] = None,
        default_targets: Optional[List[str]] = None,
        source_agent: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        # default_channel stays None here; we resolve it at invocation time
        # (picks the first registered telegram channel if None).
        super().__init__(
            manager=None,
            default_channel=default_channel or "telegram",
            default_targets=default_targets or [],
            source_agent=source_agent,
            **kwargs,
        )

    async def _execute(self, **kwargs: Any) -> Any:
        # Lazy-resolve the manager
        if self.manager is None:
            self.manager = get_default_human_manager()

        if self.manager is None:
            return (
                "HumanTool error: no HumanInteractionManager configured "
                "(Telegram integration may not be running)."
            )

        # Pick a concrete channel name if the default doesn't exist yet.
        # The manager registers channels under the Telegram bot name —
        # fall back to the first one if "telegram" isn't present.
        if self.default_channel not in self.manager.channels:
            if self.manager.channels:
                self.default_channel = next(iter(self.manager.channels))

        # Auto-fill target_humans from the current Telegram chat id
        # when neither the LLM call nor the tool defaults supplied one.
        if not kwargs.get("target_humans") and not self.default_targets:
            chat_id = get_current_telegram_chat_id()
            if chat_id:
                kwargs["target_humans"] = [chat_id]

        return await super()._execute(**kwargs)
