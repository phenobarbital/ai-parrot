"""Database-mode test paths as a mixin."""

from __future__ import annotations


from parrot.clients.factory import LLMFactory

from ..access import _store_record, build_tool_scope
from ..conversation import delete_studio_conversation
from ..key_source import KeySourceRefusal, choose_key_source
from ..storage.models import StudioAgentKey, StudioNotFound, StudioStorageUnavailable
from ._models import TestAskRequest


class _StudioTestingDbMixin:
    """Database-mode test/ask and test-session delete of ``StudioTestingHandler``."""

    async def _db_post(self, storage, part):
        """Studio row → the ask runs inside ``manager.studio.use()`` (lease held for the whole ask, §2.8/§2.7a)."""
        agent_name = self.request.match_info.get("name")
        rec = await storage.services.agents.get(part, agent_name) if agent_name else None
        if rec is None and part.tenant is None:
            return await self._legacy_post()
        if not agent_name:
            return self._error("Agent name is required.", status=400, code="missing_name")
        if rec is None or not (await self._access()).can_see(_store_record("agent", rec.agent_id, rec)):
            return self._not_found("agent", agent_name)  # access first: an invisible agent never reaches a 400
        ask_request, bad = await self._parse_ask()
        if bad is not None:
            return bad
        ctx = await self._ask_context(rec)
        return await self._ask_studio(StudioAgentKey(part.tenant, agent_name), agent_name, ask_request, ctx)

    async def _ask_context(self, rec) -> dict:
        """``{"studio_scope": …}`` for an opted-in host (caller scope + the addressed agent); ``{}`` otherwise (C16)."""
        if not self._opted_in():
            return {}
        access = await self._access()
        record = _store_record("agent", rec.agent_id, rec)
        return {"studio_scope": build_tool_scope(await self._scope(), access.agent_ref(record))}

    async def _ask_studio(self, key: StudioAgentKey, agent_name: str, ask_request: TestAskRequest, ctx: dict):
        """Run one ask on the caller's session instance of ``key`` (a lease is held for the whole ask)."""
        manager = self._manager()
        if manager is None or manager.studio is None:
            raise StudioStorageUnavailable("studio runtime is not installed")
        sid = self._studio_session_id(await self._resolve_session(), key)
        try:
            async with manager.studio.use(key, session_id=sid, request=self.request) as bot:
                return await self._ask_response(bot, agent_name, ask_request, session_id=sid, **ctx)
        except StudioNotFound:
            return self._not_found("agent", agent_name)
        except PermissionError as exc:  # AgentAccessDenied (PBAC deny, raised before any build)
            return self._error(str(exc), status=403, code="access_denied")

    async def _maybe_apply_byok(self, bot, ask_request) -> bool:
        """Swap ``bot.llm`` for a BYOK-keyed client when the chosen key source is the caller's own key.

        No-op when the bot's LLM was not configured from a plain
        ``"provider:model"`` string, or when the server key is the source. The source is
        :func:`~parrot.handlers.studio.key_source.choose_key_source`'s call (PA-2): one available source is used,
        both require ``key_source`` (``409``), a missing explicit one is ``422``. Never catches an auth failure
        and retries with the server default (spec §7) — a swapped-in client that fails auth on the subsequent
        ``ask()`` call surfaces as a query error.

        Args:
            bot: The (session-scoped) test bot instance.
            ask_request: The parsed ask (``use_byok``, ``key_source``).

        Returns:
            ``True`` when a stored personal key replaced ``bot.llm`` for this ask.

        Raises:
            KeySourceRefusal: ``409 key_source_required`` / ``422 key_source_unavailable``.
        """
        llm_raw = getattr(bot, "_llm_raw", None)
        if not isinstance(llm_raw, str) and ask_request.key_source == "byok":
            # an explicit personal key is honoured or refused, never silently served by the server key (PA-2)
            raise KeySourceRefusal(
                422, "key_source_unavailable", "A personal key cannot be applied to this agent's LLM configuration.",
                {"requested": "byok"},
            )
        if not isinstance(llm_raw, str) or (not ask_request.use_byok and ask_request.key_source is None):
            return False
        provider, _model = LLMFactory.parse_llm_string(llm_raw)
        user = await self._get_user()
        # read from the package at call time: tests patch ``studio.testing.resolve_user_api_key``
        from parrot.handlers.studio import testing as _testing_pkg

        api_key = await _testing_pkg.resolve_user_api_key(self.request.app, user.user_id, provider)
        source = choose_key_source(
            provider, has_byok=bool(api_key), requested=ask_request.key_source, use_byok=ask_request.use_byok
        )
        if source != "byok":
            return False
        bot.llm = LLMFactory.create(llm_raw, tool_manager=bot.tool_manager, api_key=api_key)
        return True

    async def _invisible_agent(self, storage, part, name):
        """The one 404 when the Studio agent is absent or invisible to the caller; ``None`` when it is visible."""
        rec = await storage.services.agents.get(part, name) if name else None
        record = _store_record("agent", rec.agent_id, rec) if rec else None
        return await self._check_record_access(await self._access(), record, "agent", name or "")

    async def _db_delete(self, storage, part):
        """Pop the Studio session id and retire that session entry; no Studio session → the legacy teardown."""
        agent_name = self.request.match_info.get("name")
        if part.tenant is not None and (refused := await self._invisible_agent(storage, part, agent_name)) is not None:
            return refused  # 404 before the session entry is touched
        session = await self._resolve_session()
        key = StudioAgentKey(part.tenant, agent_name) if agent_name else None
        sid = session.pop(f"studio_test:{key.qualified}", None) if key and session is not None else None
        if not sid:
            if part.tenant is None:
                return await self._legacy_delete()
            return self.json_response({"message": f"No active test session for '{agent_name}'"}, status=200)
        if (runtime := getattr(self._manager(), "studio", None)) is not None:
            runtime.evict_session(key, sid)
        rec = await storage.services.agents.get(part, agent_name)
        if rec is not None:  # a shared (redis) history outlives the evicted instance: ending the session deletes it
            await delete_studio_conversation((await self._get_user()).user_id, sid, str(rec.agent_id))
        return self.json_response({"message": f"Test session for '{agent_name}' stopped", "agent_name": agent_name})
