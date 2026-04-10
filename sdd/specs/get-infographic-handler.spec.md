# Feature Specification: get_infographic HTTP Handler

**Feature ID**: FEAT-095
**Date**: 2026-04-10
**Author**: Jesus Lara
**Status**: draft
**Target version**: 1.x

---

## 1. Motivation & Business Requirements

### Problem Statement

FEAT-094 introduced `AbstractBot.get_infographic()` — a method that produces
structured `InfographicResponse` blocks via the LLM and optionally renders them
to self-contained HTML through `InfographicHTMLRenderer`. It also shipped an
`InfographicTemplateRegistry` and a `ThemeRegistry` with built-in entries
(templates: `basic`, `executive`, `dashboard`, `comparison`, `timeline_report`,
`minimal`; themes: `light`, `dark`, `corporate`).

However, this capability is only reachable programmatically. There is no HTTP
surface: frontend clients cannot trigger `get_infographic()`, cannot discover
which templates or themes are available, and cannot contribute custom templates
or themes at runtime. Today they must hit the generic `AgentTalk` POST endpoint
with `output_mode=infographic` kludges, which bypasses template enforcement and
theme negotiation entirely.

We need a dedicated HTTP handler in `parrot/handlers/` — associated with and
reusing machinery from `AgentTalk` — that exposes `get_infographic()` as a
first-class endpoint, plus discovery/registration endpoints for templates and
themes, plus a small helper module so SDK users can list or register templates
and themes without reaching into `parrot.models.infographic_templates`.

### Goals
- Expose `bot.get_infographic()` through a dedicated HTTP endpoint that honours
  content negotiation (`Accept: text/html` → HTML, `Accept: application/json` →
  `InfographicResponse` JSON), matching the behaviour already built into the
  bot method.
- Provide GET endpoints to list available infographic templates and themes,
  with both summary and detailed views.
- Provide POST endpoints to register custom templates and themes at runtime.
  Custom entries may be **global** (process-wide registry) or **session-scoped**
  (isolated per user session, mirroring the `{agent_id}_tool_manager` pattern
  in `AgentTalk`).
- Provide a lightweight helper module (`parrot/helpers/infographics.py`) with
  pure-Python functions (`list_templates`, `get_template`, `register_template`,
  `list_themes`, `get_theme`, `register_theme`) so SDK consumers don't need to
  import registry singletons directly.
- Reuse `AgentTalk`'s existing authentication, PBAC guards, agent lookup, and
  session management — do **not** duplicate `_check_pbac_agent_access`,
  `_get_agent`, `_get_user_session`.

### Non-Goals (explicitly out of scope)
- Changing `InfographicHTMLRenderer` output, `get_infographic()` signature,
  or any block models from FEAT-094.
- Persisting custom templates / themes beyond in-memory (no database). Session
  storage is the only persistence mechanism in this feature.
- Frontend UI for template/theme management (separate navigator-frontend-next
  task).
- WebSocket streaming of partial infographic blocks — the endpoint is
  request/response only.
- A dedicated OpenAPI schema wiring beyond what the rest of AI-Parrot handlers
  provide.
- PDF, PNG, or SVG export of the rendered infographic.

---

## 2. Architectural Design

### Overview

A new handler class `InfographicTalk` lives in
`packages/ai-parrot/src/parrot/handlers/infographic.py`. It **inherits** from
`AgentTalk` so it reuses authentication decorators, `_get_agent`,
`_get_user_session`, `_check_pbac_agent_access`, and the post_init logger.
Inheritance (instead of composition) is the pattern already used across
parrot handlers that need the same auth/PBAC/session machinery.

The handler overrides only the HTTP verbs: `post`, `get`, and `put`. It
dispatches on the URL shape (`match_info`) to route between:
- generate infographic (`POST /api/v1/agents/infographic/{agent_id}`)
- list templates/themes (`GET /api/v1/agents/infographic/templates`,
  `GET /api/v1/agents/infographic/themes`)
- get one template/theme (`GET .../templates/{name}`, `GET .../themes/{name}`)
- register custom template/theme (`POST .../templates`, `POST .../themes`)

Two helper modules act as thin façades so registry singletons stay
encapsulated:
- `parrot/helpers/infographics.py` — pure sync functions over
  `infographic_registry` and `theme_registry`. Used by the handler and
  exposed for SDK consumers.

