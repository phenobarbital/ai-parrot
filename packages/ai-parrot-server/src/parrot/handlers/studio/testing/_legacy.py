"""Filesystem-mode (legacy) test paths — the verbatim ``_legacy_*`` bodies, as a mixin."""

from __future__ import annotations


from pydantic import ValidationError

from ._models import TestAskRequest


class _StudioTestingLegacyMixin:
    """Legacy test/ask and test-session delete of ``StudioTestingHandler``."""

    async def _legacy_post(self):
        # PBAC (adversarial-review fix: gate was defined but never called).
        if (denied := await self._pbac_gate("testing", "astudio:testing:ask")) is not None:
            return denied

        agent_name = self.request.match_info.get("name")
        if not agent_name:
            return self._error("Agent name is required.", status=400, code="missing_name")

        try:
            payload = await self.request.json()
        except Exception:  # pylint: disable=broad-except
            return self._error("Invalid JSON body.", status=400, code="invalid_json")

        try:
            ask_request = TestAskRequest(**(payload or {}))
        except ValidationError as exc:
            return self._error(f"Invalid request: {exc}", status=400, code="invalid_request")

        session = await self._resolve_session()
        try:
            bot = await self._get_or_create_test_bot(agent_name, session)
        except LookupError as exc:
            return self._error(str(exc), status=404, code="not_found")
        except PermissionError as exc:
            # AgentAccessDenied (PBAC deny from get_bot's enforce_agent_access).
            return self._error(str(exc), status=403, code="access_denied")
        except RuntimeError as exc:
            return self._error(str(exc), status=503, code="unavailable")

        return await self._ask_response(bot, agent_name, ask_request)

    async def _legacy_delete(self):
        agent_name = self.request.match_info.get("name")
        if not agent_name:
            return self._error("Agent name is required.", status=400, code="missing_name")

        session = await self._resolve_session()
        key = self._session_key(agent_name)
        bot_name = session.pop(key, None) if session is not None else None

        if not bot_name:
            return self.json_response({"message": f"No active test session for '{agent_name}'"}, status=200)

        manager = self._manager()
        if manager is not None:
            try:
                manager.remove_bot(bot_name)
            except KeyError:
                self.logger.warning("Studio: test bot '%s' already removed", bot_name)

        return self.json_response(
            {
                "message": f"Test session for '{agent_name}' stopped",
                "agent_name": agent_name,
            }
        )
