"""Database-mode test paths as a mixin."""

from __future__ import annotations


from parrot.clients.factory import LLMFactory

from ..access import _store_record
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
        return await self._ask_studio(StudioAgentKey(part.tenant, agent_name), agent_name, ask_request)

    async def _ask_studio(self, key: StudioAgentKey, agent_name: str, ask_request: TestAskRequest):
        """Run one ask on the caller's session instance of ``key`` (a lease is held for the whole ask)."""
        manager = self._manager()
        if manager is None or manager.studio is None:
            raise StudioStorageUnavailable("studio runtime is not installed")
        sid = self._studio_session_id(await self._resolve_session(), key)
        try:
            async with manager.studio.use(key, session_id=sid, request=self.request) as bot:
                return await self._ask_response(bot, agent_name, ask_request)
        except StudioNotFound:
            return self._not_found("agent", agent_name)
        except PermissionError as exc:   # AgentAccessDenied (PBAC deny, raised before any build)
            return self._error(str(exc), status=403, code="access_denied")

    async def _maybe_apply_byok(self, bot) -> None:
        """Swap ``bot.llm`` for a BYOK-keyed client, when a key is stored.

        No-op when the bot's LLM was not configured from a plain
        ``"provider:model"`` string, or when the caller has no stored key
        for that provider. Never catches an auth failure and retries with
        the server default (spec §7) — a swapped-in client that fails
        auth on the subsequent ``ask()`` call surfaces as a query error.

        Args:
            bot: The (session-scoped) test bot instance.
        """
        llm_raw = getattr(bot, "_llm_raw", None)
        if not isinstance(llm_raw, str):
            return
        provider, _model = LLMFactory.parse_llm_string(llm_raw)
        user = await self._get_user()
        # read from the package at call time: tests patch ``studio.testing.resolve_user_api_key``
        from parrot.handlers.studio import testing as _testing_pkg

        api_key = await _testing_pkg.resolve_user_api_key(self.request.app, user.user_id, provider)
        if not api_key:
            return
        bot.llm = LLMFactory.create(llm_raw, tool_manager=bot.tool_manager, api_key=api_key)

    async def _db_delete(self, storage, part):
        """Pop the Studio session id and retire that session entry; no Studio session → the legacy teardown."""
        agent_name = self.request.match_info.get("name")
        session = await self._resolve_session()
        key = StudioAgentKey(part.tenant, agent_name) if agent_name else None
        sid = session.pop(f"studio_test:{key.qualified}", None) if key and session is not None else None
        if not sid:
            if part.tenant is None:
                return await self._legacy_delete()
            return self.json_response({"message": f"No active test session for '{agent_name}'"}, status=200)
        if (runtime := getattr(self._manager(), "studio", None)) is not None:
            runtime.evict_session(key, sid)
        return self.json_response(
            {"message": f"Test session for '{agent_name}' stopped", "agent_name": agent_name}
        )
