# TASK-651: Register InfographicTalk Routes in BotManager

**Feature**: get-infographic-handler
**Spec**: `sdd/specs/get-infographic-handler.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-650
**Assigned-to**: unassigned

---

## Context

The `InfographicTalk` handler created in TASK-650 must be wired into the
aiohttp router by `BotManager.setup_app()`. This task adds six routes under
`/api/v1/agents/infographic` next to the existing `AgentTalk` routes.

Implements **Module 3** of the spec.

---

## Scope

- Import `InfographicTalk` inside `packages/ai-parrot/src/parrot/manager/manager.py`.
- Register the following routes in `setup_app`, immediately after the
  existing `AgentTalk` route block (around line 718-725):

  | Method | Path | `match_info` keys |
  |---|---|---|
  | POST | `/api/v1/agents/infographic/{agent_id}` | `agent_id` |
  | GET  | `/api/v1/agents/infographic/templates` | `resource` (literal) |
  | GET  | `/api/v1/agents/infographic/templates/{template_name}` | `resource`, `template_name` |
  | POST | `/api/v1/agents/infographic/templates` | `resource` |
  | GET  | `/api/v1/agents/infographic/themes` | `resource` |
  | GET  | `/api/v1/agents/infographic/themes/{theme_name}` | `resource`, `theme_name` |
  | POST | `/api/v1/agents/infographic/themes` | `resource` |

- To supply the `resource` key to the dispatcher in TASK-650, use aiohttp's
  variable-path trick by registering literal routes under a `resource`
  variable OR by using `add_route`/`add_view` with explicit routing. Pick
  whichever keeps the `InfographicTalk.post()` / `get()` dispatch logic
  unchanged.

  **Recommended approach**: register the two resource sub-roots as distinct
  views. Because aiohttp resolves literal path segments before pattern
  segments, and `{agent_id}` could match `templates` or `themes`, we must
  register the literal resource routes BEFORE the `{agent_id}` route OR
  route them to a separate path prefix to avoid collision.

  **Simplest working design**:
  ```python
  # Literal resource routes — register FIRST to win against {agent_id}
  router.add_view('/api/v1/agents/infographic/templates', InfographicTalk)
  router.add_view('/api/v1/agents/infographic/templates/{template_name}', InfographicTalk)
  router.add_view('/api/v1/agents/infographic/themes', InfographicTalk)
  router.add_view('/api/v1/agents/infographic/themes/{theme_name}', InfographicTalk)
  # Catch-all per-agent generation — register LAST
  router.add_view('/api/v1/agents/infographic/{agent_id}', InfographicTalk)
  ```

  Then in `InfographicTalk` dispatch logic (TASK-650), instead of reading
  `mi.get("resource")`, infer the resource from the presence of
  `template_name` / `theme_name` OR by parsing the path. If TASK-650's
  skeleton used `mi.get("resource")`, update the dispatch to instead check
  `self.request.path` segments or rely on match_info shape.

  **IMPORTANT — coordinate with TASK-650's dispatch**: TASK-650 uses
  `mi.get("resource")` as a key. aiohttp does NOT synthesise such a key from
  literal segments. The implementer of THIS task should either:
  (a) patch `InfographicTalk.post()` / `get()` to inspect `self.request.path`
      instead of `match_info["resource"]`, OR
  (b) register routes with a pattern like `/{resource:templates}` to force
      the match_info key, using aiohttp's regex variable syntax:
      `router.add_view('/api/v1/agents/infographic/{resource:templates}', InfographicTalk)`.

  Option (b) is cleaner and preserves TASK-650's skeleton. Use it.

- Confirm the routes appear in `app.router.resources()` after
  `BotManager.setup_app()` runs.
- Do NOT touch any other existing routes.
- Do NOT add swagger/openapi annotations — out of scope.

**NOT in scope**:
- Tests (TASK-652).
- Modifying `InfographicTalk` class behaviour beyond the small dispatch
  adjustment noted above.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/manager/manager.py` | MODIFY | Import `InfographicTalk` and register 7 routes |
| `packages/ai-parrot/src/parrot/handlers/infographic.py` | MODIFY (tiny) | Align dispatch with chosen route strategy if needed |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# In manager.py — add next to existing AgentTalk import (line 22)
from ..handlers.agent import AgentTalk                   # line 22 — already present
from ..handlers.infographic import InfographicTalk       # NEW — added by this task
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/manager/manager.py
class BotManager:
    def setup_app(self, app: web.Application, ...) -> None:
        # Around line 700-725:
        self.app['bot_manager'] = self
        router = self.app.router
        # ... ChatHandler routes ...
        router.add_view(
            '/api/v1/agents/chat/{agent_id}',
            AgentTalk,
        )                                                       # line 718-721
        router.add_view(
            '/api/v1/agents/chat/{agent_id}/{method_name}',
            AgentTalk,
        )                                                       # line 722-725
        # ← NEW InfographicTalk routes go here
        # Then DatasetManagerHandler routes continue at line 727+
