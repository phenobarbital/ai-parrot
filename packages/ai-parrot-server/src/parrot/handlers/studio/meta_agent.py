"""Studio assistant — conversational surface for the AgentStudio meta-agent
(FEAT-467 TASK-2521).

    POST   /api/v1/astudio/assistant  — session-scoped conversation
    DELETE /api/v1/astudio/assistant  — end the session instance

Session-scoped instance discipline mirrors the TASK-2517 testing surface
(``BotConfigTestHandler`` pattern): the ``AgentStudioAgent`` instance is
created once per caller session and reused across calls, keyed via the
session (not the ``BotManager`` — this agent is never registered into the
``AgentRegistry``, so instances live in a small per-app cache instead).

FEAT-605 W3.6 (C30): the session entry, the instance cache, the toolset, the
conversational identity (``chatbot_id``) and the ``user_id`` / ``session_id``
handed to ``ask`` are all partitioned by ``(tenant, user)``; a caller switching
tenants inside one login never reaches the other tenant's instance or history.
"""

from __future__ import annotations

import contextlib
import json
import logging
import uuid
from collections.abc import AsyncIterator
from typing import Any, NamedTuple

from aiohttp import web
from navigator_auth.decorators import is_authenticated, user_session
from parrot.bots.studio import AgentStudioAgent
from pydantic import BaseModel

from ._base import StudioBaseView
from .access import StudioTenantRequired, build_tool_scope
from .byok import resolve_user_api_key
from .models import StudioError

SESSION_KEY = "_studio_assistant"
#: Per-app cache of live AgentStudioAgent instances, keyed by the
#: generated instance name stashed in the caller's session. Not
#: registered with BotManager — this agent is standalone (spec §3
#: Module 13), so it needs its own small cache, mirroring
#: ``BotManager._bots``' in-memory discipline at a smaller scale.
_ASSISTANTS_APP_KEY = "_studio_assistant_instances"
_logger = logging.getLogger("Parrot.AgentStudio.Assistant")


class Partition(NamedTuple):
    """The assistant partition: compared as a tuple, never as a joined string (no ``:`` / ``-`` collisions).

    ``tenant`` is ``None`` only on a host with no scope resolver (a real tenant may be called ``"-"``).
    """

    tenant: str | None
    user_id: str

    @property
    def key(self) -> str:
        """The session-mapping key: an unambiguous JSON encoding of the pair."""
        return json.dumps([self.tenant, self.user_id])

    @property
    def chatbot_id(self) -> str:
        """Tenant-qualified conversational identity of the instance (``agent_studio:<tenant|->``)."""
        return f"agent_studio:{self.tenant or '-'}"


_ANONYMOUS = Partition(None, "anonymous")


def _assistant_partition(scope: Any, user: Any) -> Partition:
    """The assistant partition ``(tenant, user_id)`` of a resolved scope and user (FEAT-605 C30)."""
    return Partition(scope.tenant, str(user.user_id))


async def _cleanup_once(agent: Any) -> None:
    """Await ``agent.cleanup()`` at most once per instance; a failure is logged, never raised."""
    if getattr(agent, "_assistant_cleaned", False):
        return
    agent._assistant_cleaned = True
    cleanup = getattr(agent, "cleanup", None)
    if cleanup is None:
        return
    try:
        await cleanup()
    except Exception as exc:  # pylint: disable=broad-except
        _logger.warning("Studio assistant: cleanup of %s failed: %s", getattr(agent, "name", "?"), exc)


async def _retire(agent: Any) -> None:
    """Clean a removed instance now, or — while a POST on it is in flight — when its last ask finishes."""
    if getattr(agent, "_assistant_leases", 0) > 0:
        agent._assistant_retired = True
        return
    await _cleanup_once(agent)


@contextlib.asynccontextmanager
async def _leased(agent: Any) -> AsyncIterator[Any]:
    """Hold ``agent`` for one ask: a DELETE / app cleanup that retires it meanwhile is deferred until the ask ends."""
    agent._assistant_leases = getattr(agent, "_assistant_leases", 0) + 1
    try:
        yield agent
    finally:
        agent._assistant_leases -= 1
        if agent._assistant_leases == 0 and getattr(agent, "_assistant_retired", False):
            await _cleanup_once(agent)


