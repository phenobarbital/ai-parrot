"""Studio assistant — conversational surface for the AgentStudio meta-agent
(FEAT-467 TASK-2521).

    POST   /api/v1/astudio/assistant  — session-scoped conversation
    DELETE /api/v1/astudio/assistant  — end the session instance

Session-scoped instance discipline mirrors the TASK-2517 testing surface
(``BotConfigTestHandler`` pattern): the ``AgentStudioAgent`` instance is
created once per caller session and reused across calls, keyed via the
session (not the ``BotManager`` — this agent is never registered into the
``AgentRegistry``, so instances live in a small per-app cache instead).
"""
from __future__ import annotations

import uuid
from typing import Any

from navigator_auth.decorators import is_authenticated, user_session
from parrot.bots.studio import AgentStudioAgent
from pydantic import BaseModel

from ._base import StudioBaseView
from .byok import resolve_user_api_key
from .models import StudioError

SESSION_KEY = "_studio_assistant"
#: Per-app cache of live AgentStudioAgent instances, keyed by the
#: generated instance name stashed in the caller's session. Not
#: registered with BotManager — this agent is standalone (spec §3
#: Module 13), so it needs its own small cache, mirroring
#: ``BotManager._bots``' in-memory discipline at a smaller scale.
_ASSISTANTS_APP_KEY = "_studio_assistant_instances"


class AssistantAskRequest(BaseModel):
    """``POST /astudio/assistant`` payload."""
    query: str
    use_byok: bool = True


@is_authenticated()
@user_session()
class StudioAssistantHandler(StudioBaseView):
    """``/api/v1/astudio/assistant`` — converse with the AgentStudio meta-agent."""

    def _error(self, message: str, *, status: int, code: str | None = None):
        return self.json_response(
            StudioError(message=message, code=code).model_dump(), status=status,
        )

    def _instances(self) -> dict[str, AgentStudioAgent]:
        return self.request.app.setdefault(_ASSISTANTS_APP_KEY, {})

    async def _get_or_create_assistant(
        self, session: Any, *, api_key: str | None
    ) -> AgentStudioAgent:
        """Return the reused assistant instance for this session, creating
        it once. Mirrors TASK-2517's ``_get_or_create_test_bot``."""
        instances = self._instances()
        instance_key = session.get(SESSION_KEY) if session is not None else None
        if instance_key:
            agent = instances.get(instance_key)
            if agent is not None:
                return agent
            # Session referenced an instance that expired/was cleaned up.

        agent = AgentStudioAgent(name=f"agent_studio_{uuid.uuid4().hex[:8]}", api_key=api_key)
        await agent.configure(self.request.app)
        instances[agent.name] = agent
        if session is not None:
            session[SESSION_KEY] = agent.name
        return agent

    # -- POST: converse -------------------------------------------------

    async def post(self):
        try:
            payload = await self.request.json()
        except Exception:  # pylint: disable=broad-except
            return self._error("Invalid JSON body.", status=400, code="invalid_json")

        try:
            ask_request = AssistantAskRequest(**(payload or {}))
        except Exception as exc:  # pylint: disable=broad-except
            return self._error(f"Invalid request: {exc}", status=400, code="invalid_request")

        user = await self._get_user()
        session = await self._resolve_session()

        api_key = None
        if ask_request.use_byok:
            api_key = await resolve_user_api_key(self.request.app, user.user_id, "anthropic")

        try:
            agent = await self._get_or_create_assistant(session, api_key=api_key)
        except Exception as exc:  # pylint: disable=broad-except
            self.logger.exception("Studio assistant: failed to build instance")
            return self._error(
                f"Failed to start the assistant: {exc}", status=500, code="build_failed"
            )

        try:
            self.request.session = session
            async with agent.session(request=self.request, app=self.request.app) as bot:
                response = await bot.ask(question=ask_request.query)
        except Exception as exc:  # pylint: disable=broad-except
            self.logger.exception("Studio assistant query failed")
            return self._error(f"Assistant query failed: {exc}", status=502, code="query_failed")

        content = str(response.content) if hasattr(response, "content") else str(response)
        metadata = getattr(response, "metadata", None) or {}

        return self.json_response({"response": content, "metadata": metadata})

    # -- DELETE: end session ----------------------------------------------

    async def delete(self):
        session = await self._resolve_session()
        instance_key = session.pop(SESSION_KEY, None) if session is not None else None

        if not instance_key:
            return self.json_response({"message": "No active assistant session"})

        instances = self._instances()
        instances.pop(instance_key, None)

        return self.json_response({"message": "Assistant session stopped"})
