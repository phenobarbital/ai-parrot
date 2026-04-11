# TASK-652: InfographicTalk Handler Tests

**Feature**: get-infographic-handler
**Spec**: `sdd/specs/get-infographic-handler.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-649, TASK-650, TASK-651
**Assigned-to**: unassigned

---

## Context

Final validation task for FEAT-095. Covers unit and integration tests for
the `InfographicTalk` handler, content negotiation, template/theme
endpoints, registration paths, and route registration, per the spec's
Test Specification (§4).

Implements **Module 4** of the spec.

---

## Scope

- Create `packages/ai-parrot/tests/handlers/test_infographic_handler.py`
  with the full unit test suite listed in the spec (Test Specification §4).
- Cover the three content negotiation paths (HTML default, HTML explicit,
  JSON), missing query / agent errors, PBAC denials, and both
  template/theme GET + register flows.
- Include integration tests that:
    1. Mock an agent whose `get_infographic()` returns a canned
       `AIMessage` wrapping a synthetic `InfographicResponse`.
    2. Exercise the full aiohttp app via `aiohttp.test_utils.TestClient`.
    3. Verify `BotManager.setup_app()` registers all five new routes.
- Use the existing `packages/ai-parrot/tests/handlers/` directory
  (confirmed to exist per spec scaffolding).
- Tests must pass under the activated venv using `pytest`.

**NOT in scope**:
- Testing `get_infographic()` itself (already covered by FEAT-094's
  TASK-648).
- Testing `ThemeRegistry.list_themes_detailed` (covered by TASK-649's
  helper tests).
- Load/performance tests.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/handlers/test_infographic_handler.py` | CREATE | Unit + integration tests per spec §4 |
| `packages/ai-parrot/tests/handlers/conftest.py` | MODIFY (if exists) or CREATE | Shared fixtures for mock agent and `aiohttp_client` if needed |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from parrot.handlers.infographic import InfographicTalk
# verified: created by TASK-650

from parrot.handlers.agent import AgentTalk
# verified: packages/ai-parrot/src/parrot/handlers/agent.py:47

from parrot.manager.manager import BotManager
# verified: packages/ai-parrot/src/parrot/manager/manager.py

from parrot.helpers.infographics import (
    list_templates, get_template, register_template,
    list_themes, get_theme, register_theme,
)  # verified: created by TASK-649

from parrot.models.infographic import (
    InfographicResponse,
    TitleBlock, SummaryBlock, ChartBlock, ChartDataSeries, ChartType,
    ThemeConfig, theme_registry,
)  # verified: packages/ai-parrot/src/parrot/models/infographic.py
from parrot.models.infographic_templates import (
    InfographicTemplate, infographic_registry,
)  # verified: packages/ai-parrot/src/parrot/models/infographic_templates.py

from parrot.models.responses import AIMessage
# verified: packages/ai-parrot/src/parrot/models/responses.py
```

### Existing Signatures to Use

```python
# Mocking the authentication decorators
# AgentTalk is decorated with @is_authenticated() and @user_session().
# For unit tests of handler internals, bypass these by instantiating the
# view directly with a fake request, OR patch navigator_auth at import
# time inside a conftest fixture.

# Canonical fixture pattern from other parrot handler tests:
# 1. Build a web.Application
# 2. Register routes with a test-only InfographicTalk variant that skips PBAC
# 3. Use aiohttp.test_utils.TestClient to issue requests

# InfographicTalk dispatch signature (from TASK-650):
# - match_info["resource"] == "templates" | "themes" — literal sub-paths
# - match_info["agent_id"] — catch-all per-agent generation
# - match_info["template_name"] / match_info["theme_name"] — single-entity GET
```

### Does NOT Exist
- ~~`parrot.tests.fixtures.mock_agent`~~ — no such shared fixture; write
  one locally.
- ~~`parrot.handlers.infographic.InfographicTalk.generate`~~ — no such
  method; the public surface is `post` / `get`.
- ~~A pre-existing `aiohttp_app` fixture~~ — check `conftest.py` before
  assuming; otherwise create one per-test.

---

## Implementation Notes

### Test Organisation

```python
# packages/ai-parrot/tests/handlers/test_infographic_handler.py

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from parrot.models.infographic import (
    InfographicResponse, TitleBlock, SummaryBlock, ChartBlock,
    ChartDataSeries, ChartType,
)
from parrot.models.responses import AIMessage


# ── Fixtures ───────────────────────────────────────────────────────────