async def cleanup_studio_assistants(app: Any) -> None:
    """``on_cleanup`` hook: clean every cached assistant instance exactly once (every host mode)."""
    instances = app.get(_ASSISTANTS_APP_KEY) or {}
    for key in list(instances):
        await _retire(instances.pop(key, None))


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
            StudioError(message=message, code=code).model_dump(),
            status=status,
        )

    def _instances(self) -> dict[tuple, AgentStudioAgent]:
        """The app-level cache, keyed by ``(tenant, user_id, instance_name)``."""
        return self.request.app.setdefault(_ASSISTANTS_APP_KEY, {})

    async def _identity(self) -> Partition:
        """The caller's :class:`Partition`.

        Raises:
            StudioTenantRequired: an opted-in host whose resolved scope has no tenant (answered 422 before any
                instance is touched).
        """
        user = await self._get_user()
        scope = await self._scope()
        if self._opted_in() and scope.tenant is None:
            raise StudioTenantRequired
        return _assistant_partition(scope, user)

    @staticmethod
    def _partition_entries(session: Any) -> dict:
        """The session's partition mapping; anything that is not a mapping (tampered / legacy) is empty."""
        raw = session.get(SESSION_KEY) if session is not None else None
        return raw if isinstance(raw, dict) else {}

    def _partition_entry(self, session: Any, partition: Partition) -> dict | None:
        """``{"instance", "session_id"}`` of THIS partition, or ``None`` (another partition's entry is never read)."""
        entry = self._partition_entries(session).get(partition.key)
        ok = isinstance(entry, dict) and isinstance(entry.get("instance"), str) and isinstance(entry.get("session_id"), str)
        return entry if ok else None

    async def _declarative_only(self) -> bool:
        """Database mode: the toolset follows the partition's Python-draft policy (tenant ⇒ declarative only)."""
        storage = self.request.app.get("studio_storage")
        if storage is None or storage.backend != "database":
            return False
        return not storage.services.drafts.python_drafts_allowed(await self._studio_partition())

    async def _get_or_create_assistant(
        self, session: Any, *, api_key: str | None, identity: Partition | None = None
    ) -> AgentStudioAgent:
        """Return this partition's assistant instance, creating it once (the toolset is built per instance).

        A cached instance whose recorded partition differs from the request's is a miss (a tampered or shared
        session cannot reach another partition's instance). The instance gets an explicit tenant-qualified
        ``chatbot_id`` so its conversation memory key is partitioned too.
        """
        partition = identity or _ANONYMOUS
        entry = self._partition_entry(session, partition)
        if entry is not None:
            agent = self._instances().get((*partition, entry["instance"]))
            if agent is not None and getattr(agent, "_assistant_partition", None) == partition:
                return agent
            # the entry named an instance that expired / belongs to another partition: rebuild below

        agent = AgentStudioAgent(
            name=f"agent_studio_{uuid.uuid4().hex[:8]}", api_key=api_key,
            declarative_only=await self._declarative_only(), chatbot_id=partition.chatbot_id,
        )
        await agent.configure(self.request.app)
        agent._assistant_partition = partition
        self._instances()[(*partition, agent.name)] = agent
        if session is not None:
            session[SESSION_KEY] = {
                **self._partition_entries(session),
                partition.key: {"instance": agent.name, "session_id": uuid.uuid4().hex},
            }
        return agent

    # -- POST: converse -------------------------------------------------

    async def _parse_ask(self):
        """The :class:`AssistantAskRequest`, or the 400 response."""
        try:
            payload = await self.request.json()
        except Exception:  # pylint: disable=broad-except
            return self._error("Invalid JSON body.", status=400, code="invalid_json")
        try:
            return AssistantAskRequest(**(payload or {}))
        except Exception as exc:  # pylint: disable=broad-except
            return self._error(f"Invalid request: {exc}", status=400, code="invalid_request")

    async def _session_context(self) -> dict:
        """``{"studio_scope": …}`` (agent=None) for an opted-in host; ``{}`` otherwise."""
        return {"studio_scope": build_tool_scope(await self._scope())} if self._opted_in() else {}

    async def _ask(self, agent, partition: Partition, session: Any, question: str):
        """One ask on a leased ``agent`` (a concurrent DELETE cannot clean it up mid-ask); the JSON response."""
        user = await self._get_user()
        conversation = (self._partition_entry(session, partition) or {}).get("session_id") or uuid.uuid4().hex
        try:
            self.request.session = session
            # user_id is REQUIRED by the meta-agent's mutating tools: they stamp/enforce ownership from the context
            ctx = await self._session_context()
            async with _leased(agent), agent.session(
                request=self.request, app=self.request.app, user_id=user.user_id, **ctx
            ) as bot:
                # explicit identity: the memory key (chatbot, user, session) is partitioned by tenant and user
                response = await bot.ask(question=question, user_id=user.user_id, session_id=conversation)
        except Exception as exc:  # pylint: disable=broad-except
            self.logger.exception("Studio assistant query failed")
            return self._error(f"Assistant query failed: {exc}", status=502, code="query_failed")
        content = str(response.content) if hasattr(response, "content") else str(response)
        return self.json_response({"response": content, "metadata": getattr(response, "metadata", None) or {}})

    async def post(self):
        # PBAC (adversarial-review fix: gate was defined but never called).
        if (denied := await self._pbac_gate("assistant", "astudio:assistant:ask")) is not None:
            return denied
        try:
            partition = await self._identity()   # before ANY instance is touched
        except StudioTenantRequired:
            return self._tenant_required()
        ask_request = await self._parse_ask()
        if isinstance(ask_request, web.Response):
            return ask_request
        user, session = await self._get_user(), await self._resolve_session()
        api_key = None
        if ask_request.use_byok:
            api_key = await resolve_user_api_key(self.request.app, user.user_id, "anthropic")
        try:
            agent = await self._get_or_create_assistant(session, api_key=api_key, identity=partition)
        except Exception as exc:  # pylint: disable=broad-except
            self.logger.exception("Studio assistant: failed to build instance")
            return self._error(f"Failed to start the assistant: {exc}", status=500, code="build_failed")
        return await self._ask(agent, partition, session, ask_request.query)

    # -- DELETE: end session ----------------------------------------------

    async def delete(self):
        """Reset ONLY the caller's partition: pop its entry and retire that instance (cleaned once, after any ask)."""
        try:
            partition = await self._identity()
        except StudioTenantRequired:
            return self._tenant_required()
        session = await self._resolve_session()
        entry = self._partition_entry(session, partition)
        if entry is None:
            return self.json_response({"message": "No active assistant session"})

        remaining = {k: v for k, v in self._partition_entries(session).items() if k != partition.key}
        if remaining:
            session[SESSION_KEY] = remaining
        else:
            session.pop(SESSION_KEY, None)
        agent = self._instances().pop((*partition, entry["instance"]), None)
        if agent is not None:
            await _retire(agent)

        return self.json_response({"message": "Assistant session stopped"})