### Component Diagram
```
Client HTTP
    │
    ▼
InfographicTalk (extends AgentTalk)
    │
    ├── POST /api/v1/agents/infographic/{agent_id}
    │       └──→ _get_agent() → bot.get_infographic(accept=<negotiated>) → HTML | JSON
    │
    ├── GET /api/v1/agents/infographic/templates[/{name}]
    │       └──→ helpers.list_templates() | helpers.get_template(name)
    │
    ├── GET /api/v1/agents/infographic/themes[/{name}]
    │       └──→ helpers.list_themes() | helpers.get_theme(name)
    │
    ├── POST /api/v1/agents/infographic/templates
    │       └──→ helpers.register_template(payload, scope=global|session)
    │
    └── POST /api/v1/agents/infographic/themes
            └──→ helpers.register_theme(payload, scope=global|session)

parrot/helpers/infographics.py
    └──→ infographic_registry (parrot/models/infographic_templates.py)
    └──→ theme_registry        (parrot/models/infographic.py)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `AgentTalk` | inherits from | Reuse `_get_agent`, `_get_user_session`, `_check_pbac_agent_access`, `post_init`, PBAC decorators |
| `AbstractBot.get_infographic` | calls | Bot method from FEAT-094 — used as-is with the `accept` parameter |
| `InfographicTemplateRegistry` | uses via helpers | `register`, `get`, `list_templates`, `list_templates_detailed` already exist |
| `ThemeRegistry` | uses via helpers | `register`, `get`, `list_themes` already exist; `list_themes_detailed` is added |
| `InfographicTemplate` model | deserializes | JSON payloads are validated via `InfographicTemplate.model_validate` |
| `ThemeConfig` model | deserializes | JSON payloads are validated via `ThemeConfig.model_validate` |
| `BotManager.setup_app()` | registers routes | New routes added next to the existing `AgentTalk` routes |
| `navigator_auth` decorators | applied | `@is_authenticated()`, `@user_session()` inherited from `AgentTalk` |

### Data Models

No new Pydantic models are introduced. The handler accepts the existing
`InfographicTemplate` and `ThemeConfig` JSON shapes.

Request body shapes (documented, not new models):

```python
# POST /api/v1/agents/infographic/{agent_id}
{
    "query": "Analyze Q4 2025 sales performance",
    "template": "executive",              # optional, default "basic"
    "theme": "corporate",                 # optional
    "session_id": "optional-session-id",
    "user_id": "optional-user-id",
    "use_vector_context": True,
    "use_conversation_history": False,
    "scope": "global"                     # optional for template/theme registration
}

# POST /api/v1/agents/infographic/templates
{
    "template": {
        "name": "my_quarterly_report",
        "description": "...",
        "block_specs": [...],
        "default_theme": "light"
    },
    "scope": "session"   # or "global" — defaults to "session"
}

# POST /api/v1/agents/infographic/themes
{
    "theme": {
        "name": "sunset",
        "primary": "#ff6b35",
        ...
    },
    "scope": "session"
}
```

### New Public Interfaces

```python
# parrot/handlers/infographic.py
@is_authenticated()
@user_session()
class InfographicTalk(AgentTalk):
    """HTTP handler for get_infographic() with template/theme discovery
    and registration endpoints."""

    _logger_name: str = "Parrot.InfographicTalk"

    async def post(self) -> web.Response: ...
    async def get(self) -> web.Response: ...
    async def put(self) -> web.Response: ...   # optional: update existing template

    # Internal dispatch helpers
    async def _generate_infographic(self, agent_id: str) -> web.Response: ...
    async def _handle_templates_get(self, name: Optional[str]) -> web.Response: ...
    async def _handle_themes_get(self, name: Optional[str]) -> web.Response: ...
    async def _handle_templates_register(self, data: dict) -> web.Response: ...
    async def _handle_themes_register(self, data: dict) -> web.Response: ...

    def _negotiate_accept(self) -> str: ...     # returns "text/html" or "application/json"
    def _session_registry_key(self, kind: str) -> str: ...

