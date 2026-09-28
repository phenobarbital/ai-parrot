"""FEAT-610 TASK-3849 — example server routes (spec section 4 integration test)."""

from __future__ import annotations

import sys
import types
from pathlib import Path
from typing import Any

import pytest
from aiohttp import web

from parrot.models.basic import CompletionUsage, ToolCall
from parrot.models.responses import AIMessage

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "examples" / "a2ui"))
import server  # noqa: E402

ENVELOPE = {"metadata": {"extensions": {"parrot_data_sources": {"a": {"slug": "x"}}}}}


class FakeAgent:
    """Agent stub returning a message with a linked-dashboard tool call."""

    def __init__(self) -> None:
        self.calls = 0

    async def configure(self) -> None:
        return None

    async def ask(self, question: str) -> AIMessage:
        self.calls += 1
        call = ToolCall(id="1", name="qs_build_linked_dashboard", arguments={}, result={"a2ui_envelope": ENVELOPE})
        return AIMessage(
            input=question,
            output="ok",
            model="m",
            provider="p",
            usage=CompletionUsage(),
            tool_calls=[call],
        )


class FakeAuthHandler:
    """AuthHandler stub rejecting requests without Authorization unless excluded."""

    def setup(self, app: web.Application) -> None:
        app["auth_exclude_list"] = []

        @web.middleware
        async def guard(request: web.Request, handler: Any) -> web.StreamResponse:
            excluded = request.path == "/" or request.path.startswith("/static/")
            if not excluded and "Authorization" not in request.headers:
                raise web.HTTPUnauthorized()
            return await handler(request)

        app.middlewares.append(guard)


class FakeQuerySource:
    """QuerySource stub."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    def setup(self, app: web.Application) -> None:
        return None


@pytest.fixture
def agent(monkeypatch: pytest.MonkeyPatch) -> FakeAgent:
    fake = FakeAgent()
    monkeypatch.setattr(server, "build_dashboard_agent", lambda llm=None: fake)
    monkeypatch.setattr(server, "check_slugs", _noop)
    monkeypatch.setitem(sys.modules, "navigator_auth", types.SimpleNamespace(AuthHandler=FakeAuthHandler))
    monkeypatch.setitem(sys.modules, "querysource.services", types.SimpleNamespace(QuerySource=FakeQuerySource))
    return fake


async def _noop(app: web.Application) -> None:
    return None


@pytest.mark.asyncio
async def test_dashboard_example_server_routes(
    agent: FakeAgent, aiohttp_client: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text("<html>ok</html>")
    monkeypatch.setattr(server, "STATIC", static)
    client = await aiohttp_client(server.create_app())

    resp = await client.get("/")
    assert resp.status == 200
    assert "<html>" in await resp.text()

    resp = await client.get("/api/a2ui/dashboard", headers={"Authorization": "Bearer t"})
    assert resp.status == 200
    assert (await resp.json())["metadata"]["extensions"]["parrot_data_sources"]
    await client.get("/api/a2ui/dashboard", headers={"Authorization": "Bearer t"})
    assert agent.calls == 1
    await client.get("/api/a2ui/dashboard?rebuild=1", headers={"Authorization": "Bearer t"})
    assert agent.calls == 2

    resp = await client.get("/api/a2ui/dashboard")
    assert resp.status in (401, 403)


def test_require_querysource_exits() -> None:
    with pytest.raises(SystemExit):
        server.require_querysource("99.0")
