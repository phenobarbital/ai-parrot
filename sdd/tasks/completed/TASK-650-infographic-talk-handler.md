# TASK-650: InfographicTalk HTTP Handler

**Feature**: get-infographic-handler
**Spec**: `sdd/specs/get-infographic-handler.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-649
**Assigned-to**: unassigned

---

## Context

This is the core HTTP surface for FEAT-095. It introduces
`InfographicTalk`, a new aiohttp view that inherits from `AgentTalk` to
reuse authentication decorators, PBAC guards, agent lookup, and session
handling. The handler exposes `bot.get_infographic()` and the
template/theme registries over HTTP.

Implements **Module 2** of the spec.

**Key design constraint (spec §7)**: Regular users cannot register new
templates or themes via `scope: "global"` — that is deferred to v2. For v1,
global registration requires the `agent:configure` PBAC action; if denied,
return 403 directly. The `scope: "session"` path is also denied — in v1 we
return 403 for any registration attempt. The GET/list endpoints remain open
to all authenticated users.

Implements **Module 2** of the spec.

---

## Scope

- Create `packages/ai-parrot/src/parrot/handlers/infographic.py` with an
  `InfographicTalk` class that **inherits from `AgentTalk`**.
- Override `post`, `get`, and do NOT override `patch` / `put`.
- Dispatch inside each HTTP verb on `self.request.match_info` keys to route
  between generation, template GETs, and theme GETs.
- **Generation path (`POST /api/v1/agents/infographic/{agent_id}`)**:
    - Call `self._check_pbac_agent_access(agent_id, action="agent:chat")`.
    - Parse JSON body; require `query` field.
    - Resolve agent via inherited `self._get_agent(data)`.
    - Resolve user/session via inherited `self._get_user_session(data)`.
    - Call `_negotiate_accept()` to resolve `"text/html"` or
      `"application/json"` (priority: `?format=` query > `Accept` header >
      default `"text/html"`).
    - Invoke `await agent.get_infographic(question=query, template=..., theme=..., accept=negotiated_accept, session_id=..., user_id=..., use_vector_context=..., use_conversation_history=..., ctx=None, **kwargs)`.
    - If `negotiated_accept == "text/html"`: return `web.Response(body=<ai_message.content or ai_message.output>, content_type="text/html")`.
    - Otherwise: return `self.json_response({...structured_output fields...})`.
- **Template GET paths**:
    - `GET /api/v1/agents/infographic/templates` →
      `helpers.list_templates(detailed=qs.get('detailed')=='true')`.
    - `GET /api/v1/agents/infographic/templates/{template_name}` →
      `helpers.get_template(name).model_dump()`; return 404 on `KeyError`.
- **Theme GET paths**:
    - `GET /api/v1/agents/infographic/themes` →
      `helpers.list_themes(detailed=...)`.
    - `GET /api/v1/agents/infographic/themes/{theme_name}` →
      `helpers.get_theme(name).model_dump()`; return 404 on `KeyError`.
- **Registration paths (v1 = denied for regular users)**:
    - `POST /api/v1/agents/infographic/templates`:
        1. PBAC check `agent:configure` via
           `self._check_pbac_agent_access(agent_id="*", action="agent:configure")`.
        2. If PBAC is not configured OR the caller passes the check, call
           `helpers.register_template(data["template"])`. On
           `pydantic.ValidationError` return HTTP 400.
        3. The `scope` field in the body is accepted but only `"global"` is
           honoured in v1 (no session-scoped storage). If `scope == "session"`
           return 403 with body
           `{"error": "Session-scoped template registration is not available in v1."}`.
    - `POST /api/v1/agents/infographic/themes` — mirror template behaviour.
- Add `_logger_name: str = "Parrot.InfographicTalk"`.
- Inherit `@is_authenticated()`, `@user_session()` decorators by applying
  them to the `InfographicTalk` class (they don't inherit automatically
  from `AgentTalk` — verify at implementation time and apply explicitly).
- **Do not** register routes in this task — TASK-651 owns that.

**NOT in scope**:
- Route registration in `BotManager.setup_app` (TASK-651).
- Any DELETE endpoint.
- Session-scoped template/theme storage — out of scope per spec Open
  Question resolution.
- Tests beyond trivial import-smoke — full test coverage is TASK-652.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/handlers/infographic.py` | CREATE | `InfographicTalk(AgentTalk)` handler class |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from __future__ import annotations
from typing import Any, Dict, Optional
from aiohttp import web
from navconfig.logging import logging
from navigator_auth.decorators import is_authenticated, user_session
from pydantic import ValidationError