# parrot/helpers/infographics.py — SDK convenience functions
def list_templates(detailed: bool = False) -> list[str] | list[dict]: ...
def get_template(name: str) -> InfographicTemplate: ...
def register_template(template: InfographicTemplate | dict) -> InfographicTemplate: ...
def list_themes(detailed: bool = False) -> list[str] | list[dict]: ...
def get_theme(name: str) -> ThemeConfig: ...
def register_theme(theme: ThemeConfig | dict) -> ThemeConfig: ...
```

---

## 3. Module Breakdown

### Module 1: Helper Façade
- **Path**: `packages/ai-parrot/src/parrot/helpers/infographics.py`
- **Responsibility**: Thin functions that wrap `infographic_registry` and
  `theme_registry`. Validate dict inputs via Pydantic
  (`InfographicTemplate.model_validate`, `ThemeConfig.model_validate`).
  Provide `list_templates_detailed` / `list_themes_detailed`-style views. Add
  a new `ThemeRegistry.list_themes_detailed()` method on the model registry
  if it simplifies the helper (minimal extension).
- **Depends on**: `parrot.models.infographic_templates.infographic_registry`,
  `parrot.models.infographic.theme_registry`, `InfographicTemplate`,
  `ThemeConfig`.

### Module 2: InfographicTalk Handler
- **Path**: `packages/ai-parrot/src/parrot/handlers/infographic.py`
- **Responsibility**: Defines `InfographicTalk(AgentTalk)`. Implements
  `post`/`get`/`put` with dispatch based on `match_info` sub-paths. Generates
  infographics via `bot.get_infographic()` and returns either HTML or JSON
  based on the `Accept` header. Resolves session-scoped custom
  templates/themes from the aiohttp session and falls back to the global
  registry. Uses `self._check_pbac_agent_access` from the parent for PBAC
  (`agent:chat` for generation, `agent:configure` for registration).
- **Depends on**: Module 1 helpers, `AgentTalk` (inheritance),
  `AbstractBot.get_infographic`.

### Module 3: Route Registration
- **Path**: `packages/ai-parrot/src/parrot/manager/manager.py` (modify
  `setup_app`, around existing `AgentTalk` route block at line ~718)
- **Responsibility**: Register six routes under
  `/api/v1/agents/infographic`:
    - `POST /api/v1/agents/infographic/{agent_id}`
    - `GET  /api/v1/agents/infographic/templates`
    - `GET  /api/v1/agents/infographic/templates/{template_name}`
    - `POST /api/v1/agents/infographic/templates`
    - `GET  /api/v1/agents/infographic/themes`
    - `GET  /api/v1/agents/infographic/themes/{theme_name}`
    - `POST /api/v1/agents/infographic/themes`
- **Depends on**: Module 2.

### Module 4: Tests
- **Path**: `packages/ai-parrot/tests/handlers/test_infographic_handler.py`
  (new file; `tests/handlers/` already exists)
- **Responsibility**: Unit tests for each endpoint (content negotiation,
  template/theme list, registration, session-vs-global scope), helper
  validation, and an integration test that mocks `get_infographic()` and
  asserts HTML and JSON paths. Use `aiohttp.test_utils.TestClient` fixtures
  already present in the handler tests directory.
- **Depends on**: Modules 1-3.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_helpers_list_templates_names` | 1 | `list_templates()` returns sorted names of built-in templates |
| `test_helpers_list_templates_detailed` | 1 | `list_templates(detailed=True)` returns name+description dicts |
| `test_helpers_get_template_known` | 1 | Returns the matching `InfographicTemplate` |
| `test_helpers_get_template_unknown` | 1 | Raises `KeyError` with available list in the message |
| `test_helpers_register_template_model` | 1 | Accepts an `InfographicTemplate` instance |
| `test_helpers_register_template_dict` | 1 | Accepts a raw dict, validates via pydantic |
| `test_helpers_register_template_invalid` | 1 | Raises `ValidationError` on malformed payload |
| `test_helpers_list_themes_names` | 1 | Returns `["corporate", "dark", "light"]` |
| `test_helpers_list_themes_detailed` | 1 | Returns dicts with name + key colours |
| `test_helpers_register_theme_model_and_dict` | 1 | Accepts both shapes; `get_theme()` returns it back |
| `test_handler_get_templates_list` | 2 | GET /templates returns JSON list; status 200 |
| `test_handler_get_templates_detailed` | 2 | `?detailed=true` returns detailed entries |
| `test_handler_get_template_by_name` | 2 | GET /templates/executive returns full block_specs |
| `test_handler_get_template_not_found` | 2 | Returns 404 with available-templates message |
| `test_handler_get_themes_list` | 2 | GET /themes returns theme names |
| `test_handler_get_theme_by_name` | 2 | GET /themes/dark returns full `ThemeConfig` fields |
| `test_handler_post_register_template_session_scope` | 2 | Stores into session under known key; does NOT touch global registry |
| `test_handler_post_register_template_global_scope` | 2 | Calls `helpers.register_template`; subsequent GET returns it |
| `test_handler_post_register_template_invalid_payload` | 2 | Returns 400 with Pydantic error summary |
| `test_handler_post_register_theme_session_scope` | 2 | Stores into session under known key; not in global registry |
| `test_handler_post_register_theme_global_scope` | 2 | Available via global registry afterwards |
| `test_handler_post_generate_html_default` | 2 | POST /{agent_id} with no Accept returns `text/html` body |
| `test_handler_post_generate_html_explicit` | 2 | `Accept: text/html` → HTML body, correct content-type |
| `test_handler_post_generate_json_accept` | 2 | `Accept: application/json` → JSON body with `InfographicResponse` |
| `test_handler_post_missing_query` | 2 | Returns 400 |
| `test_handler_post_missing_agent` | 2 | Returns 404 when agent not found (delegated to `_get_agent`) |
| `test_handler_post_uses_session_template` | 2 | Session-registered template takes precedence over global when looked up by name |
| `test_handler_post_uses_session_theme` | 2 | Session-registered theme is passed through to `get_infographic` |
| `test_handler_pbac_denied_on_generate` | 2 | 403 when `_check_pbac_agent_access('agent:chat')` denies |
| `test_handler_pbac_denied_on_register` | 2 | 403 when `_check_pbac_agent_access('agent:configure')` denies |

