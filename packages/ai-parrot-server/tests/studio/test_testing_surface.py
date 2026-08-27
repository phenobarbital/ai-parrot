"""Tests for the Studio testing surface (FEAT-467 TASK-2517).

Covers: session-scoped test/ask instance reuse + BYOK client swap + DELETE
teardown, deterministic tool execute (zero-arg success / unknown slug 404 /
server-managed-deps 422), and tool/toolkit assignment onto a live agent's
``tool_manager`` (with ownership enforcement).

All LLM calls are mocked — no network. Handlers are called directly via
their undecorated method bodies (pattern: ``test_agents_lifecycle.py``),
peeling ``@is_authenticated()``/``@user_session()`` via ``__wrapped__``.
"""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import web
from aiohttp.test_utils import make_mocked_request
from parrot.handlers.studio import testing as testing_module
from parrot.handlers.studio._base import StudioUser
from parrot.handlers.studio.testing import (
    StudioTestingHandler,
    StudioToolAssignHandler,
    StudioToolExecuteHandler,
)
from parrot.tools.abstract import AbstractTool
from parrot.tools.manager import ToolManager
from parrot.tools.toolkit import AbstractToolkit


def _unwrap(method):
    """Peel back class-level auth decorators to the undecorated method body."""
    while hasattr(method, "__wrapped__"):
        method = method.__wrapped__
    return method


async def _decode(response: web.Response) -> dict:
    return json.loads(response.body)


def _make_handler(handler_cls, app, *, method="GET", path="/x", match_info=None,
                   json_body=None, owner="1", session=None):
    request = make_mocked_request(method, path, match_info=match_info or {}, app=app)
    if json_body is not None:
        request.json = AsyncMock(return_value=json_body)
    handler = handler_cls(request)
    handler._get_user = AsyncMock(return_value=StudioUser(user_id=owner))
    handler._resolve_session = AsyncMock(return_value=session if session is not None else {})
    return handler


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _FakeSessionCtx:
    """Fake async context manager for ``AbstractBot.session(...)``."""

    def __init__(self, bot):
        self._bot = bot

    async def __aenter__(self):
        return self._bot

    async def __aexit__(self, *_args):
        return False


class _FakeTestBot:
    """Stand-in for a session-scoped test agent instance."""

    def __init__(self, name="fake_test_bot", llm_raw="anthropic:claude-3-haiku"):
        self.name = name
        self._llm_raw = llm_raw
        self.llm = MagicMock(name="default_llm_client")
        self.tool_manager = MagicMock()
        self.ask_calls: list[str] = []
        self._ask_result = SimpleNamespace(content="hello there", metadata={"tokens": 5})
        self._ask_error: Exception | None = None

    def session(self, request=None, app=None):
        return _FakeSessionCtx(self)

    async def ask(self, question: str):
        self.ask_calls.append(question)
        if self._ask_error is not None:
            raise self._ask_error
        return self._ask_result


class _FakeTestManager:
    """Fake BotManager for ``_get_or_create_test_bot`` unit tests."""

    def __init__(self):
        self._bots: dict[str, _FakeTestBot] = {}
        self.get_bot_calls = 0
        self.remove_bot_calls: list[str] = []

    async def get_bot(self, name, new=False, session_id="", **kwargs):
        self.get_bot_calls += 1
        bot = _FakeTestBot(name=f"{name}_{session_id}")
        self._bots[bot.name] = bot
        return bot

    def remove_bot(self, name):
        self.remove_bot_calls.append(name)
        self._bots.pop(name, None)


# ---------------------------------------------------------------------------
# Fake tools / toolkits for the execute + assignment tests
# ---------------------------------------------------------------------------


class _ZeroArgTool(AbstractTool):
    """A trivially-instantiable tool for deterministic-execute tests."""

    name = "fake_zero_arg_tool"
    description = "Echoes back a fixed payload."

    async def _execute(self, **kwargs):
        return {"echoed": True}