```

### Aiohttp routing reference

```python
# aiohttp regex variable syntax: {name:regex}
router.add_view('/api/v1/agents/infographic/{resource:templates}', InfographicTalk)
router.add_view(
    '/api/v1/agents/infographic/{resource:templates}/{template_name}',
    InfographicTalk,
)
router.add_view('/api/v1/agents/infographic/{resource:themes}', InfographicTalk)
router.add_view(
    '/api/v1/agents/infographic/{resource:themes}/{theme_name}',
    InfographicTalk,
)
router.add_view('/api/v1/agents/infographic/{agent_id}', InfographicTalk)
```

After this registration, `self.request.match_info.get("resource")` will
return `"templates"` or `"themes"` when the literal-path routes match, and
the generic `{agent_id}` route captures anything else.

### Does NOT Exist
- ~~`app.router.add_infographic_routes()`~~ — no such helper; use
  `router.add_view` like every other handler.
- ~~`InfographicTalk.configure(app, prefix)`~~ — the handler does not
  expose a class-level configure method (unlike `ChatbotHandler`). Use
  `router.add_view` directly.

---

## Implementation Notes

### Diff sketch for `manager.py`

```python
# near line 22
from ..handlers.agent import AgentTalk
from ..handlers.infographic import InfographicTalk   # NEW

# ...

# near line 718 inside setup_app()
router.add_view('/api/v1/agents/chat/{agent_id}', AgentTalk)
router.add_view('/api/v1/agents/chat/{agent_id}/{method_name}', AgentTalk)

# -- InfographicTalk routes (FEAT-095) --
# Literal resource routes (use regex variable so match_info exposes 'resource')
router.add_view(
    '/api/v1/agents/infographic/{resource:templates}',
    InfographicTalk,
)
router.add_view(
    '/api/v1/agents/infographic/{resource:templates}/{template_name}',
    InfographicTalk,
)
router.add_view(
    '/api/v1/agents/infographic/{resource:themes}',
    InfographicTalk,
)
router.add_view(
    '/api/v1/agents/infographic/{resource:themes}/{theme_name}',
    InfographicTalk,
)
# Catch-all per-agent generation — MUST come after the literal routes
router.add_view(
    '/api/v1/agents/infographic/{agent_id}',
    InfographicTalk,
)
```

### Route ordering

In aiohttp, when multiple routes could match a request, the first
registered wins. By registering the four literal `{resource:...}` routes
BEFORE the `{agent_id}` catch-all, we ensure
`/api/v1/agents/infographic/templates` resolves to the templates route,
not to `{agent_id}=templates`. Verify this with a smoke check in the
integration test (TASK-652).

### Adjust InfographicTalk dispatch if required

TASK-650's skeleton already uses `mi.get("resource")`, which is exactly
what the `{resource:templates}` syntax produces. No adjustment should be
necessary. Confirm by reading the final file from TASK-650 before writing
the route block.

### Key Constraints

- Use `router.add_view`, not `router.add_route`, to stay consistent with
  every other handler in `setup_app`.
- Do not move or rename existing `AgentTalk` routes.
- Do not register the routes inside a conditional feature flag — they are
  always available (no `ENABLE_*` env var for this feature).

### References in Codebase

- `packages/ai-parrot/src/parrot/manager/manager.py:700-800` — canonical
  example of `router.add_view` usage for `AgentTalk`,
  `DatasetManagerHandler`, database handlers, `BotConfigHandler`, etc.

---

## Acceptance Criteria

- [ ] `from parrot.handlers.infographic import InfographicTalk` is present
      at the top of `manager.py`.
- [ ] Five `router.add_view` calls (four literal + one catch-all) are added
      inside `setup_app` immediately after the `AgentTalk` route block.
- [ ] The literal resource routes are registered BEFORE the `{agent_id}`
      route (so aiohttp resolves `templates` / `themes` paths correctly).
- [ ] After calling `BotManager.setup_app()` on a fresh `web.Application`,
      `app.router.resources()` includes all five new paths.
- [ ] No existing routes are removed or reordered.
- [ ] `ruff check packages/ai-parrot/src/parrot/manager/manager.py` passes.
- [ ] The app boots without errors (smoke: `python -c "from parrot.manager.manager import BotManager"` inside the venv).

---

## Test Specification

> Full integration tests are TASK-652. This task needs only a direct
> routing smoke check.

```python
# packages/ai-parrot/tests/handlers/test_infographic_routes_registered.py
import pytest
from aiohttp import web


def test_routes_registered_after_setup_app():
    from parrot.manager.manager import BotManager
    app = web.Application()
    manager = BotManager()
    # BotManager.setup_app may require extra init — adapt to the real
    # signature; skip the test with an explanatory reason if the bootstrap
    # requires a database.
    manager.setup_app(app)
    paths = {r.canonical for r in app.router.resources()}
    expected = {
        "/api/v1/agents/infographic/templates",
        "/api/v1/agents/infographic/templates/{template_name}",
        "/api/v1/agents/infographic/themes",
        "/api/v1/agents/infographic/themes/{theme_name}",
        "/api/v1/agents/infographic/{agent_id}",
    }
    missing = expected - paths
    assert not missing, f"Missing routes: {missing}"
```

Note: if `BotManager.setup_app` has required dependencies that prevent the
smoke test from running in isolation, replace the assertion with a
`pytest.skip("requires full BotManager bootstrap")` and rely on TASK-652's
integration test instead. Document the choice in the Completion Note.

---

## Agent Instructions

1. Read the spec and TASK-650's completed file to confirm `InfographicTalk`
   exists and its dispatch reads `match_info["resource"]`.
2. Update `packages/ai-parrot/src/parrot/manager/manager.py` per the
   sketch above.
3. Update status in `sdd/tasks/.index.json` → `"in-progress"`.
4. Run the smoke test or, if the full bootstrap is required, run
   `python -c "from parrot.manager.manager import BotManager"` to confirm
   the module still imports.
5. Run `ruff check packages/ai-parrot/src/parrot/manager/manager.py`.
6. Verify acceptance criteria.
7. Move this file to `sdd/tasks/completed/TASK-651-route-registration.md`
   and update index → `"done"`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