### Integration Tests

| Test | Description |
|---|---|
| `test_integration_generate_html_roundtrip` | Full pipeline with a mocked agent: POST → `get_infographic()` → HTML body contains `<html`, `--primary`, and an ECharts `<script>` when the mocked response includes a chart block |
| `test_integration_generate_json_roundtrip` | Same pipeline with `Accept: application/json` — body parses into a dict that matches the structure of `InfographicResponse` |
| `test_integration_register_then_generate` | Register a custom template via POST /templates, then POST /{agent_id} with that template name, and assert the mocked `get_infographic()` was called with the new template |
| `test_integration_routes_registered` | After `BotManager.setup_app()`, `app.router` exposes all six new routes |

### Test Data / Fixtures

```python
@pytest.fixture
def mock_agent_with_infographic(monkeypatch):
    """A mock AbstractBot whose get_infographic() returns a canned AIMessage."""
    from parrot.models.responses import AIMessage
    from parrot.models.infographic import (
        InfographicResponse, TitleBlock, SummaryBlock, ChartBlock, ChartDataSeries, ChartType,
    )

    response = InfographicResponse(
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

    class _MockAgent:
        name = "test_agent"
        async def get_infographic(self, question, **kw):
            msg = AIMessage(input=question, output=response)
            msg.structured_output = response
            return msg

    return _MockAgent()


@pytest.fixture
def custom_template_payload():
    return {
        "template": {
            "name": "custom_report",
            "description": "A user-defined quarterly report",
            "block_specs": [
                {"block_type": "title", "required": True, "description": "Report title"},
                {"block_type": "summary", "required": True, "description": "Executive summary"},
            ],
            "default_theme": "corporate",
        },
        "scope": "global",
    }
```

---

## 5. Acceptance Criteria

- [ ] All unit tests pass (`pytest packages/ai-parrot/tests/handlers/test_infographic_handler.py -v`)
- [ ] All integration tests pass
- [ ] `GET /api/v1/agents/infographic/templates` returns the 6 built-in templates
- [ ] `GET /api/v1/agents/infographic/themes` returns `light`, `dark`, `corporate`
- [ ] `POST /api/v1/agents/infographic/templates` with `scope: "global"` makes
      the new template immediately visible to all subsequent requests
- [ ] `POST /api/v1/agents/infographic/templates` with `scope: "session"`
      stores the template only in the user's aiohttp session
- [ ] `POST /api/v1/agents/infographic/{agent_id}` honours `Accept` header
      (HTML default; JSON when `Accept: application/json`)