class _NeedsDepTool(AbstractTool):
    """A tool whose constructor requires an unresolvable dependency."""

    name = "fake_needs_dep_tool"
    description = "Requires a 'foo' dependency this endpoint can't supply."

    def __init__(self, foo, **kwargs):
        self.foo = foo
        super().__init__(**kwargs)

    async def _execute(self, **kwargs):
        return {"foo": self.foo}


class _FakeToolkit(AbstractToolkit):
    """A minimal toolkit exposing one tool method."""

    async def echo(self, text: str) -> str:
        """Echo text back."""
        return text


# ---------------------------------------------------------------------------
# Session reuse — unit test of the mixin helper
# ---------------------------------------------------------------------------


class TestSessionReuse:
    @pytest.mark.asyncio
    async def test_get_or_create_test_bot_reuses_instance(self):
        app = web.Application()
        manager = _FakeTestManager()
        app["bot_manager"] = manager
        handler = _make_handler(StudioTestingHandler, app)

        session: dict = {}
        bot1 = await handler._get_or_create_test_bot("myagent", session)
        bot2 = await handler._get_or_create_test_bot("myagent", session)

        assert bot1 is bot2
        assert manager.get_bot_calls == 1
        assert session[handler._session_key("myagent")] == bot1.name


# ---------------------------------------------------------------------------
# test/ask + DELETE
# ---------------------------------------------------------------------------


class TestTestAsk:
    @pytest.mark.asyncio
    async def test_ask_session_instance_reused(self):
        app = web.Application()
        handler = _make_handler(
            StudioTestingHandler, app, method="POST", path="/test/ask",
            match_info={"name": "myagent"}, json_body={"query": "hi", "use_byok": False},
        )
        bot = _FakeTestBot()
        handler._get_or_create_test_bot = AsyncMock(return_value=bot)

        response = await _unwrap(StudioTestingHandler.post)(handler)

        assert response.status == 200
        body = await _decode(response)
        assert body["response"] == "hello there"
        assert body["metadata"] == {"tokens": 5}
        assert bot.ask_calls == ["hi"]

    @pytest.mark.asyncio
    async def test_ask_uses_byok_key(self, monkeypatch):
        app = web.Application()
        handler = _make_handler(
            StudioTestingHandler, app, method="POST", path="/test/ask",
            match_info={"name": "myagent"}, json_body={"query": "hi", "use_byok": True},
        )
        bot = _FakeTestBot(llm_raw="anthropic:claude-3-haiku")
        handler._get_or_create_test_bot = AsyncMock(return_value=bot)

        resolve_mock = AsyncMock(return_value="sk-ant-byok-key")
        monkeypatch.setattr(testing_module, "resolve_user_api_key", resolve_mock)
        byok_client = MagicMock(name="byok_client")
        create_mock = MagicMock(return_value=byok_client)
        monkeypatch.setattr(testing_module.LLMFactory, "create", create_mock)

        response = await _unwrap(StudioTestingHandler.post)(handler)

        assert response.status == 200
        resolve_mock.assert_awaited_once()
        assert resolve_mock.await_args.args[1:] == ("1", "anthropic")
        create_mock.assert_called_once()
        assert create_mock.call_args.args[0] == "anthropic:claude-3-haiku"
        assert create_mock.call_args.kwargs["api_key"] == "sk-ant-byok-key"
        assert bot.llm is byok_client

    @pytest.mark.asyncio
    async def test_ask_byok_no_stored_key_is_noop(self, monkeypatch):
        app = web.Application()
        handler = _make_handler(
            StudioTestingHandler, app, method="POST", path="/test/ask",
            match_info={"name": "myagent"}, json_body={"query": "hi", "use_byok": True},
        )
        bot = _FakeTestBot()
        original_llm = bot.llm
        handler._get_or_create_test_bot = AsyncMock(return_value=bot)
        monkeypatch.setattr(
            testing_module, "resolve_user_api_key", AsyncMock(return_value=None)
        )
        create_mock = MagicMock()
        monkeypatch.setattr(testing_module.LLMFactory, "create", create_mock)

        response = await _unwrap(StudioTestingHandler.post)(handler)

        assert response.status == 200
        create_mock.assert_not_called()
        assert bot.llm is original_llm

    @pytest.mark.asyncio
    async def test_ask_query_failure_surfaces_as_error(self):
        app = web.Application()
        handler = _make_handler(
            StudioTestingHandler, app, method="POST", path="/test/ask",
            match_info={"name": "myagent"}, json_body={"query": "hi", "use_byok": False},
        )
        bot = _FakeTestBot()
        bot._ask_error = RuntimeError("provider auth failed")
        handler._get_or_create_test_bot = AsyncMock(return_value=bot)

        response = await _unwrap(StudioTestingHandler.post)(handler)

        assert response.status == 502
        body = await _decode(response)
        assert body["code"] == "query_failed"

    @pytest.mark.asyncio
    async def test_ask_unknown_agent_404(self):
        app = web.Application()
        handler = _make_handler(
            StudioTestingHandler, app, method="POST", path="/test/ask",
            match_info={"name": "nope"}, json_body={"query": "hi"},
        )
        handler._get_or_create_test_bot = AsyncMock(
            side_effect=LookupError("Agent 'nope' not found in registry.")
        )

        response = await _unwrap(StudioTestingHandler.post)(handler)

        assert response.status == 404

    @pytest.mark.asyncio
    async def test_delete_ends_session(self):
        app = web.Application()
        manager = MagicMock()
        app["bot_manager"] = manager
        session = {"_studio_test:myagent": "myagent_abc123"}
        handler = _make_handler(
            StudioTestingHandler, app, method="DELETE", path="/test",
            match_info={"name": "myagent"}, session=session,
        )

        response = await _unwrap(StudioTestingHandler.delete)(handler)

        assert response.status == 200
        assert "_studio_test:myagent" not in session
        manager.remove_bot.assert_called_once_with("myagent_abc123")

    @pytest.mark.asyncio
    async def test_delete_no_active_session_is_noop(self):
        app = web.Application()
        manager = MagicMock()
        app["bot_manager"] = manager
        handler = _make_handler(
            StudioTestingHandler, app, method="DELETE", path="/test",
            match_info={"name": "myagent"}, session={},
        )

        response = await _unwrap(StudioTestingHandler.delete)(handler)

        assert response.status == 200
        manager.remove_bot.assert_not_called()