from parrot.handlers.agent import AgentTalk
# verified: packages/ai-parrot/src/parrot/handlers/agent.py:47

from parrot.bots.abstract import AbstractBot
# verified: packages/ai-parrot/src/parrot/handlers/agent.py:32

from parrot.helpers.infographics import (
    list_templates, get_template, register_template,
    list_themes, get_theme, register_theme,
)  # verified: created by TASK-649 (MUST be complete before starting this task)

from parrot.models.infographic_templates import InfographicTemplate
# verified: packages/ai-parrot/src/parrot/models/infographic_templates.py:47

from parrot.models.infographic import ThemeConfig
# verified: packages/ai-parrot/src/parrot/models/infographic.py:339
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/handlers/agent.py:47
@is_authenticated()
@user_session()
class AgentTalk(BaseView):
    _logger_name: str = "Parrot.AgentTalk"                         # line 65

    def post_init(self, *args, **kwargs):                          # line 76
        # Sets self.logger.

    async def _check_pbac_agent_access(
        self, agent_id: str, action: str = "agent:chat",
    ) -> Optional[web.Response]:                                   # line 80
        # Returns None if allowed, or a 403 web.Response if denied.
        # Returns None (allow) if PBAC is not configured (fail open).

    def _get_agent_name(self, data: dict) -> Union[str, None]:     # line 821

    async def _get_user_session(
        self, data: dict,
    ) -> tuple[Union[str, None], Union[str, None]]:                 # line 867

    async def _get_agent(
        self, data: Dict[str, Any],
    ) -> Union[AbstractBot, web.Response]:                         # line 898
        # Returns the agent OR a web.Response error — always check isinstance.

    def _get_output_format(
        self, data: Dict[str, Any], qs: Dict[str, Any],
    ) -> str:                                                      # line 390
        # Returns one of 'json', 'html', 'markdown', 'text'.

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
    """When accept == 'text/html', response.content holds HTML and
    response.output_mode is OutputMode.HTML. Otherwise structured_output
    holds the raw InfographicResponse."""

# BaseView provides:
# - self.request (aiohttp Request)
# - self.json_response(data, status=200) helper
# - self.error(msg, status=...) helper
# - self.query_parameters(request) helper
# These are used throughout AgentTalk — same usage applies here.
```

### Does NOT Exist
- ~~`parrot.handlers.infographic`~~ — this task creates it.
- ~~`InfographicTalk` anywhere in the codebase~~ — new class.
- ~~`AgentTalk.get_infographic`~~ — not a method on the handler; infographic
  generation goes through `bot.get_infographic()`.
- ~~`ctx.RequestContext` auto-built by the handler~~ — pass `ctx=None`.
- ~~Session-scoped template storage helpers~~ — do NOT implement; v1
  returns 403 for any `scope: "session"` registration.
- ~~`bot.get_infographic` returning `web.Response`~~ — it returns
  `AIMessage`; the handler must translate.
- ~~`AIMessage.to_html()`~~ — no such method; read `response.content`
  (HTML string set by `get_infographic` when `accept=='text/html'`) OR
  `response.output` as a fallback.

---

## Implementation Notes

### Class Skeleton

```python
# packages/ai-parrot/src/parrot/handlers/infographic.py
"""HTTP handler for get_infographic() generation, plus template and theme
discovery/registration endpoints."""
from __future__ import annotations
from typing import Any, Dict, Optional
from aiohttp import web
from navconfig.logging import logging
from navigator_auth.decorators import is_authenticated, user_session
from pydantic import ValidationError