@pytest.fixture
def sample_infographic_response():
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
    """AsyncMock agent with get_infographic() that returns a canned AIMessage."""
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
    """TestClient with InfographicTalk routes and PBAC/auth bypassed."""
    from parrot.handlers.infographic import InfographicTalk

    # Patch PBAC and auth for tests
    async def _no_pbac(self, agent_id, action="agent:chat"):
        return None

    async def _fake_get_agent(self, data):
        return mock_agent

    async def _fake_session(self, data):
        return ("test_user", "test_session")

    with patch.object(InfographicTalk, "_check_pbac_agent_access", _no_pbac), \
         patch.object(InfographicTalk, "_get_agent", _fake_get_agent), \
         patch.object(InfographicTalk, "_get_user_session", _fake_session):
        app = web.Application()
        # Register routes in the same order as manager.py
        app.router.add_view(
            "/api/v1/agents/infographic/{resource:templates}",
            InfographicTalk,
        )
        app.router.add_view(
            "/api/v1/agents/infographic/{resource:templates}/{template_name}",
            InfographicTalk,
        )
        app.router.add_view(
            "/api/v1/agents/infographic/{resource:themes}",
            InfographicTalk,
        )
        app.router.add_view(
            "/api/v1/agents/infographic/{resource:themes}/{theme_name}",
            InfographicTalk,
        )
        app.router.add_view(
            "/api/v1/agents/infographic/{agent_id}",
            InfographicTalk,
        )
        yield await aiohttp_client(app)


# ── Content Negotiation Tests ──────────────────────────────────────────

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
        assert resp.content_type == "text/html"

    async def test_accept_json(self, client):
        resp = await client.post(
            "/api/v1/agents/infographic/test_agent",
            json={"query": "foo"},
            headers={"Accept": "application/json"},
        )
        assert resp.status == 200
        data = await resp.json()
        assert "infographic" in data
        assert data["infographic"]["template"] == "basic"
        assert len(data["infographic"]["blocks"]) == 3

    async def test_format_query_param_wins(self, client):
        resp = await client.post(
            "/api/v1/agents/infographic/test_agent?format=json",
            json={"query": "foo"},
            headers={"Accept": "text/html"},
        )
        assert resp.content_type == "application/json"

    async def test_missing_query_returns_400(self, client):
        resp = await client.post(
            "/api/v1/agents/infographic/test_agent",
            json={},
        )
        assert resp.status == 400


# ── Template Endpoint Tests ────────────────────────────────────────────

class TestTemplateEndpoints:
    async def test_list_templates(self, client):
        resp = await client.get("/api/v1/agents/infographic/templates")
        assert resp.status == 200
        data = await resp.json()
        assert "templates" in data
        assert "basic" in data["templates"]

    async def test_list_templates_detailed(self, client):
        resp = await client.get(
            "/api/v1/agents/infographic/templates?detailed=true"
        )
        data = await resp.json()
        assert all("description" in t for t in data["templates"])

    async def test_get_template_by_name(self, client):
        resp = await client.get("/api/v1/agents/infographic/templates/basic")
        assert resp.status == 200
        data = await resp.json()
        assert data["template"]["name"] == "basic"
        assert "block_specs" in data["template"]  # full model_dump

    async def test_get_template_not_found(self, client):
        resp = await client.get(
            "/api/v1/agents/infographic/templates/no_such_template"
        )
        assert resp.status == 404


# ── Theme Endpoint Tests ───────────────────────────────────────────────

class TestThemeEndpoints:
    async def test_list_themes(self, client):
        resp = await client.get("/api/v1/agents/infographic/themes")
        data = await resp.json()
        assert set(["light", "dark", "corporate"]).issubset(set(data["themes"]))

    async def test_get_theme_by_name(self, client):
        resp = await client.get("/api/v1/agents/infographic/themes/dark")
        data = await resp.json()
        assert data["theme"]["name"] == "dark"
        assert "primary" in data["theme"]

    async def test_get_theme_not_found(self, client):
        resp = await client.get(
            "/api/v1/agents/infographic/themes/no_such_theme"
        )
        assert resp.status == 404


# ── Registration Path Tests (v1 behaviour) ─────────────────────────────

class TestRegistrationPaths:
    async def test_register_template_global_scope_accepted(self, client):
        payload = {
            "template": {
                "name": "test_reg_template",
                "description": "desc",
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
            assert data["template"]["name"] == "test_reg_template"
        finally:
            # cleanup global registry
            from parrot.models.infographic_templates import infographic_registry
            infographic_registry._templates.pop("test_reg_template", None)

    async def test_register_template_session_scope_denied(self, client):
        resp = await client.post(
            "/api/v1/agents/infographic/templates",
            json={"template": {"name": "x", "description": "d", "block_specs": []},
                  "scope": "session"},
        )
        assert resp.status == 403

    async def test_register_template_invalid_payload(self, client):
        resp = await client.post(
            "/api/v1/agents/infographic/templates",
            json={"template": {"name": "only_name"}},
        )
        assert resp.status == 400
        data = await resp.json()
        assert "error" in data

    async def test_register_theme_global_scope_accepted(self, client):
        try:
            resp = await client.post(
                "/api/v1/agents/infographic/themes",
                json={"theme": {"name": "test_reg_theme"}, "scope": "global"},
            )
            assert resp.status == 201
        finally:
            from parrot.models.infographic import theme_registry
            theme_registry._themes.pop("test_reg_theme", None)

    async def test_register_theme_session_scope_denied(self, client):
        resp = await client.post(
            "/api/v1/agents/infographic/themes",
            json={"theme": {"name": "x"}, "scope": "session"},
        )
        assert resp.status == 403


# ── Integration: Generate after Register ───────────────────────────────

class TestIntegrationRegisterThenGenerate:
    async def test_register_then_generate_uses_new_template(self, client, mock_agent):
        """Register a custom template, then invoke generation with it."""
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
                        "name": "test_integ_tpl",
                        "description": "integ",
                        "block_specs": [],
                    },
                    "scope": "global",
                },
            )
            assert reg.status == 201
            gen = await client.post(
                "/api/v1/agents/infographic/test_agent",
                json={"query": "foo", "template": "test_integ_tpl"},
            )
            assert gen.status == 200
            assert captured["template"] == "test_integ_tpl"
        finally:
            from parrot.models.infographic_templates import infographic_registry
            infographic_registry._templates.pop("test_integ_tpl", None)


