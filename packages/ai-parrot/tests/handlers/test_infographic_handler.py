"""Tests for InfographicTalk HTTP handler (FEAT-095).

Covers:
- Content negotiation (HTML default, explicit HTML, JSON, ?format= param)
- Template list / get / not-found endpoints
- Theme list / get / not-found endpoints
- Template/theme registration paths (global accepted, session denied, invalid)
- Integration: register then generate
- BotManager route registration smoke test
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch
from aiohttp import web

from parrot.models.infographic import (
    InfographicResponse,
    TitleBlock,
    SummaryBlock,
    ChartBlock,
    ChartDataSeries,
    ChartType,
    ThemeConfig,
    theme_registry,
)
from parrot.models.infographic_templates import (
    InfographicTemplate,
    infographic_registry,
)
from parrot.models.responses import AIMessage


# ── Fixtures ───────────────────────────────────────────────────────────────

@pytest.fixture
def sample_infographic_response():
    """A canned InfographicResponse for mocking."""
    return InfographicResponse(
        template="basic",
        theme="light",
        blocks=[
            TitleBlock(type="title", title="Mock Report"),
            SummaryBlock(type="summary", content="**bold** summary"),
            ChartBlock(
                type="chart",
                chart_type=ChartType.BAR,
                title="Sales",
                labels=["Q1", "Q2"],
                series=[ChartDataSeries(name="2025", values=[100, 200])],
            ),
        ],
    )


@pytest.fixture
def mock_agent(sample_infographic_response):
    """A MagicMock agent whose get_infographic() returns a canned AIMessage."""
    agent = MagicMock()
    agent.name = "test_agent"

    async def _get_infographic(question, accept="text/html", **kw):
        msg = AIMessage(input=question, output=sample_infographic_response)
        msg.structured_output = sample_infographic_response
        if accept == "text/html":
            msg.content = "<html><body><h1>Mock</h1></body></html>"
        return msg

    agent.get_infographic = _get_infographic
    return agent


@pytest.fixture
async def client(mock_agent, aiohttp_client):
    """TestClient with a test subclass of InfographicTalk.

    The conftest loads InfographicTalk with auth decorators replaced by
    no-ops, so post/get are plain undecorated coroutines.  This subclass
    only needs to override PBAC / agent / session helpers to inject stubs.
    """
    from parrot.handlers.infographic import InfographicTalk

    _captured_agent = mock_agent

    class _TestInfographicTalk(InfographicTalk):
        """Auth-bypass subclass for testing."""

        async def _check_pbac_agent_access(
            self, agent_id: str, action: str = "agent:chat"
        ):
            return None  # always allow

        async def _get_agent(self, data):
            return _captured_agent

        async def _get_user_session(self, data):
            return ("test_user", "test_session")

    app = web.Application()
    app.router.add_view(
        "/api/v1/agents/infographic/{resource:templates}",
        _TestInfographicTalk,
    )
    app.router.add_view(
        "/api/v1/agents/infographic/{resource:templates}/{template_name}",
        _TestInfographicTalk,
    )
    app.router.add_view(
        "/api/v1/agents/infographic/{resource:themes}",
        _TestInfographicTalk,
    )
    app.router.add_view(
        "/api/v1/agents/infographic/{resource:themes}/{theme_name}",
        _TestInfographicTalk,
    )
    app.router.add_view(
        "/api/v1/agents/infographic/{agent_id}",
        _TestInfographicTalk,
    )
    yield await aiohttp_client(app)


# ── Content Negotiation Tests ──────────────────────────────────────────────

class TestGenerateContentNegotiation:
    async def test_default_returns_html(self, client):
        resp = await client.post(
            "/api/v1/agents/infographic/test_agent",
            json={"query": "Analyze Q4 2025"},
        )
        assert resp.status == 200
        assert resp.content_type == "text/html"
        body = await resp.text()
        assert "<html" in body.lower()

    async def test_accept_html_explicit(self, client):
        resp = await client.post(
            "/api/v1/agents/infographic/test_agent",
            json={"query": "foo"},
            headers={"Accept": "text/html"},
        )
        assert resp.status == 200
        assert resp.content_type == "text/html"

    async def test_accept_json(self, client):
        resp = await client.post(
            "/api/v1/agents/infographic/test_agent",
            json={"query": "foo"},
            headers={"Accept": "application/json"},
        )
        assert resp.status == 200
        assert resp.content_type == "application/json"
        data = await resp.json()
        assert "infographic" in data
        assert data["infographic"]["template"] == "basic"
        assert len(data["infographic"]["blocks"]) == 3

    async def test_format_query_param_wins_over_accept_header(self, client):
        resp = await client.post(
            "/api/v1/agents/infographic/test_agent?format=json",
            json={"query": "foo"},
            headers={"Accept": "text/html"},
        )
        assert resp.status == 200
        assert resp.content_type == "application/json"

    async def test_format_html_explicit(self, client):
        resp = await client.post(
            "/api/v1/agents/infographic/test_agent?format=html",
            json={"query": "foo"},
            headers={"Accept": "application/json"},
        )
        assert resp.status == 200
        assert resp.content_type == "text/html"

    async def test_missing_query_returns_400(self, client):
        resp = await client.post(
            "/api/v1/agents/infographic/test_agent",
            json={},
        )
        assert resp.status == 400


# ── Template Endpoint Tests ────────────────────────────────────────────────

class TestTemplateEndpoints:
    async def test_list_templates(self, client):
        resp = await client.get("/api/v1/agents/infographic/templates")
        assert resp.status == 200
        data = await resp.json()
        assert "templates" in data
        assert "basic" in data["templates"]
        assert isinstance(data["templates"], list)

    async def test_list_templates_detailed(self, client):
        resp = await client.get(
            "/api/v1/agents/infographic/templates?detailed=true"
        )
        assert resp.status == 200
        data = await resp.json()
        assert all("description" in t for t in data["templates"])

    async def test_get_template_by_name(self, client):
        resp = await client.get("/api/v1/agents/infographic/templates/basic")
        assert resp.status == 200
        data = await resp.json()
        assert data["template"]["name"] == "basic"
        assert "block_specs" in data["template"]

    async def test_get_template_not_found(self, client):
        resp = await client.get(
            "/api/v1/agents/infographic/templates/no_such_template_xyz"
        )
        assert resp.status == 404


# ── Theme Endpoint Tests ───────────────────────────────────────────────────

class TestThemeEndpoints:
    async def test_list_themes(self, client):
        resp = await client.get("/api/v1/agents/infographic/themes")
        assert resp.status == 200
        data = await resp.json()
        assert set(["light", "dark", "corporate"]).issubset(set(data["themes"]))

    async def test_list_themes_detailed(self, client):
        resp = await client.get(
            "/api/v1/agents/infographic/themes?detailed=true"
        )
        assert resp.status == 200
        data = await resp.json()
        assert all("primary" in t for t in data["themes"])

    async def test_get_theme_by_name(self, client):
        resp = await client.get("/api/v1/agents/infographic/themes/dark")
        assert resp.status == 200
        data = await resp.json()
        assert data["theme"]["name"] == "dark"
        assert "primary" in data["theme"]

    async def test_get_theme_not_found(self, client):
        resp = await client.get(
            "/api/v1/agents/infographic/themes/no_such_theme_xyz"
        )
        assert resp.status == 404


# ── Registration Path Tests ────────────────────────────────────────────────

class TestRegistrationPaths:
    async def test_register_template_global_scope_accepted(self, client):
        payload = {
            "template": {
                "name": "test_reg_tpl_integ",
                "description": "Integration test template",
                "block_specs": [],
            },
            "scope": "global",
        }
        try:
            resp = await client.post(
                "/api/v1/agents/infographic/templates",
                json=payload,
            )
            assert resp.status == 201
            data = await resp.json()
            assert data["template"]["name"] == "test_reg_tpl_integ"
        finally:
            infographic_registry._templates.pop("test_reg_tpl_integ", None)

    async def test_register_template_session_scope_denied(self, client):
        resp = await client.post(
            "/api/v1/agents/infographic/templates",
            json={
                "template": {
                    "name": "x",
                    "description": "d",
                    "block_specs": [],
                },
                "scope": "session",
            },
        )
        assert resp.status == 403

    async def test_register_template_invalid_payload(self, client):
        resp = await client.post(
            "/api/v1/agents/infographic/templates",
            json={"template": {"name": "only_name_no_desc"}},
        )
        assert resp.status == 400
        data = await resp.json()
        assert "error" in data

    async def test_register_template_missing_template_field(self, client):
        resp = await client.post(
            "/api/v1/agents/infographic/templates",
            json={"scope": "global"},
        )
        assert resp.status == 400

    async def test_register_theme_global_scope_accepted(self, client):
        try:
            resp = await client.post(
                "/api/v1/agents/infographic/themes",
                json={"theme": {"name": "test_reg_theme_integ"}, "scope": "global"},
            )
            assert resp.status == 201
            data = await resp.json()
            assert data["theme"]["name"] == "test_reg_theme_integ"
        finally:
            theme_registry._themes.pop("test_reg_theme_integ", None)

    async def test_register_theme_session_scope_denied(self, client):
        resp = await client.post(
            "/api/v1/agents/infographic/themes",
            json={"theme": {"name": "x"}, "scope": "session"},
        )
        assert resp.status == 403

    async def test_register_theme_missing_theme_field(self, client):
        resp = await client.post(
            "/api/v1/agents/infographic/themes",
            json={"scope": "global"},
        )
        assert resp.status == 400


# ── Integration: Register Then Generate ───────────────────────────────────

class TestIntegrationRegisterThenGenerate:
    async def test_register_then_generate_uses_new_template(
        self, client, mock_agent
    ):
        """Register a custom template, then generate with it; assert call."""
        captured = {}

        async def _capture_get_infographic(question, **kw):
            captured["template"] = kw.get("template")
            msg = AIMessage(input=question, output="<html>ok</html>")
            msg.content = "<html>ok</html>"
            return msg

        mock_agent.get_infographic = _capture_get_infographic

        try:
            reg = await client.post(
                "/api/v1/agents/infographic/templates",
                json={
                    "template": {
                        "name": "test_integ_tpl_2",
                        "description": "integ",
                        "block_specs": [],
                    },
                    "scope": "global",
                },
            )
            assert reg.status == 201

            gen = await client.post(
                "/api/v1/agents/infographic/test_agent",
                json={"query": "foo", "template": "test_integ_tpl_2"},
            )
            assert gen.status == 200
            assert captured.get("template") == "test_integ_tpl_2"
        finally:
            infographic_registry._templates.pop("test_integ_tpl_2", None)


# ── Routes Registered via BotManager.setup_app ─────────────────────────────

def test_bot_manager_registers_infographic_routes():
    """Smoke-check that BotManager.setup_app adds all new infographic routes.

    Skips gracefully if BotManager cannot be instantiated without external
    resources (DB, Redis).
    """
    try:
        from parrot.manager.manager import BotManager
    except Exception as exc:
        pytest.skip(f"BotManager import failed: {exc}")

    app = web.Application()
    manager = BotManager()
    try:
        manager.setup_app(app)
    except Exception as exc:
        pytest.skip(f"BotManager.setup_app requires full bootstrap: {exc}")

    paths = {r.canonical for r in app.router.resources()}
    expected_substrings = [
        "/api/v1/agents/infographic/templates",
        "/api/v1/agents/infographic/themes",
        "/api/v1/agents/infographic/{agent_id}",
    ]
    for substr in expected_substrings:
        assert any(substr in p for p in paths), f"Route missing from app: {substr}"


# ── Subclass Integrity ────────────────────────────────────────────────────

def test_infographic_talk_is_subclass_of_agent_talk():
    """Verify InfographicTalk inherits from AgentTalk."""
    from parrot.handlers.infographic import InfographicTalk
    from parrot.handlers.agent import AgentTalk

    assert issubclass(InfographicTalk, AgentTalk)
    assert InfographicTalk._logger_name == "Parrot.InfographicTalk"


def test_infographic_talk_does_not_redefine_pbac_helpers():
    """Verify PBAC/session helpers are NOT redefined on InfographicTalk."""
    from parrot.handlers.infographic import InfographicTalk
    from parrot.handlers.agent import AgentTalk

    for attr in ("_check_pbac_agent_access", "_get_agent", "_get_user_session",
                 "_get_agent_name"):
        assert attr not in InfographicTalk.__dict__, (
            f"{attr} should not be redefined on InfographicTalk "
            f"(inherited from AgentTalk)"
        )