from .agent import AgentTalk
from ..bots.abstract import AbstractBot
from ..helpers.infographics import (
    list_templates, get_template, register_template,
    list_themes, get_theme, register_theme,
)


@is_authenticated()
@user_session()
class InfographicTalk(AgentTalk):
    """Dedicated HTTP handler for bot.get_infographic() plus template/theme
    registries."""

    _logger_name: str = "Parrot.InfographicTalk"

    def post_init(self, *args, **kwargs):
        self.logger = logging.getLogger(self._logger_name)
        self.logger.setLevel(logging.DEBUG)

    # ── Public HTTP verbs ──────────────────────────────────────────────

    async def post(self) -> web.Response:
        """Dispatch on match_info:
          - {agent_id}: generate infographic
          - templates: register template
          - themes:    register theme
        """
        mi = self.request.match_info
        if "template_name" in mi:
            return self.error("Cannot POST to a specific template.", status=405)
        if "theme_name" in mi:
            return self.error("Cannot POST to a specific theme.", status=405)
        if mi.get("resource") == "templates":
            return await self._handle_templates_register()
        if mi.get("resource") == "themes":
            return await self._handle_themes_register()
        # Default: infographic generation
        return await self._generate_infographic()

    async def get(self) -> web.Response:
        """Dispatch on match_info:
          - templates[/{name}]
          - themes[/{name}]
          - default → endpoint info
        """
        mi = self.request.match_info
        if mi.get("resource") == "templates":
            return await self._handle_templates_get(mi.get("template_name"))
        if mi.get("resource") == "themes":
            return await self._handle_themes_get(mi.get("theme_name"))
        return self.json_response({
            "message": "InfographicTalk — get_infographic HTTP handler",
            "version": "1.0",
            "endpoints": {
                "generate": "POST /api/v1/agents/infographic/{agent_id}",
                "list_templates": "GET /api/v1/agents/infographic/templates",
                "get_template": "GET /api/v1/agents/infographic/templates/{name}",
                "register_template": "POST /api/v1/agents/infographic/templates",
                "list_themes": "GET /api/v1/agents/infographic/themes",
                "get_theme": "GET /api/v1/agents/infographic/themes/{name}",
                "register_theme": "POST /api/v1/agents/infographic/themes",
            },
        })

    # ── Internal dispatchers ───────────────────────────────────────────

    async def _generate_infographic(self) -> web.Response:
        agent_id = self.request.match_info.get("agent_id")
        if not agent_id:
            return self.error("Missing agent_id in URL.", status=400)

        pbac_denied = await self._check_pbac_agent_access(
            agent_id=agent_id, action="agent:chat"
        )
        if pbac_denied is not None:
            return pbac_denied

        try:
            data: Dict[str, Any] = await self.request.json()
        except Exception:
            return self.error("Invalid JSON body.", status=400)

        query = data.pop("query", None)
        if not query:
            return self.error("Missing 'query' field in body.", status=400)

        agent = await self._get_agent({"agent_name": agent_id, **data})
        if isinstance(agent, web.Response):
            return agent

        user_id, session_id = await self._get_user_session(data)

        accept = self._negotiate_accept()

        template = data.pop("template", "basic")
        theme = data.pop("theme", None)
        use_vector_context = data.pop("use_vector_context", True)
        use_conversation_history = data.pop("use_conversation_history", False)

        try:
            ai_message = await agent.get_infographic(
                question=query,
                template=template,
                theme=theme,
                accept=accept,
                session_id=session_id,
                user_id=user_id,
                use_vector_context=use_vector_context,
                use_conversation_history=use_conversation_history,
                ctx=None,
                **data,
            )
        except KeyError as exc:
            # Unknown template — registry raises KeyError.
            return self.error(str(exc), status=404)
        except Exception as exc:
            self.logger.exception("Infographic generation failed: %s", exc)
            return self.error(f"Generation failed: {exc}", status=500)

        if accept == "text/html":
            html = getattr(ai_message, "content", None) or getattr(ai_message, "output", None) or ""
            if not isinstance(html, str):
                html = str(html)
            return web.Response(body=html, content_type="text/html")

        # JSON path
        structured = getattr(ai_message, "structured_output", None) or getattr(ai_message, "output", None)
        if hasattr(structured, "model_dump"):
            payload = structured.model_dump()
        elif isinstance(structured, dict):
            payload = structured
        else:
            payload = {"output": str(structured)}
        return self.json_response({"infographic": payload})

    async def _handle_templates_get(self, name: Optional[str]) -> web.Response:
        qs = self.query_parameters(self.request)
        if name is None:
            detailed = qs.get("detailed", "").lower() == "true"
            return self.json_response({"templates": list_templates(detailed=detailed)})
        try:
            tpl = get_template(name)
        except KeyError as exc:
            return self.error(str(exc), status=404)
        return self.json_response({"template": tpl.model_dump()})

    async def _handle_themes_get(self, name: Optional[str]) -> web.Response:
        qs = self.query_parameters(self.request)
        if name is None:
            detailed = qs.get("detailed", "").lower() == "true"
            return self.json_response({"themes": list_themes(detailed=detailed)})
        try:
            theme = get_theme(name)
        except KeyError as exc:
            return self.error(str(exc), status=404)
        return self.json_response({"theme": theme.model_dump()})

    async def _handle_templates_register(self) -> web.Response:
        pbac_denied = await self._check_pbac_agent_access(
            agent_id="*", action="agent:configure"
        )
        if pbac_denied is not None:
            return pbac_denied

        try:
            data = await self.request.json()
        except Exception:
            return self.error("Invalid JSON body.", status=400)

        scope = data.get("scope", "global").lower()
        if scope == "session":
            return self.error(
                "Session-scoped template registration is not available in v1.",
                status=403,
            )
        payload = data.get("template")
        if not payload:
            return self.error("Missing 'template' field in body.", status=400)
        try:
            tpl = register_template(payload)
        except ValidationError as exc:
            return self.json_response(
                {"error": "Invalid template payload", "details": exc.errors()},
                status=400,
            )
        return self.json_response(
            {"message": "Template registered", "template": tpl.model_dump()},
            status=201,
        )

    async def _handle_themes_register(self) -> web.Response:
        pbac_denied = await self._check_pbac_agent_access(
            agent_id="*", action="agent:configure"
        )
        if pbac_denied is not None:
            return pbac_denied

        try:
            data = await self.request.json()
        except Exception:
            return self.error("Invalid JSON body.", status=400)

        scope = data.get("scope", "global").lower()
        if scope == "session":
            return self.error(
                "Session-scoped theme registration is not available in v1.",
                status=403,
            )
        payload = data.get("theme")
        if not payload:
            return self.error("Missing 'theme' field in body.", status=400)
        try:
            theme = register_theme(payload)
        except ValidationError as exc:
            return self.json_response(
                {"error": "Invalid theme payload", "details": exc.errors()},
                status=400,
            )
        return self.json_response(
            {"message": "Theme registered", "theme": theme.model_dump()},
            status=201,
        )

    # ── Helpers ────────────────────────────────────────────────────────

    def _negotiate_accept(self) -> str:
        """Resolve the desired content type.

        Priority:
            1. Explicit ``?format=`` query parameter (``html`` or ``json``).
            2. ``Accept`` header containing ``application/json``.
            3. Default ``text/html``.
        """
        qs = self.query_parameters(self.request)
        fmt = (qs.get("format") or "").lower()
        if fmt == "json":
            return "application/json"
        if fmt == "html":
            return "text/html"
        accept_header = self.request.headers.get("Accept", "")
        if "application/json" in accept_header:
            return "application/json"
        return "text/html"
