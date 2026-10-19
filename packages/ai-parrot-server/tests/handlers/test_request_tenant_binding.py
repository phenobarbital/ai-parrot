"""FEAT-707 — HTTP tenant binding (TASK-4497)."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import web
from aiohttp.test_utils import make_mocked_request

from parrot.handlers.agents.abstract import AgentHandler
from parrot.handlers.chat import ChatHandler
from parrot.handlers.scope import RequestScope, resolve_request_tenant


class _Resolver:
    """Resolver returning one fixed server-side tenant."""

    def __init__(self, tenant: str | None = "pokemon") -> None:
        self.scope = RequestScope(user_id="u-test", tenant=tenant, groups=frozenset())

    async def resolve(self, request: web.Request) -> RequestScope:
        """Return the configured trusted scope."""
        return self.scope


class _RaisingResolver:
    """Resolver used to prove tenant lookup fails closed."""

    async def resolve(self, request: web.Request) -> RequestScope:
        """Raise as a broken session resolver would."""
        raise RuntimeError("session unavailable")


class _FakeBot:
    """Minimal chat bot recording every handler dispatch."""

    name = "tenant-bot"

    def __init__(self) -> None:
        self.ask_calls: list[dict] = []
        self.stream_calls: list[dict] = []
        self.custom_calls: list[dict] = []

    @asynccontextmanager
    async def session(self, **kwargs):
        """Yield this bot as the normal session manager does."""
        yield self

    async def ask(self, **kwargs) -> dict:
        """Record synchronous chat input."""
        self.ask_calls.append(kwargs)
        return {"answer": "ok"}

    async def ask_stream(self, **kwargs):
        """Record streaming chat input and yield one event."""
        self.stream_calls.append(kwargs)

        async def events():
            yield {"answer": "ok"}

        return events()

    async def custom(self, **kwargs) -> dict:
        """Record custom method input."""
        self.custom_calls.append(kwargs)
        return {"answer": "custom"}


def _unwrap(method):
    """Return an auth-decorator-free handler method for unit tests."""
    while hasattr(method, "__wrapped__"):
        method = method.__wrapped__
    return method


def _chat_handler(*, resolver: object | None = None, method_name: str | None = None):
    """Create a direct ``ChatHandler`` invocation using a recording bot."""
    bot = _FakeBot()
    manager = MagicMock()
    manager.get_user_bot = AsyncMock(return_value=None)
    manager.get_bot = AsyncMock(return_value=bot)
    app = web.Application()
    app["bot_manager"] = manager
    if resolver is not None:
        app["scope_resolver"] = resolver
    request = make_mocked_request(
        "POST",
        "/api/v1/chat/tenant-bot",
        app=app,
        match_info={"chatbot_name": "tenant-bot", "method_name": method_name},
    )
    request.session = {"user_id": "u-test"}
    handler = ChatHandler(request)
    handler.handle_upload = AsyncMock(side_effect=web.HTTPUnsupportedMediaType())
    handler.query_parameters = MagicMock(return_value={})
    handler._check_pbac_chatbot_access = AsyncMock(return_value=None)
    return handler, bot, request


async def test_resolve_request_tenant_no_resolver() -> None:
    """A host without a resolver has no trusted tenant."""
    assert await resolve_request_tenant({}, MagicMock()) is None


async def test_resolve_request_tenant_single_program() -> None:
    """The helper returns only the resolver-provided tenant."""
    assert await resolve_request_tenant({"scope_resolver": _Resolver()}, MagicMock()) == "pokemon"


async def test_resolve_request_tenant_resolver_raises() -> None:
    """A failed resolver never exposes a tenant or raises to the caller."""
    assert await resolve_request_tenant({"scope_resolver": _RaisingResolver()}, MagicMock()) is None


async def test_chat_handler_drops_client_tenant(caplog) -> None:
    """Client JSON cannot override the server-resolved chat tenant."""
    handler, bot, request = _chat_handler(resolver=_Resolver())
    request.json = AsyncMock(return_value={"query": "hello", "tenant": "epson"})
    with caplog.at_level(logging.WARNING):
        response = await _unwrap(ChatHandler.post)(handler)
    assert response.status == 200
    assert bot.ask_calls[-1]["tenant"] == "pokemon"
    assert "Ignoring client-supplied 'tenant'" in caplog.text


async def test_chat_handler_passes_server_tenant_stream_and_sync(monkeypatch) -> None:
    """Both chat paths receive the same trusted server-side tenant."""
    sync_handler, bot, sync_request = _chat_handler(resolver=_Resolver())
    sync_request.json = AsyncMock(return_value={"query": "sync"})
    sync_response = await _unwrap(ChatHandler.post)(sync_handler)

    class _StreamResponse:
        status = 200

        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs

        async def prepare(self, request) -> None:
            return None

        async def write(self, data: bytes) -> None:
            return None

        async def write_eof(self) -> None:
            return None

    monkeypatch.setattr("parrot.handlers.chat.web.StreamResponse", _StreamResponse)
    stream_handler, stream_bot, stream_request = _chat_handler(resolver=_Resolver())
    stream_request.json = AsyncMock(return_value={"query": "stream", "stream": True})
    stream_response = await _unwrap(ChatHandler.post)(stream_handler)
    assert sync_response.status == stream_response.status == 200
    assert bot.ask_calls[-1]["tenant"] == "pokemon"
    assert stream_bot.stream_calls[-1]["tenant"] == "pokemon"


async def test_chat_handler_custom_method_never_sees_tenant() -> None:
    """Tenant is removed before custom-method parameters are assembled."""
    handler, bot, request = _chat_handler(resolver=_Resolver(), method_name="custom")
    request.json = AsyncMock(return_value={"query": "ignored", "tenant": "epson"})
    response = await _unwrap(ChatHandler.post)(handler)
    assert response.status == 200
    assert "tenant" not in bot.custom_calls[-1]


async def test_ask_agent_passes_tenant() -> None:
    """The abstract agent handler forwards the trusted server tenant."""
    agent = MagicMock()
    agent.ask = AsyncMock(return_value=MagicMock(output="report"))
    request = MagicMock()
    request.app = {"scope_resolver": _Resolver("digimon")}
    request.session = {"user_id": "u-test"}
    handler = AgentHandler(request)
    handler._agent = agent
    handler._userid = None
    handler.agent_name = "reporting"
    handler._agent_response = MagicMock(return_value=MagicMock())
    handler.logger = logging.getLogger(__name__)

    await handler.ask_agent(query="report")

    assert agent.ask.await_args.kwargs["tenant"] == "digimon"
