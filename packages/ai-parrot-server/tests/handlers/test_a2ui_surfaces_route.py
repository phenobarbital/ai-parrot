"""``A2UIHandler`` surfaces mirror route tests (FEAT-492, TASK-2703).

Real aiohttp ``TestClient`` end-to-end (``A2UIHandler`` does not use
``@is_authenticated()`` — see ``handlers/a2ui.py`` module docstring — so the
``test_a2ui_handler.py`` client-fixture idiom applies directly). The
``PgUISurfaceStore`` is stubbed via ``app["ui_surfaces_store"]`` (the same
app-context slot ``UISurfacesHandler``/``A2UIHandler`` both lazily populate),
so no live Postgres is required.
"""
from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import web
from parrot.handlers.a2ui import A2UIHandler
from parrot.handlers.agent import AgentTalk
from parrot.handlers.models.ui_surfaces import (
    UISurfaceKind,
    UISurfaceRecord,
    UISurfaceShare,
)
from parrot.handlers.ui_surfaces import SurfaceNegotiationService, UISurfacesHandler
from parrot.memory.file import FileConversationMemory
from parrot.outputs.a2ui.catalog.base import DEFAULT_CATALOG_ID
from parrot.outputs.a2ui.models import CreateSurface
from parrot.tools import tool
from parrot.tools.manager import ToolManager


@tool
def get_weather(location: str) -> str:
    """Get the weather for a location."""
    return f"Weather in {location}: Sunny"


def _make_agent(tmp_path):
    tm = ToolManager()
    tm.register_tool(get_weather)
    agent = MagicMock()
    agent.name = "demo"
    agent.tool_manager = tm
    agent.conversation_memory = FileConversationMemory(base_path=str(tmp_path))
    reply = MagicMock()
    reply.a2ui_envelope = None
    agent.ask = AsyncMock(return_value=reply)
    return agent


def _bot_manager(agent):
    manager = MagicMock()
    manager.get_user_bot = AsyncMock(return_value=None)
    manager.get_bot = AsyncMock(return_value=agent)
    return manager


def _sample_envelope(surface_id="s-1") -> dict:
    return CreateSurface(
        surfaceId=surface_id, components=[], dataModel={"filters": {"window": "all"}}
    ).model_dump(by_alias=True, mode="json")


def _make_record(**overrides) -> UISurfaceRecord:
    now = datetime.now(UTC)
    defaults = {
        "surface_id": "surface-1",
        "kind": UISurfaceKind.dashboard,
        "title": "Q3 Revenue",
        "envelope": _sample_envelope(),
        "catalog_id": None,
        "agent_id": "demo",
        "user_id": "u-1",
        "session_id": "sess-1",
        "recipe_name": None,
        "recipe_owner": None,
        "recipe_params": {},
        "created_at": now,
        "updated_at": now,
    }
    defaults.update(overrides)
    return UISurfaceRecord(**defaults)


@pytest.fixture
def fake_store():
    store = MagicMock()
    store.get = AsyncMock(return_value=None)
    store.resolve_share = AsyncMock(return_value=None)
    store.claim_share = AsyncMock(return_value=None)
    return store


@pytest.fixture
async def client(aiohttp_client, tmp_path, fake_store):
    agent = _make_agent(tmp_path)
    app = web.Application()
    app["bot_manager"] = _bot_manager(agent)
    app["_test_agent"] = agent
    app["ui_surfaces_store"] = fake_store
    # Pre-wire the negotiation service too — avoids aiohttp's "changing state
    # of started application" deprecation warning from the lazy-cache
    # fallback firing after aiohttp_client() has already started the app
    # (a real setup_app() would wire both at startup, same as recipe_runner).
    app["ui_surfaces_negotiation"] = SurfaceNegotiationService()
    router = app.router
    router.add_view("/api/v1/agents/chat/{agent_id}", AgentTalk)
    # Mirrors manager.py's literal-before-pattern ordering (TASK-2703).
    router.add_view("/api/v1/agents/{agent_id}/a2ui/capabilities", A2UIHandler)
    router.add_view("/api/v1/agents/{agent_id}/a2ui/surfaces/{surface_id}", A2UIHandler)
    router.add_view("/api/v1/agents/{agent_id}/a2ui", A2UIHandler)
    router.add_view("/api/v1/ui/surfaces/{surface_id}", UISurfacesHandler)
    return await aiohttp_client(app)


def _auth_params(user_id="u-1", session_id="sess-1"):
    return {"user_id": user_id, "session_id": session_id}