```

### Key Constraints

- Inherit from `AgentTalk`, do NOT copy its helpers.
- Decorators `@is_authenticated()` and `@user_session()` must be applied
  explicitly on `InfographicTalk` — aiohttp BaseView decorators do not
  always propagate through inheritance reliably. Mirror the pattern from
  `AgentTalk` line 45-47.
- `_get_agent` expects `data["agent_name"]` OR `match_info["agent_id"]` —
  we pass the URL `agent_id` via `match_info` which `_get_agent_name`
  already reads from `self.request.match_info.get('agent_id', None)`, so
  we don't need to stuff it into `data`. The sketch above does it for
  belt-and-braces; simplify at implementation time.
- `_get_user_session` mutates `data` (`data.pop('user_id', ...)`). Call
  it AFTER popping `query`, `template`, `theme`, etc., so leftover
  `**data` passed to `get_infographic` doesn't carry `user_id`/`session_id`
  twice.
- Route registration is NOT this task — TASK-651 handles `setup_app`.
- Do not call `OutputFormatter` — `get_infographic` already assembles the
  HTML.

### References in Codebase

- `packages/ai-parrot/src/parrot/handlers/agent.py:47-65` — decorator
  and class pattern.
- `packages/ai-parrot/src/parrot/handlers/agent.py:1001-1332` — reference
  for how `post()` composes PBAC check → data parse → `_get_agent` →
  ask-style call → formatted response.
- `packages/ai-parrot/src/parrot/handlers/agent.py:1556-1651` — reference
  for how `get()` dispatches on `match_info`.
- `packages/ai-parrot/src/parrot/handlers/lyria_music.py` — minimal
  handler pattern (CREATE + GET with JSON body validation).

---

## Acceptance Criteria

- [ ] `from parrot.handlers.infographic import InfographicTalk` succeeds.
- [ ] `InfographicTalk.__bases__` contains `AgentTalk`.
- [ ] `InfographicTalk` does not redefine `_check_pbac_agent_access`,
      `_get_agent`, `_get_user_session`, or `_get_agent_name`.
- [ ] `post()` routes correctly based on `match_info` keys.
- [ ] `get()` routes templates and themes lookups.
- [ ] `_negotiate_accept()` returns `"application/json"` for
      `Accept: application/json` and `"text/html"` otherwise.
- [ ] Registration POST paths return 403 when `scope == "session"`.
- [ ] Pydantic `ValidationError` on register → HTTP 400 with error details.
- [ ] `KeyError` from `get_template` / `get_theme` → HTTP 404.
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/handlers/infographic.py`.
- [ ] Module imports without errors inside an activated venv.

