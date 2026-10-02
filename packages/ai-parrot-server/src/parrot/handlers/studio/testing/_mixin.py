"""Shared helpers of the testing views (``_StudioTestingMixin``)."""

from __future__ import annotations

import uuid
from typing import Any


from ..models import StudioError
from ._models import SESSION_PREFIX


class _StudioTestingMixin:
    """Shared helpers for the testing-surface views in this module."""

    def _manager(self):
        """Return the ``BotManager`` instance, or ``None`` if unavailable."""
        return self.request.app.get("bot_manager")

    def _error(self, message: str, *, status: int, code: str | None = None, details: dict | None = None):
        """Return a JSON error response shaped like :class:`StudioError`."""
        return self.json_response(
            StudioError(message=message, code=code, details=details).model_dump(),
            status=status,
        )

    def _session_key(self, agent_name: str) -> str:
        """Session key for the Studio test instance (namespaced — TASK-2517)."""
        return f"{SESSION_PREFIX}{agent_name}"

    async def _get_or_create_test_bot(self, agent_name: str, session: Any):
        """Return the reused test bot for ``(session, agent_name)``, creating it once.

        Mirrors ``BotConfigTestHandler._create_agent``/session discipline
        (``handlers/testing_handler.py:54-72``).

        Args:
            agent_name: The base agent name to clone a test instance from.
            session: The resolved caller session (dict-like).

        Returns:
            The (possibly newly created) test bot instance.

        Raises:
            LookupError: ``agent_name`` is not a known agent.
            RuntimeError: ``BotManager`` is not installed.
        """
        manager = self._manager()
        if not manager:
            raise RuntimeError("BotManager is not installed.")

        key = self._session_key(agent_name)
        bot_name = session.get(key) if session is not None else None
        if bot_name:
            bot = manager._bots.get(bot_name)
            if bot is not None:
                return bot
            # Session referenced a bot that expired/was cleaned up — recreate.

        session_id = uuid.uuid4().hex[:12]
        # request= is REQUIRED for PBAC (adversarial-review fix): per
        # BotManager.get_bot's contract, request=None means "programmatic
        # invocation — no PBAC check", which let any authenticated Studio
        # user spin up a test instance of a PBAC-denied agent.
        bot = await manager.get_bot(agent_name, new=True, session_id=session_id, request=self.request)
        if not bot:
            raise LookupError(f"Agent '{agent_name}' not found in registry.")
        if session is not None:
            session[key] = bot.name
        return bot
