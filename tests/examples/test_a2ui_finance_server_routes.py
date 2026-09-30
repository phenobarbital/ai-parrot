"""A2UI finance example — server routes: definition-only envelope, shared static lane, cache/rebuild, 502 paths."""

from __future__ import annotations

import sys
import types
from pathlib import Path
from typing import Any

import pytest
from aiohttp import web

from parrot.models.basic import CompletionUsage, ToolCall
from parrot.models.responses import AIMessage

from ._finance_envelope import real_finance_envelope

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "examples" / "a2ui_finance"))
import finance_server  # noqa: E402


class FakeAgent:
    """Agent stub returning a BAKED envelope: the server must strip its rows before serving it."""

    def __init__(self) -> None:
        self.calls = 0

    async def configure(self) -> None:
        return None

    async def ask(self, question: str) -> AIMessage:
        self.calls += 1
        envelope = real_finance_envelope(snapshot=True)
        call = ToolCall(id="1", name="qs_build_linked_dashboard", arguments={}, result={"a2ui_envelope": envelope})
        return AIMessage(
            input=question, output="ok", model="m", provider="p", usage=CompletionUsage(), tool_calls=[call]
        )


class FakeAuthHandler:
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
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    def setup(self, app: web.Application) -> None:
        return None


async def _noop(app: web.Application) -> None:
    return None


@pytest.fixture
def agent(monkeypatch: pytest.MonkeyPatch) -> FakeAgent:
    fake = FakeAgent()
    monkeypatch.setattr(finance_server, "build_dashboard_agent", lambda llm=None: fake)
    monkeypatch.setattr(finance_server, "check_slugs", _noop)
    monkeypatch.setitem(sys.modules, "navigator_auth", types.SimpleNamespace(AuthHandler=FakeAuthHandler))
    monkeypatch.setitem(sys.modules, "querysource.services", types.SimpleNamespace(QuerySource=FakeQuerySource))
    return fake


@pytest.mark.asyncio
async def test_finance_server_routes(agent: FakeAgent, aiohttp_client: Any) -> None:
    client = await aiohttp_client(finance_server.create_app())

    resp = await client.get("/")
    assert resp.status == 200
    assert "Finance projection" in await resp.text()

    resp = await client.get("/static/linked.js")  # served from the SHARED examples/a2ui/static
    assert resp.status == 200
    assert "api/v2/services/queries" in await resp.text()

    resp = await client.get("/api/a2ui/dashboard", headers={"Authorization": "Bearer t"})
    assert resp.status == 200
    envelope = await resp.json()
    sources = envelope["metadata"]["extensions"]["parrot_data_sources"]
    assert sources
    assert all(envelope["dataModel"][key] == {"rows": []} for key in sources), "served envelope is definition-only"
    assert all(source["snapshot_at"] is None for source in sources.values())

    await client.get("/api/a2ui/dashboard", headers={"Authorization": "Bearer t"})
    assert agent.calls == 1
    await client.get("/api/a2ui/dashboard?rebuild=1", headers={"Authorization": "Bearer t"})
    assert agent.calls == 2

    resp = await client.get("/api/a2ui/dashboard")
    assert resp.status in (401, 403)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [RuntimeError("no linked envelope"), ConnectionError("llm down")])
async def test_dashboard_failure_is_a_502_never_a_500(
    agent: FakeAgent, aiohttp_client: Any, monkeypatch: pytest.MonkeyPatch, failure: Exception
) -> None:
    async def boom(question: str) -> AIMessage:
        raise failure

    monkeypatch.setattr(agent, "ask", boom)
    client = await aiohttp_client(finance_server.create_app())
    resp = await client.get("/api/a2ui/dashboard", headers={"Authorization": "Bearer t"})
    assert resp.status == 502
    assert "error" in await resp.json()


@pytest.mark.asyncio
async def test_check_slugs_warns_and_never_raises(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A missing slug or a failing DatasetManager probe is a warning naming the seed, never a startup failure."""

    class Toolkit:
        def __init__(self, **kwargs: Any) -> None:
            assert kwargs["programs"] == ["troc"]

        async def describe_slug(self, slug: str) -> None:
            raise RuntimeError(f"{slug} missing")

    fake_tools = types.ModuleType("parrot_tools.querysource.toolkit")
    fake_tools.QuerysourceToolkit = Toolkit
    monkeypatch.setitem(sys.modules, "parrot_tools.querysource.toolkit", fake_tools)
    with caplog.at_level("WARNING"):
        await finance_server.check_slugs(web.Application())
    assert any("seed_finance.py --yes" in record.message for record in caplog.records)