- [ ] The handler inherits from `AgentTalk` and reuses its auth/PBAC/session
      machinery — **no duplication** of `_check_pbac_agent_access`,
      `_get_agent`, `_get_user_session`
- [ ] `parrot.helpers.infographics` exports the six helper functions and is
      importable via `from parrot.helpers.infographics import list_templates`
- [ ] Pydantic validation errors on register-template / register-theme return
      HTTP 400 with a clear error body — no 500s
- [ ] Routes registered in `BotManager.setup_app()` alongside the existing
      `AgentTalk` routes
- [ ] No breaking changes to `AgentTalk`, `get_infographic()`,
      `InfographicTemplateRegistry`, or `ThemeRegistry`

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> The references below were verified on 2026-04-10 against the current tip
> of `dev` (commit b660ce4c). Re-verify before modifying.

### Verified Imports

```python
# Handler / auth layer
from navigator.views import BaseView
from navigator_auth.decorators import is_authenticated, user_session
from navigator_session import get_session
# verified: packages/ai-parrot/src/parrot/handlers/agent.py:21-31

# Existing handler (parent class)
from parrot.handlers.agent import AgentTalk
# verified: packages/ai-parrot/src/parrot/handlers/agent.py:47

# Bot abstractions and infographic entry point
from parrot.bots.abstract import AbstractBot
# verified: packages/ai-parrot/src/parrot/handlers/agent.py:32

# Infographic models and registries
from parrot.models.infographic import ThemeConfig, ThemeRegistry, theme_registry
# verified: packages/ai-parrot/src/parrot/models/infographic.py:339,387,434
from parrot.models.infographic_templates import (
    InfographicTemplate, InfographicTemplateRegistry, infographic_registry,
    BlockSpec,
)
# verified: packages/ai-parrot/src/parrot/models/infographic_templates.py:21,47,310,382

# Infographic HTML rendering (used only by bot.get_infographic, not directly)
from parrot.outputs.formats.infographic_html import InfographicHTMLRenderer
# verified: packages/ai-parrot/src/parrot/outputs/formats/infographic_html.py

# Responses
from parrot.models.responses import AIMessage
# verified: packages/ai-parrot/src/parrot/handlers/agent.py:34

# aiohttp
from aiohttp import web
```

### Existing Class Signatures

