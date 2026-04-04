# TASK-566: Package Integration & Exports

**Feature**: FEAT-081 parrot-formdesigner-renderer-telegram
**Spec**: `sdd/specs/parrot-formdesigner-renderer-telegram.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-562, TASK-563, TASK-564, TASK-565
**Assigned-to**: unassigned

---

## Context

Wire everything together: populate `renderers/telegram/__init__.py` exports, update
`renderers/__init__.py`, register routes in `setup_form_routes()`, and add `aiogram`
to `pyproject.toml`. Implements Spec Module 5.

---

## Scope

- Populate `renderers/telegram/__init__.py` with public exports:
  `TelegramRenderer`, `TelegramFormRouter`, `TelegramRenderMode`, `TelegramFormStep`,
  `TelegramFormPayload`.
- Update `renderers/__init__.py` to include `TelegramRenderer` in imports and `__all__`.
- Update `handlers/routes.py` `setup_form_routes()`:
  - Add `GET {p}/forms/{form_id}/telegram` route → `TelegramWebAppHandler.serve_webapp`.
  - Add `POST {p}/api/v1/forms/{form_id}/telegram-submit` route → `TelegramWebAppHandler.rest_fallback`.
- Add `aiogram>=3.12` to `pyproject.toml` dependencies.
- Add `templates/telegram_webapp.html.j2` to package-data glob in `pyproject.toml`.
- Verify all imports work end-to-end.

**NOT in scope**: Implementation of renderer, router, or handler logic (those are done).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot/formdesigner/renderers/telegram/__init__.py` | MODIFY | Add exports |
| `packages/parrot-formdesigner/src/parrot/formdesigner/renderers/__init__.py` | MODIFY | Add TelegramRenderer |
| `packages/parrot-formdesigner/src/parrot/formdesigner/handlers/routes.py` | MODIFY | Register telegram routes |
| `packages/parrot-formdesigner/pyproject.toml` | MODIFY | Add aiogram dep + template glob |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Current renderers/__init__.py exports (renderers/__init__.py:9-12):
from .adaptive_card import AdaptiveCardRenderer
from .base import AbstractFormRenderer
from .html5 import HTML5Renderer
from .jsonschema import JsonSchemaRenderer
# __all__ = ["AbstractFormRenderer", "AdaptiveCardRenderer", "HTML5Renderer", "JsonSchemaRenderer"]

# Current handlers/routes.py imports (handlers/routes.py:12-14):
from ..services.registry import FormRegistry
from .api import FormAPIHandler
from .forms import FormPageHandler

# Current pyproject.toml package-data (pyproject.toml:59-61):
# [tool.setuptools.package-data]
# "parrot.formdesigner" = ["py.typed"]
# "parrot.formdesigner.renderers" = ["templates/*.j2"]
```

### Existing Signatures to Use
```python
# packages/parrot-formdesigner/src/parrot/formdesigner/handlers/routes.py:20
def setup_form_routes(
    app: web.Application,
    *,
    registry: FormRegistry | None = None,
    client: "AbstractClient | None" = None,
    api_key: str | None = None,
    prefix: str = "",
) -> None:

# Current route registrations end at line 62:
#   app.router.add_post(f"{p}/api/v1/forms/{{form_id}}/validate", api.validate)
```

### Does NOT Exist
- ~~`setup_form_routes()` telegram kwarg~~ — does not accept any telegram-specific parameter; handler is instantiated internally
- ~~`parrot.formdesigner.renderers.TelegramRenderer`~~ — not yet in __init__.py; this task adds it

---

## Implementation Notes

### Key Constraints
- Import `TelegramWebAppHandler` lazily or with a try/except in `routes.py` if we want
  the formdesigner to remain usable without aiogram installed. However, per brainstorm
  decision, aiogram is a hard requirement, so direct import is fine.
- The `pyproject.toml` template glob already covers `templates/*.j2` — since the new
  template is in the same directory, it's already included. Verify this.
- Route registration order: Telegram routes must be added BEFORE the catch-all
  `/forms/{form_id}` GET route, or aiohttp will match the wrong handler. Check that
  `/forms/{form_id}/telegram` is registered before `/forms/{form_id}`.

### Pattern to Follow
```python
# In renderers/__init__.py, add:
from .telegram import TelegramRenderer
# In __all__, add "TelegramRenderer"

# In routes.py, add after existing page routes:
from .telegram import TelegramWebAppHandler
telegram = TelegramWebAppHandler(registry=registry)
app.router.add_get(f"{p}/forms/{{form_id}}/telegram", telegram.serve_webapp)
app.router.add_post(f"{p}/api/v1/forms/{{form_id}}/telegram-submit", telegram.rest_fallback)
```

---

## Acceptance Criteria

- [ ] `from parrot.formdesigner.renderers.telegram import TelegramRenderer, TelegramFormRouter` works
- [ ] `from parrot.formdesigner.renderers import TelegramRenderer` works
- [ ] `setup_form_routes()` registers `/forms/{form_id}/telegram` and `/api/v1/forms/{form_id}/telegram-submit`
- [ ] `aiogram>=3.12` is in `pyproject.toml` dependencies
- [ ] `telegram_webapp.html.j2` is included in package-data
- [ ] No existing tests broken
- [ ] Route ordering: `/forms/{form_id}/telegram` matches before `/forms/{form_id}`

---

## Test Specification

```python
# Verification tests (can be added to existing test files):
def test_telegram_renderer_importable():
    from parrot.formdesigner.renderers import TelegramRenderer
    assert TelegramRenderer is not None

def test_telegram_router_importable():
    from parrot.formdesigner.renderers.telegram import TelegramFormRouter
    assert TelegramFormRouter is not None
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/parrot-formdesigner-renderer-telegram.spec.md`
2. **Check dependencies** — verify TASK-562, 563, 564, 565 are all completed
3. **Verify the Codebase Contract** — re-read routes.py and __init__.py files
4. **Update status** in `tasks/.index.json` → `"in-progress"`
5. **Implement** following the scope and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-566-telegram-package-integration.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