# ── Routes Registered via BotManager.setup_app ─────────────────────────

def test_bot_manager_registers_infographic_routes():
    """Smoke-check that BotManager.setup_app adds all five new routes.

    If BotManager.setup_app requires external resources (DB, Redis), skip
    with an explanatory reason.
    """
    try:
        from parrot.manager.manager import BotManager
    except Exception as exc:  # pragma: no cover
        pytest.skip(f"BotManager import failed: {exc}")

    app = web.Application()
    manager = BotManager()
    try:
        manager.setup_app(app)
    except Exception as exc:  # pragma: no cover
        pytest.skip(f"BotManager.setup_app requires bootstrap: {exc}")

    paths = {r.canonical for r in app.router.resources()}
    expected_substrings = [
        "/api/v1/agents/infographic/templates",
        "/api/v1/agents/infographic/themes",
        "/api/v1/agents/infographic/{agent_id}",
    ]
    for substr in expected_substrings:
        assert any(substr in p for p in paths), f"Route missing: {substr}"
```

### Key Constraints

- Use `aiohttp_client` pytest fixture (provided by `pytest-aiohttp`).
  Verify it is available; if not, the monorepo pyproject.toml already
  declares it via ai-parrot test dependencies.
- Do NOT instantiate `BotManager` with live DB/Redis dependencies; if
  `setup_app` can't run cleanly in test mode, use `pytest.skip` inside
  the routes-registered test and rely on the direct handler tests.
- Clean up every globally-registered test template/theme in a `finally`
  block or an `autouse` fixture to avoid cross-test pollution.
- Use `pytest-asyncio` markers (`async def test_...`) consistent with
  other `tests/handlers/` files. Check the existing handler test style
  before starting.

### References in Codebase

- `packages/ai-parrot/tests/handlers/` — look for existing `conftest.py`
  and test files to match style, fixture naming, and pytest markers.
- `packages/ai-parrot/src/parrot/handlers/infographic.py` — target of
  the tests (delivered by TASK-650).

---

## Acceptance Criteria

- [ ] `pytest packages/ai-parrot/tests/handlers/test_infographic_handler.py -v`
      completes with all tests passing.
- [ ] Content negotiation tests cover HTML default, explicit HTML, JSON,
      and `?format=json` override.
- [ ] Template list / get / not-found tests all present and green.
- [ ] Theme list / get / not-found tests all present and green.
- [ ] Registration tests cover global-accept, session-deny, and invalid
      payload paths for BOTH templates and themes.
- [ ] Integration test "register-then-generate" runs and asserts the
      mocked `get_infographic` was called with the new template name.
- [ ] Routes-registered test passes OR cleanly skips with an explanatory
      reason.
- [ ] No test leaves custom entries behind in `infographic_registry` or
      `theme_registry` (assert cleanup by listing registry contents at
      session end).
- [ ] No linting errors on the new test file: `ruff check packages/ai-parrot/tests/handlers/test_infographic_handler.py`.

---

## Agent Instructions

1. Read the spec §4 and TASK-650 for the exact HTTP contract.
2. Verify TASK-649, TASK-650, TASK-651 are all `done` in
   `sdd/tasks/.index.json`.
3. Activate the venv (`source .venv/bin/activate`) before running any
   pytest command.
4. Update status in `sdd/tasks/.index.json` → `"in-progress"`.
5. Implement the test file per the scaffold above, adapting fixture
   style to whatever already exists in `packages/ai-parrot/tests/handlers/`.
6. Run the full test file and ensure it passes. Fix handler bugs found
   here by pushing small commits back into the relevant prior task's code
   (the fix belongs with the component, not with the test task).
7. Verify acceptance criteria.
8. Move this file to `sdd/tasks/completed/TASK-652-handler-tests.md` and
   update index → `"done"`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