# ---------------------------------------------------------------------------
# tools/{slug}/execute
# ---------------------------------------------------------------------------


class TestToolExecute:
    @pytest.mark.asyncio
    async def test_execute_zero_arg_tool(self, monkeypatch):
        app = web.Application()
        monkeypatch.setattr(
            testing_module, "discover_all",
            lambda: {"fake_zero_arg_tool": _ZeroArgTool},
        )
        handler = _make_handler(
            StudioToolExecuteHandler, app, method="POST", path="/tools/x/execute",
            match_info={"slug": "fake_zero_arg_tool"}, json_body={"args": {}},
        )

        response = await _unwrap(StudioToolExecuteHandler.post)(handler)

        assert response.status == 200
        body = await _decode(response)
        assert body["status"] == "success"
        assert body["result"] == {"echoed": True}

    @pytest.mark.asyncio
    async def test_execute_unknown_slug_404(self, monkeypatch):
        app = web.Application()
        monkeypatch.setattr(testing_module, "discover_all", dict)
        handler = _make_handler(
            StudioToolExecuteHandler, app, method="POST", path="/tools/x/execute",
            match_info={"slug": "does-not-exist"}, json_body={"args": {}},
        )

        response = await _unwrap(StudioToolExecuteHandler.post)(handler)

        assert response.status == 404

    @pytest.mark.asyncio
    async def test_execute_server_managed_422(self, monkeypatch):
        app = web.Application()
        monkeypatch.setattr(
            testing_module, "discover_all",
            lambda: {"fake_needs_dep_tool": _NeedsDepTool},
        )
        handler = _make_handler(
            StudioToolExecuteHandler, app, method="POST", path="/tools/x/execute",
            match_info={"slug": "fake_needs_dep_tool"}, json_body={"args": {}},
        )

        response = await _unwrap(StudioToolExecuteHandler.post)(handler)

        assert response.status == 422
        body = await _decode(response)
        assert body["code"] == "server_managed"
        assert body["details"]["missing"] == ["foo"]


