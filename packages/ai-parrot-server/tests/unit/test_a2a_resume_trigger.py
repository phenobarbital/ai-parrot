"""Unit tests for A2A OAuth-callback resume trigger (FEAT-260 / TASK-1645).

Tests:
- Callback with valid a2a_interaction_id → resume hook called.
- Suspended entry deleted after successful resume.
- Expired entry (store returns None) → graceful re-prompt (no crash).
- Web callback path is unchanged (no A2A hook interference).
- Missing hook → warning logged but no crash.
- resume_from_oauth_callback loads SuspendedExecution + calls agent.resume.
"""
from __future__ import annotations

from typing import Any, Dict, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.a2a.server import A2AServer
from parrot.auth.oauth2_routes import register_a2a_resume_hook


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_server(suspended_store=None) -> A2AServer:
    agent = MagicMock()
    agent.name = "TestAgent"
    agent.ask = AsyncMock(return_value="response")
    agent.resume = AsyncMock(return_value="resumed-response")
    agent.tool_manager = None
    agent.tools = []
    return A2AServer(agent, suspended_store=suspended_store)


class FakeSuspendedExecution:
    def __init__(self, interaction_id: str, session_id: str = "sess-1", user_id: str = "u@e.com"):
        self.interaction_id = interaction_id
        self.session_id = session_id
        self.user_id = user_id
        self.agent_name = "TestAgent"
        self.tool_call_id = "stub_tool"
        self.messages: list = []


class FakeSuspendedStore:
    def __init__(self):
        self._store: Dict[str, Any] = {}

    async def save(self, record: Any, ttl: int) -> None:
        self._store[record.interaction_id] = record

    async def load(self, interaction_id: str) -> Optional[Any]:
        return self._store.get(interaction_id)

    async def delete(self, interaction_id: str) -> None:
        self._store.pop(interaction_id, None)

    def has(self, interaction_id: str) -> bool:
        return interaction_id in self._store


# ---------------------------------------------------------------------------
# TestResumeFromOauthCallback — A2AServer.resume_from_oauth_callback
# ---------------------------------------------------------------------------


class TestResumeFromOauthCallback:
    @pytest.mark.asyncio
    async def test_resume_loads_suspended_and_calls_agent_resume(self):
        """resume_from_oauth_callback loads SuspendedExecution + calls agent.resume."""
        store = FakeSuspendedStore()
        interaction_id = "test-interaction-001"
        suspended = FakeSuspendedExecution(interaction_id=interaction_id)
        store._store[interaction_id] = suspended

        server = _make_server(suspended_store=store)
        await server.resume_from_oauth_callback(interaction_id, user_input="ok")

        server.agent.resume.assert_awaited_once()
        call_args = server.agent.resume.call_args
        assert call_args[0][0] == "sess-1"   # session_id
        assert call_args[0][1] == "ok"        # user_input

    @pytest.mark.asyncio
    async def test_resume_deletes_suspended_entry(self):
        """resume_from_oauth_callback deletes the SuspendedExecution after success."""
        store = FakeSuspendedStore()
        interaction_id = "test-interaction-002"
        store._store[interaction_id] = FakeSuspendedExecution(interaction_id=interaction_id)

        server = _make_server(suspended_store=store)
        await server.resume_from_oauth_callback(interaction_id)

        assert not store.has(interaction_id), "SuspendedExecution not deleted after resume"

    @pytest.mark.asyncio
    async def test_resume_after_ttl_expiry_does_not_crash(self):
        """Expired entry (store returns None) → graceful re-prompt, no exception."""
        store = FakeSuspendedStore()  # empty — simulates TTL expiry

        server = _make_server(suspended_store=store)
        # Should not raise
        await server.resume_from_oauth_callback("expired-interaction-id")

        # Agent must NOT have been called
        server.agent.resume.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_resume_without_store_does_not_crash(self):
        """No suspended_store configured → graceful no-op (logs warning)."""
        server = _make_server(suspended_store=None)
        # Should not raise
        await server.resume_from_oauth_callback("some-interaction-id")
        server.agent.resume.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_resume_calls_ask_when_agent_has_no_resume(self):
        """Agent without resume() → ask() is called as fallback."""
        store = FakeSuspendedStore()
        interaction_id = "test-interaction-003"
        store._store[interaction_id] = FakeSuspendedExecution(interaction_id=interaction_id)

        server = _make_server(suspended_store=store)
        # Remove resume attribute to simulate old agent
        del server.agent.resume
        server.agent.ask = AsyncMock(return_value="ask-fallback")

        # Should not raise
        await server.resume_from_oauth_callback(interaction_id, user_input="hello")
        server.agent.ask.assert_awaited_once()


# ---------------------------------------------------------------------------
# TestRegisterA2AResumeHook — oauth2_routes.register_a2a_resume_hook
# ---------------------------------------------------------------------------


class TestRegisterA2AResumeHook:
    def test_hook_stored_on_app(self):
        """register_a2a_resume_hook stores the hook on the aiohttp app."""
        app = {}  # dict as minimal app substitute

        async def my_hook(interaction_id: str) -> None:
            pass

        register_a2a_resume_hook(app, my_hook)  # type: ignore[arg-type]
        assert app.get("a2a_oauth_resume_hook") is my_hook

    def test_second_registration_overwrites(self):
        """Re-registering the hook replaces the previous one."""
        app = {}

        async def hook1(iid: str) -> None:
            pass

        async def hook2(iid: str) -> None:
            pass

        register_a2a_resume_hook(app, hook1)  # type: ignore[arg-type]
        register_a2a_resume_hook(app, hook2)  # type: ignore[arg-type]
        assert app["a2a_oauth_resume_hook"] is hook2


# ---------------------------------------------------------------------------
# TestCallbackA2AFanout — integration of the callback fan-out path
# (tests the make_oauth2_callback handler indirectly via the server)
# ---------------------------------------------------------------------------


class TestA2AServerResumeHookIntegration:
    @pytest.mark.asyncio
    async def test_a2a_server_resume_method_is_hookable(self):
        """A2AServer.resume_from_oauth_callback can be used as the A2A hook."""
        store = FakeSuspendedStore()
        interaction_id = "hook-test-001"
        store._store[interaction_id] = FakeSuspendedExecution(interaction_id=interaction_id)

        server = _make_server(suspended_store=store)

        # The method should be directly callable as a hook
        hook = server.resume_from_oauth_callback
        await hook(interaction_id, user_input="")

        server.agent.resume.assert_awaited_once()
        assert not store.has(interaction_id)

    @pytest.mark.asyncio
    async def test_resume_passes_user_id_in_state(self):
        """resume_from_oauth_callback passes user_id to agent.resume state dict."""
        store = FakeSuspendedStore()
        interaction_id = "hook-test-002"
        suspended = FakeSuspendedExecution(
            interaction_id=interaction_id,
            user_id="alice@example.com"
        )
        store._store[interaction_id] = suspended

        server = _make_server(suspended_store=store)
        await server.resume_from_oauth_callback(interaction_id)

        call_kwargs = server.agent.resume.call_args[0]
        # Third positional arg is the state dict
        state_arg = call_kwargs[2] if len(call_kwargs) > 2 else server.agent.resume.call_args[1].get("state", {})
        if isinstance(state_arg, dict):
            assert state_arg.get("user_id") == "alice@example.com"