---

## Test Specification

> Full test coverage is TASK-652. This task only needs a smoke test to
> confirm the module imports and the class is properly constructed.

```python
# packages/ai-parrot/tests/handlers/test_infographic_handler_smoke.py
def test_import_infographic_talk():
    from parrot.handlers.infographic import InfographicTalk
    from parrot.handlers.agent import AgentTalk
    assert issubclass(InfographicTalk, AgentTalk)
    assert InfographicTalk._logger_name == "Parrot.InfographicTalk"
```

---

## Agent Instructions

When you pick up this task:

1. Read the spec at `sdd/specs/get-infographic-handler.spec.md`.
2. **Verify TASK-649 is complete** — `from parrot.helpers.infographics import list_templates` must succeed.
3. Re-verify the Codebase Contract against the current tree — line numbers in
   `agent.py` may drift.
4. Update status in `sdd/tasks/.index.json` → `"in-progress"`.
5. Implement Module 2 per the scope and class skeleton above.
6. Run the smoke test: `pytest packages/ai-parrot/tests/handlers/test_infographic_handler_smoke.py -v`.
7. Verify acceptance criteria.
8. Move this file to `sdd/tasks/completed/TASK-650-infographic-talk-handler.md` and update index → `"done"`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sdd-worker
**Date**: 2026-04-10
**Notes**: Handler created with full dispatch logic. Smoke test passes. Conftest updated to register new modules from worktree without shadowing compiled extensions.

**Deviations from spec**: none