# ---------------------------------------------------------------------------
# agents/{name}/tools — assignment
# ---------------------------------------------------------------------------


class TestToolAssignment:
    def _bot_with_real_tool_manager(self):
        bot = SimpleNamespace(tool_manager=ToolManager())
        return bot

    @pytest.mark.asyncio
    async def test_assign_toolkit_registers_tools(self, monkeypatch):
        app = web.Application()
        bot = self._bot_with_real_tool_manager()
        manager = MagicMock()
        manager.get_bot = AsyncMock(return_value=bot)
        app["bot_manager"] = manager

        monkeypatch.setattr(
            testing_module, "discover_all",
            lambda: {"fake_toolkit": _FakeToolkit},
        )

        handler = _make_handler(
            StudioToolAssignHandler, app, method="POST", path="/agents/myagent/tools",
            match_info={"name": "myagent"}, owner="1",
            json_body={"tools": [], "toolkits": [{"slug": "fake_toolkit", "params": {}}]},
        )
        handler._get_db_agent = AsyncMock(return_value=None)
        fake_meta = SimpleNamespace(bot_config=SimpleNamespace(config={"created_by": "1"}))
        handler._registry = MagicMock(
            return_value=SimpleNamespace(get_metadata=lambda name: fake_meta)
        )

        response = await _unwrap(StudioToolAssignHandler.post)(handler)

        assert response.status == 200
        body = await _decode(response)
        assert body["persisted"] is False
        assert "echo" in body["registered_tools"]
        assert "echo" in bot.tool_manager.list_tools()

    @pytest.mark.asyncio
    async def test_assign_requires_ownership(self):
        app = web.Application()
        bot = self._bot_with_real_tool_manager()
        manager = MagicMock()
        manager.get_bot = AsyncMock(return_value=bot)
        app["bot_manager"] = manager

        handler = _make_handler(
            StudioToolAssignHandler, app, method="POST", path="/agents/myagent/tools",
            match_info={"name": "myagent"}, owner="not-the-owner",
            json_body={"tools": [], "toolkits": []},
        )
        handler._get_db_agent = AsyncMock(return_value=None)
        fake_meta = SimpleNamespace(bot_config=SimpleNamespace(config={"created_by": "1"}))
        handler._registry = MagicMock(
            return_value=SimpleNamespace(get_metadata=lambda name: fake_meta)
        )

        with pytest.raises(web.HTTPForbidden):
            await _unwrap(StudioToolAssignHandler.post)(handler)

    @pytest.mark.asyncio
    async def test_assign_unknown_toolkit_reports_error(self, monkeypatch):
        app = web.Application()
        bot = self._bot_with_real_tool_manager()
        manager = MagicMock()
        manager.get_bot = AsyncMock(return_value=bot)
        app["bot_manager"] = manager

        monkeypatch.setattr(testing_module, "discover_all", dict)

        handler = _make_handler(
            StudioToolAssignHandler, app, method="POST", path="/agents/myagent/tools",
            match_info={"name": "myagent"}, owner="1",
            json_body={"tools": [], "toolkits": [{"slug": "nope", "params": {}}]},
        )
        handler._get_db_agent = AsyncMock(return_value=None)
        fake_meta = SimpleNamespace(bot_config=SimpleNamespace(config={"created_by": "1"}))
        handler._registry = MagicMock(
            return_value=SimpleNamespace(get_metadata=lambda name: fake_meta)
        )

        response = await _unwrap(StudioToolAssignHandler.post)(handler)

        assert response.status == 200
        body = await _decode(response)
        assert body["registered_tools"] == []
        assert body["errors"][0]["slug"] == "nope"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
