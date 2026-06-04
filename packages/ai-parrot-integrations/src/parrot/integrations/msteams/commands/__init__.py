"""MS Teams command routing infrastructure (FEAT-225).

Provides ``MSTeamsCommandRouter``, which detects text commands in
``on_message_activity`` and dispatches them to registered handlers.

Usage::

    from parrot.integrations.msteams.commands import MSTeamsCommandRouter
    from parrot.integrations.msteams.commands.jira_commands import register_jira_commands

    router = MSTeamsCommandRouter()
    register_jira_commands(router, oauth_manager)

    # In on_message_activity:
    handled = await router.try_dispatch(text, turn_context)
    if handled:
        return  # skip agent processing
"""
from __future__ import annotations

import logging
from typing import Callable, Dict, TYPE_CHECKING

if TYPE_CHECKING:
    from botbuilder.core import TurnContext

logger = logging.getLogger(__name__)


class MSTeamsCommandRouter:
    """Detects and routes text commands in ``on_message_activity``.

    A *command* is a message whose first word starts with ``/``.  The router
    strips the leading slash, looks up the normalized name in the handler
    registry, and calls the matching handler.

    Non-command text (no leading ``/``) returns ``False`` without touching
    the registered handlers, so the caller can continue to normal agent
    processing.

    Example::

        router = MSTeamsCommandRouter()
        router.register("connect_jira", my_handler)

        handled = await router.try_dispatch("/connect_jira", turn_context)
        assert handled is True

    Attributes:
        _handlers: Mapping from normalized command name to handler callable.
    """

    def __init__(self) -> None:
        self._handlers: Dict[str, Callable] = {}

    def register(self, command: str, handler: Callable) -> None:
        """Register a handler for *command*.

        Args:
            command: The command name, with or without a leading ``/``
                (e.g. ``"connect_jira"`` or ``"/connect_jira"``).
            handler: An async callable with the signature
                ``async (turn_context: TurnContext) -> None``.
        """
        normalized = command.lstrip("/")
        if normalized in self._handlers:
            logger.warning(
                "MSTeamsCommandRouter: overwriting handler for '/%s'",
                normalized,
            )
        self._handlers[normalized] = handler
        logger.debug("Registered MS Teams command handler: /%s", normalized)

    async def try_dispatch(
        self, text: str, turn_context: "TurnContext"
    ) -> bool:
        """Attempt to dispatch *text* as a slash command.

        Args:
            text: The message text (already stripped of @mentions).
            turn_context: The current Bot Framework turn context.

        Returns:
            ``True`` if the text was recognized as a registered command and
            handled; ``False`` otherwise (caller should continue to agent).
        """
        if not text or not text.startswith("/"):
            return False

        parts = text.split(maxsplit=1)
        cmd = parts[0].lstrip("/")
        handler = self._handlers.get(cmd)
        if handler is None:
            return False

        try:
            await handler(turn_context)
        except Exception:
            logger.exception(
                "MSTeamsCommandRouter: error in handler for /%s", cmd
            )
            from botbuilder.schema import Activity
            await turn_context.send_activity(
                Activity(
                    type="message",
                    text="An error occurred processing your command. Please try again.",
                )
            )
        return True

    async def try_dispatch_plain(
        self, text: str, turn_context: "TurnContext"
    ) -> bool:
        """Attempt to dispatch *text* as a plain-text (non-slash) trigger.

        Used for discoverability keywords like ``"jira"`` or
        ``"integrations"`` that are registered without a ``/`` prefix
        (e.g. the ``"jira_menu"`` handler).  This method does **not** require
        the text to start with ``/``, so it acts as a secondary dispatch path
        called after :meth:`try_dispatch` returns ``False``.

        Args:
            text: The lowercase, stripped message text.
            turn_context: The current Bot Framework turn context.

        Returns:
            ``True`` if a matching plain-text handler was found and called;
            ``False`` otherwise.
        """
        if not text:
            return False

        handler = self._handlers.get(text)
        if handler is None:
            return False

        try:
            await handler(turn_context)
        except Exception:
            logger.exception(
                "MSTeamsCommandRouter: error in plain-text handler for '%s'", text
            )
            from botbuilder.schema import Activity
            await turn_context.send_activity(
                Activity(
                    type="message",
                    text="An error occurred processing your request. Please try again.",
                )
            )
        return True

    @property
    def registered_commands(self) -> list[str]:
        """Return the list of registered command names (without ``/``)."""
        return list(self._handlers.keys())