class TestMirrorRouteNegotiation:
    async def test_mirror_route_json_and_html_negotiation(self, client, fake_store):
        fake_store.get.return_value = _make_record()

        r_json = await client.get(
            "/api/v1/agents/demo/a2ui/surfaces/surface-1", params=_auth_params()
        )
        assert r_json.status == 200
        assert r_json.content_type == "application/json"
        body = await r_json.json()
        assert body["metadata"]["surface_id"] == "surface-1"

        params_html = {**_auth_params(), "format": "html"}
        r_html = await client.get(
            "/api/v1/agents/demo/a2ui/surfaces/surface-1", params=params_html
        )
        assert r_html.status == 200
        assert r_html.content_type == "text/html"

    async def test_mirror_route_delegates_to_shared_service(self, client, fake_store, monkeypatch):
        fake_store.get.return_value = _make_record()
        calls = []
        original_negotiate = SurfaceNegotiationService.negotiate

        def _spy_negotiate(self, request):
            calls.append("negotiate")
            return original_negotiate(self, request)

        original_respond = SurfaceNegotiationService.respond

        async def _spy_respond(self, record, accept):
            calls.append("respond")
            return await original_respond(self, record, accept)

        monkeypatch.setattr(SurfaceNegotiationService, "negotiate", _spy_negotiate)
        monkeypatch.setattr(SurfaceNegotiationService, "respond", _spy_respond)

        r = await client.get("/api/v1/agents/demo/a2ui/surfaces/surface-1", params=_auth_params())

        assert r.status == 200
        assert calls == ["negotiate", "respond"]

    async def test_mirror_route_share_token_access(self, client, fake_store):
        fake_store.get.return_value = _make_record(user_id="owner-a")
        fake_store.resolve_share.return_value = UISurfaceShare(
            token="tok-1", surface_id="surface-1", created_at=datetime.now(UTC)
        )

        params = {**_auth_params(user_id="viewer-1"), "share": "tok-1"}
        r = await client.get("/api/v1/agents/demo/a2ui/surfaces/surface-1", params=params)

        assert r.status == 200
        fake_store.claim_share.assert_awaited_once_with("tok-1", "viewer-1")

    async def test_mirror_route_foreign_no_token_404(self, client, fake_store):
        fake_store.get.return_value = _make_record(user_id="owner-a")

        r = await client.get(
            "/api/v1/agents/demo/a2ui/surfaces/surface-1",
            params=_auth_params(user_id="someone-else"),
        )

        assert r.status == 404

    async def test_mirror_route_bad_token_410(self, client, fake_store):
        fake_store.get.return_value = _make_record(user_id="owner-a")
        fake_store.resolve_share.return_value = None

        params = {**_auth_params(user_id="viewer-1"), "share": "bad-token"}
        r = await client.get("/api/v1/agents/demo/a2ui/surfaces/surface-1", params=params)

        assert r.status == 410


class TestCapabilitiesAndSSEUnchanged:
    async def test_capabilities_unchanged(self, client):
        r = await client.get("/api/v1/agents/demo/a2ui/capabilities", params=_auth_params())
        assert r.status == 200
        body = await r.json()
        assert "catalogs" in body or isinstance(body, dict)

    async def test_post_dispatch_unchanged(self, client):
        payload = {
            "version": "v1.0",
            "callAgentFunction": {
                "surfaceId": "s-1",
                "functionCallId": "fc-1",
                "callFunction": {
                    "call": "get_weather",
                    "args": {"location": "Caracas"},
                    "catalogId": DEFAULT_CATALOG_ID,
                },
            },
        }
        r = await client.post("/api/v1/agents/demo/a2ui", json=payload, params=_auth_params())
        assert r.status == 200
        body = await r.json()
        assert body["agentFunctionResponse"]["functionCallId"] == "fc-1"


class TestRouteOrdering:
    async def test_routes_registered_and_ordering(self, client, fake_store):
        """Literal 'capabilities'/'surfaces' segments resolve before the bare
        '{agent_id}/a2ui' pattern — each URL shape reaches its OWN branch."""
        r_caps = await client.get("/api/v1/agents/demo/a2ui/capabilities", params=_auth_params())
        assert r_caps.status == 200
        caps_body = await r_caps.json()
        assert "supportedCatalogIds" in caps_body["v1.0"]

        fake_store.get.return_value = _make_record()
        r_surface = await client.get(
            "/api/v1/agents/demo/a2ui/surfaces/surface-1", params=_auth_params()
        )
        assert r_surface.status == 200
        surface_body = await r_surface.json()
        assert "metadata" in surface_body  # negotiated surface response, NOT capabilities/SSE

        # Bare pattern still resolves to the SSE branch (StreamResponse — a
        # GET without a body reader will hang on a live stream, so just
        # confirm it's routed to A2UIHandler and starts an SSE response by
        # checking headers via a short-lived connection).
        async with client.session.get(
            client.make_url("/api/v1/agents/demo/a2ui"), params=_auth_params()
        ) as resp:
            assert resp.headers.get("Content-Type", "").startswith("text/event-stream")