```python
# packages/ai-parrot/src/parrot/handlers/agent.py:47
@is_authenticated()
@user_session()
class AgentTalk(BaseView):
    _logger_name: str = "Parrot.AgentTalk"                         # line 65
    _user_objects_handler: UserObjectsHandler = None                # line 66

    def post_init(self, *args, **kwargs): ...                       # line 76

    async def _check_pbac_agent_access(
        self, agent_id: str, action: str = "agent:chat",
    ) -> web.Response: ...                                          # line 80

    def _get_agent_name(self, data: dict) -> Union[str, None]: ...  # line 821

    async def _get_user_session(
        self, data: dict,
    ) -> tuple[Union[str, None], Union[str, None]]: ...             # line 867

    async def _get_agent(
        self, data: Dict[str, Any],
    ) -> Union[AbstractBot, web.Response]: ...                      # line 898

    def _get_output_format(
        self, data: Dict[str, Any], qs: Dict[str, Any],
    ) -> str: ...                                                   # line 390

    async def post(self) -> web.Response: ...                       # line 1001
    async def get(self) -> web.Response: ...                        # line 1556
    async def patch(self) -> web.Response: ...                      # line 1334
    async def put(self) -> web.Response: ...                        # line 1458

# packages/ai-parrot/src/parrot/bots/abstract.py:2574
async def get_infographic(
    self,
    question: str,
    template: Optional[str] = "basic",
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
    use_vector_context: bool = True,
    use_conversation_history: bool = False,
    theme: Optional[str] = None,
    accept: str = "text/html",
    ctx: Optional[RequestContext] = None,
    **kwargs,
) -> AIMessage:
    """Returns AIMessage with .structured_output = InfographicResponse.
    When accept == 'text/html', .content holds HTML and .output_mode is HTML."""

# packages/ai-parrot/src/parrot/models/infographic_templates.py:310
class InfographicTemplateRegistry:
    def __init__(self) -> None: ...                                 # line 316
    def _register_builtins(self) -> None: ...                       # line 320
    def register(self, template: InfographicTemplate) -> None: ...  # line 332
    def get(self, name: str) -> InfographicTemplate: ...            # line 340
    def list_templates(self) -> List[str]: ...                      # line 361
    def list_templates_detailed(self) -> List[Dict[str, str]]: ...  # line 369

infographic_registry = InfographicTemplateRegistry()                # line 382

# packages/ai-parrot/src/parrot/models/infographic.py:387
class ThemeRegistry:
    def __init__(self) -> None: ...                                 # line 394
    def register(self, theme: ThemeConfig) -> None: ...             # line 397
    def get(self, name: str) -> ThemeConfig: ...                    # line 405
    def list_themes(self) -> List[str]: ...                         # line 424
    # NOTE: list_themes_detailed() does NOT exist yet — Module 1 may add it.

theme_registry = ThemeRegistry()                                    # line 434
# Built-ins registered at lines 438, 453, 468 (light, dark, corporate)

# packages/ai-parrot/src/parrot/models/infographic_templates.py:47
class InfographicTemplate(BaseModel):
    name: str                                                       # line 49
    description: str                                                # line 50
    block_specs: List[BlockSpec]                                    # line 51
    default_theme: Optional[str] = None                             # line 55
    def to_prompt_instruction(self) -> str: ...                     # line 60

# packages/ai-parrot/src/parrot/models/infographic.py:339
class ThemeConfig(BaseModel):
    name: str
    primary: str = "#6366f1"
    primary_dark: str = "#4f46e5"
    primary_light: str = "#818cf8"
    accent_green: str = "#10b981"
    accent_amber: str = "#f59e0b"
    accent_red: str = "#ef4444"
    neutral_bg: str = "#f8fafc"
    neutral_border: str = "#e2e8f0"
    neutral_muted: str = "#64748b"
    neutral_text: str = "#0f172a"
    body_bg: str = "#f1f5f9"
    font_family: str = ...                                          # line 358
    def to_css_variables(self) -> str: ...                          # line 364
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `InfographicTalk` | `AgentTalk` | class inheritance | `packages/ai-parrot/src/parrot/handlers/agent.py:47` |
| `InfographicTalk.post` | `AbstractBot.get_infographic` | method call | `packages/ai-parrot/src/parrot/bots/abstract.py:2574` |
| `InfographicTalk._get_agent` | inherited | method inheritance | `packages/ai-parrot/src/parrot/handlers/agent.py:898` |
| `helpers.list_templates` | `infographic_registry.list_templates` | delegation | `packages/ai-parrot/src/parrot/models/infographic_templates.py:361` |
| `helpers.register_template` | `infographic_registry.register` | delegation | `packages/ai-parrot/src/parrot/models/infographic_templates.py:332` |
| `helpers.list_themes` | `theme_registry.list_themes` | delegation | `packages/ai-parrot/src/parrot/models/infographic.py:424` |
| `helpers.register_theme` | `theme_registry.register` | delegation | `packages/ai-parrot/src/parrot/models/infographic.py:397` |
| Route registration | `BotManager.setup_app` | `router.add_view` | `packages/ai-parrot/src/parrot/manager/manager.py:718-725` |

### Does NOT Exist (Anti-Hallucination)
- ~~`parrot.handlers.infographic`~~ — does not exist yet (Module 2 creates it)
- ~~`parrot.helpers.infographics`~~ — does not exist yet (Module 1 creates it)
- ~~`parrot.helpers`~~ — the package does **not** exist either (verified
  2026-04-10: `packages/ai-parrot/src/parrot/helpers/` is absent). Module 1
  must create `packages/ai-parrot/src/parrot/helpers/__init__.py` before
  adding `infographics.py`.
- ~~`ThemeRegistry.list_themes_detailed`~~ — not implemented yet; Module 1
  may add this minimal extension
- ~~`InfographicTemplateRegistry.unregister`~~ — no deletion API exists, and
  this feature does NOT add one
- ~~`AgentTalk.get_infographic`~~ — not a method on the handler; infographic
  generation currently requires calling POST with `output_mode` flags
- ~~`OutputMode.INFOGRAPHIC_HTML`~~ — does not exist; HTML is the default
  via `accept` param on the bot method
- ~~`InfographicTalk.patch`~~ — we do NOT override `patch`; the inherited
  `AgentTalk.patch` stays as-is and continues to handle tool configuration
  for its own route. `InfographicTalk` has no PATCH route registered.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Inherit from `AgentTalk` (not `BaseView` directly) — auth decorators and
  session/PBAC helpers come along automatically.
- Reuse the `_check_pbac_agent_access` pattern: call it at the top of `post`
  before dispatching, with the appropriate action string (`agent:chat` for
  generation, `agent:configure` for registration).
- Dispatch inside `post`/`get` on `match_info` keys (`agent_id`,
  `template_name`, `theme_name`) rather than registering a different handler
  per sub-path. This mirrors how `AgentTalk.get` already dispatches on
  `method_name` (`debug`, `mcp_servers`, default info).
- Use `self.json_response(...)` and `self.error(...)` helpers from `BaseView`
  (both are used throughout `AgentTalk`).
- For HTML responses, build a `web.Response(body=html, content_type="text/html")`
  — do NOT hand the HTML through `OutputFormatter`; the bot method already
  assembled it.
- Session-scoped custom registries: store as a `dict[str, InfographicTemplate]`
  under `request.session["_infographic_templates"]`. When looking up a template
  name on the generation path, check session first, fall back to global
  registry. This mirrors `{agent_id}_tool_manager` isolation.
- Logger: `self.logger = logging.getLogger(self._logger_name)` — set in
  `post_init`, inherited from `AgentTalk`.

### Content Negotiation
- `_negotiate_accept()` returns `"application/json"` when the `Accept` header
  contains `application/json`, otherwise `"text/html"` (default matches
  `get_infographic`'s own default).
- Explicit override: `?format=html` or `?format=json` query param wins.
- Pass the resolved `accept` string straight into `bot.get_infographic(accept=...)`.

### Known Risks / Gotchas
- **Session storage mutability**: Custom templates stored in
  `request.session` must be JSON-serialisable for the session backend. Store
  as `InfographicTemplate.model_dump()` dicts, re-validate on read.
- **Shared global registry**: `scope: "global"` mutates a process-wide
  singleton. Document this clearly; recommend `scope: "session"` for
  user-contributed templates in production.
- **PBAC for registration**: Treat template/theme registration as
  `agent:configure` — do not allow unauthenticated registration even in
  scope=global.
- **Route ordering**: `router.add_view` is order-insensitive for distinct
  patterns, but confirm the `{agent_id}` and `templates`/`themes` routes
  don't collide. Registering `templates` and `themes` as literal paths (not
  `{agent_id}`) avoids aiohttp ambiguity — aiohttp resolves literal segments
  before pattern segments, but we'll verify with the integration test
  `test_integration_routes_registered`.
- **`tests/handlers/` layout**: verify the pytest discovery root includes
  this directory; if not, add a `conftest.py` next to the new test file.

### External Dependencies

No new packages. All imports are already in the monorepo venv.

---

## Worktree Strategy

- **Default isolation**: `per-spec` — tasks run sequentially in a single
  worktree. Module dependencies are linear (helpers → handler → routes → tests).
- **Cross-feature dependencies**: Depends on **FEAT-094** (infographic HTML
  output). FEAT-094 is already merged into `dev` as of commit `b660ce4c`, so
  this feature can branch directly from `dev`.
- **Recommended branch / worktree**:
  ```bash
  git checkout dev && git pull origin dev
  git worktree add -b feat-095-get-infographic-handler \
    .claude/worktrees/feat-095-get-infographic-handler HEAD
  ```

---

## 8. Open Questions

- [ ] Should `scope: "global"` require an elevated PBAC action (e.g.
      `infographic:register:global`) distinct from `agent:configure`, so that
      regular users can only register session-scoped templates? — *Owner: Jesus Lara*
- [x] Does `parrot/helpers/` already exist as a package? — verified
      2026-04-10: no. Module 1 will create it with an empty `__init__.py`.
      — *Owner: implementer*
- [ ] Should the handler expose a `DELETE` endpoint to remove a session-scoped
      custom template/theme? Current spec says no (out of scope for v1) —
      confirm. — *Owner: Jesus Lara*
- [ ] For `GET /templates/{template_name}` should the response return the
      raw `InfographicTemplate.model_dump()` or a narrower projection
      (name + description + block count)? Default: full dump. — *Owner: Jesus Lara*

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-04-10 | Jesus Lara | Initial draft (no brainstorm input; derived from /sdd-spec command args) |
