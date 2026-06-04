"""Slack command routing infrastructure (FEAT-225).

Provides ``SlackCommandRouter``, a simple registry that decouples slash-command
dispatch from ``SlackAgentWrapper`` and ``SlackSocketHandler``.

Usage::

    from parrot.integrations.slack.commands import SlackCommandRouter
    from parrot.integrations.slack.commands.jira_commands import register_jira_commands

    router = SlackCommandRouter()
    register_jira_commands(router, oauth_manager)

    # In the command handler:
    result = await router.dispatch("connect_jira", payload)
    if result is not None:
        return web.json_response(result)
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)


class SlackCommandRouter:
    """Routes slash commands to registered async handler functions.

    Each command is registered under a normalized name (the text that
    follows the slash, without the ``/`` prefix, e.g. ``"connect_jira"``).
    ``dispatch`` looks up the handler and calls it with the slash-command
    payload dict.  If no handler is registered for the command, it returns
    ``None`` so the caller can fall through to the next handler.

    Example::

        router = SlackCommandRouter()
        router.register("ping", my_ping_handler)
        result = await router.dispatch("ping", payload)
        # result is the return value of my_ping_handler, or None

    Attributes:
        _handlers: Mapping from normalized command name to handler callable.
    """

    def __init__(self) -> None:
        self._handlers: Dict[str, Callable] = {}

    def register(self, command: str, handler: Callable) -> None:
        """Register a handler for *command*.

        Args:
            command: The slash-command name, with or without a leading ``/``
                (e.g. ``"connect_jira"`` or ``"/connect_jira"``).
            handler: An async callable with the signature
                ``async (payload: dict) -> dict | None``.
        """
        normalized = command.lstrip("/")
        if normalized in self._handlers:
            logger.warning(
                "SlackCommandRouter: overwriting handler for '/%s'",
                normalized,
            )
        self._handlers[normalized] = handler
        logger.debug("Registered Slack command handler: /%s", normalized)

    async def dispatch(
        self, command: str, payload: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Dispatch *command* to its registered handler.

        Args:
            command: The slash-command name (with or without ``/``).
            payload: The Slack slash-command POST data as a dict.

        Returns:
            The handler's return value (typically an ephemeral response dict),
            or ``None`` if no handler is registered for *command*.
        """
        normalized = command.lstrip("/")
        handler = self._handlers.get(normalized)
        if handler is None:
            return None
        try:
            return await handler(payload)
        except Exception:
            logger.exception(
                "SlackCommandRouter: error in handler for /%s", normalized
            )
            return {
                "response_type": "ephemeral",
                "text": "An error occurred processing your command. Please try again.",
            }

    @property
    def registered_commands(self) -> list[str]:
        """Return the list of registered command names (without ``/``)."""
        return list(self._handlers.keys())
