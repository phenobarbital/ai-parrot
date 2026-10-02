"""Ask-request parsing/answering shared by the legacy and database test/ask paths."""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import ValidationError

from ..storage.models import StudioAgentKey
from ._models import TestAskRequest


class _StudioTestingAskMixin:
    """Ask plumbing of ``StudioTestingHandler``."""

    async def _ask_response(self, bot, agent_name: str, ask_request: TestAskRequest, **ctx: Any):
        """Apply BYOK, run one ask on ``bot`` and shape the JSON response (shared by both backends).

        ``ctx`` is bound into the request context of the ask (``studio_scope``, FEAT-605 C16).
        """
        if ask_request.use_byok:
            await self._maybe_apply_byok(bot)

        try:
            self.request.session = await self._resolve_session()
            async with bot.session(request=self.request, app=self.request.app, **ctx) as live_bot:
                response = await live_bot.ask(question=ask_request.query)
        except Exception as exc:  # pylint: disable=broad-except
            self.logger.exception("Studio test/ask failed for '%s'", agent_name)
            return self._error(f"Agent query failed: {exc}", status=502, code="query_failed")

        content = str(response.content) if hasattr(response, "content") else str(response)
        metadata = getattr(response, "metadata", None) or {}

        return self.json_response(
            {
                "agent_name": agent_name,
                "query": ask_request.query,
                "response": content,
                "metadata": metadata,
            }
        )

    async def _parse_ask(self):
        """``(TestAskRequest, None)`` or ``(None, 400 response)``."""
        try:
            payload = await self.request.json()
        except Exception:  # pylint: disable=broad-except
            return None, self._error("Invalid JSON body.", status=400, code="invalid_json")
        try:
            return TestAskRequest(**(payload or {})), None
        except ValidationError as exc:
            return None, self._error(f"Invalid request: {exc}", status=400, code="invalid_request")

    @staticmethod
    def _studio_session_id(session: Any, key: StudioAgentKey) -> str:
        """The caller's test session id for ``key`` (``studio_test:<qualified>``); created once when absent."""
        skey = f"studio_test:{key.qualified}"
        sid = session.get(skey) if session is not None else None
        if not sid:
            sid = uuid.uuid4().hex[:12]
            if session is not None:
                session[skey] = sid
        return sid
