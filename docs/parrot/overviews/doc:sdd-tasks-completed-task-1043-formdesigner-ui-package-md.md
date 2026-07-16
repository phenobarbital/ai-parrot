---
type: Wiki Overview
title: 'TASK-1043: Build `parrot_formdesigner.ui` package — HTML pages + Telegram
  WebApp'
id: doc:sdd-tasks-completed-task-1043-formdesigner-ui-package-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Wave 1, Step 1 (UI half) of FEAT-152 splits the HTML pages and
---

# TASK-1043: Build `parrot_formdesigner.ui` package — HTML pages + Telegram WebApp

**Feature**: FEAT-152 — parrot-formdesigner Structural Refactor
**Spec**: `sdd/specs/formdesigner-refactor.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1042
**Assigned-to**: unassigned

---

## Context

Wave 1, Step 1 (UI half) of FEAT-152 splits the HTML pages and
Telegram WebApp routes out of `handlers/` into a new opt-in `ui/`
sub-package. The host app calls `setup_form_ui(app, registry,
protect_pages=True)` to mount these. Telegram routes stay public
(Telegram has to hit them); HTML page routes honour `protect_pages`
via the same `_page_wrap` mechanism that `handlers/routes.py:_wrap_auth`
currently uses.

Per Q3 (resolved): `templates.py` stays as a single file (457 LoC of
inline HTML) — this task moves it verbatim, no per-page split.

Spec sections: §2 Architectural Design (`setup_form_ui`); §3 Module 3;
§7 Patterns to Follow ("`tools/` stays at the package root").

---

## Scope

Create the following under
`packages/parrot-formdesigner/src/parrot_formdesigner/ui/`:

1. **`__init__.py`** — exports `setup_form_ui`. No side-effect imports.
2. **`templates.py`** — VERBATIM move of
   `handlers/templates.py` (457 LoC). Update no behaviour; only the
   import path changes for callers.
3. **`handlers.py`** — VERBATIM move of `FormPageHandler` from
   `handlers/forms.py`. Update internal imports to point at
   `parrot_formdesigner.ui.templates` (and any other moved modules).
4. **`telegram.py`** — VERBATIM move of `TelegramWebAppHandler` from
   `handlers/telegram.py`. Same import-path-only adjustments.
5. **`routes.py`** —
   ```python
   from navigator_auth.decorators import is_authenticated, user_session
   ```
   (HARD import, same policy as `api/routes.py`.) Define
   `setup_form_ui(app, registry, *, base_path="", protect_pages=True)`.
   - Telegram WebApp routes (`/forms/{form_id}/telegram` and any
     fallback) registered WITHOUT `is_authenticated` — they are public
     by design (Telegram clients hit them).
   - HTML page routes (`/`, `/gallery`, `/forms/{form_id}`,
     `/forms/{form_id}/schema` (HTML-rendered schema page),
     `/forms/{form_id}` POST) honor `protect_pages=True` via a local
     `_page_wrap` analogous to the current `handlers/routes.py:41-79`
     implementation. When `protect_pages=False`, the wrapper is a no-op.

   Route table — match what `handlers/routes.py:setup_form_routes`
   currently mounts under the UI half (the part NOT handled by
   `setup_form_api`):

   | Method | Path | Handler | Auth |
   |---|---|---|---|
   | GET | `/` | `FormPageHandler.index` | _page_wrap(protect_pages) |
   | GET | `/gallery` | `FormPageHandler.gallery` | _page_wrap(protect_pages) |
   | GET | `/forms/{form_id}` | `FormPageHandler.form_page` | _page_wrap(protect_pages) |
   | POST | `/forms/{form_id}` | `FormPageHandler.form_submit` | _page_wrap(protect_pages) |
   | GET | `/forms/{form_id}/telegram` | `TelegramWebAppHandler.render_form` | NONE (public) |
   | (any other route currently in routes.py:setup_form_routes that is HTML/Telegram, NOT REST) | | |

   **Open the existing `handlers/routes.py:82-164` and use it as the
   contract for which routes belong here.** Anything starting with
   `/api/v1/` belongs to TASK-1042 (api package); everything else is
   ours.

   `setup_form_ui` MUST also store the registry on
   `app["form_registry"]` if not already set (to support hosts that
   only mount UI without API).

6. **Tests** under `packages/parrot-formdesigner/tests/unit/ui/`:
   - `test_setup_form_ui_routes.py` — every UI route is registered;
     Telegram route has NO `is_authenticated` wrapper.
   - `test_setup_form_ui_protect_pages.py` — when
     `protect_pages=True`, HTML routes go through `_page_wrap`;
     when `False`, they don't.
   - `test_ui_imports.py` — `from parrot_formdesigner.ui import
     setup_form_ui` succeeds; `setup_form_ui` does NOT trigger an
     import of `parrot_formdesigner.api` (verified via
     `sys.modules` snapshot).

**NOT in scope:**
- Splitting `templates.py` per page (Q3 resolved: stay monolithic).
- Deleting `handlers/forms.py`, `handlers/telegram.py`,
  `handlers/templates.py` (TASK-1044 deletes the whole `handlers/`
  folder).
- Touching `handlers/routes.py` or `handlers/api.py`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/ui/__init__.py` | CREATE | Re-export `setup_form_ui` |
| `packages/parrot-formdesigner/src/parrot_formdesigner/ui/templates.py` | CREATE (move) | Verbatim from `handlers/templates.py` |
| `packages/parrot-formdesigner/src/parrot_formdesigner/ui/handlers.py` | CREATE (move) | `FormPageHandler` from `handlers/forms.py` |
| `packages/parrot-formdesigner/src/parrot_formdesigner/ui/telegram.py` | CREATE (move) | `TelegramWebAppHandler` from `handlers/telegram.py` |
| `packages/parrot-formdesigner/src/parrot_formdesigner/ui/routes.py` | CREATE | `setup_form_ui` with hard nav-auth import + `_page_wrap` |
| `packages/parrot-formdesigner/tests/unit/ui/test_setup_form_ui_routes.py` | CREATE | |
| `packages/parrot-formdesigner/tests/unit/ui/test_setup_form_ui_protect_pages.py` | CREATE | |
| `packages/parrot-formdesigner/tests/unit/ui/test_ui_imports.py` | CREATE | |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# What ui/ uses
from parrot_formdesigner.core.schema import FormSchema
from parrot_formdesigner.services.registry import FormRegistry
from parrot_formdesigner.renderers.html5 import HTML5Renderer
from parrot_formdesigner.renderers.telegram.renderer import TelegramRenderer  # path verified at packages/parrot-formdesigner/src/parrot_formdesigner/renderers/telegram/renderer.py
from navigator_auth.decorators import is_authenticated, user_session
from aiohttp import web
```

### Existing Code to Migrate

```python
# packages/parrot-formdesigner/src/parrot_formdesigner/handlers/forms.py
class FormPageHandler:
    """HTML page handler for form designer UI. Methods: index, gallery,
    form_page (GET), form_submit (POST). Reads templates from
    handlers/templates.py."""

# packages/parrot-formdesigner/src/parrot_formdesigner/handlers/telegram.py
class TelegramWebAppHandler:
    """Telegram WebApp page handler. Method: render_form. Public — no auth."""

# packages/parrot-formdesigner/src/parrot_formdesigner/handlers/templates.py
# 457-line module of inline HTML strings + render helpers. Move verbatim.

# packages/parrot-formdesigner/src/parrot_formdesigner/handlers/routes.py:41-79
def _wrap_auth(handler):
    """If _AUTH_AVAILABLE, decorate with is_authenticated; else passthrough.
    Inner _inner is the unwrapped passthrough variant. Replace with
    a hard-import version that always wraps when protect=True."""
def setup_form_routes(...):  # line 82
    """Currently mounts BOTH api routes (under /api/v1/...) AND ui routes.
    The ui half is what this task migrates."""
```

### `_page_wrap` reference shape (for ui/routes.py)

```python
# Replacement for handlers/routes.py:_wrap_auth, simplified for hard-auth world.
def _page_wrap(handler, *, protect: bool):
    """If protect, wrap with is_authenticated; else return as-is."""
    if protect:
        return is_authenticated()(handler)
    return handler
```

### Does NOT Exist

- ~~`FormPageHandler.render_form_pdf()`~~ — no PDF method on the UI
  side. PDF lives in `renderers/pdf.py` (Wave 2b, TASK-1046).
- ~~`TelegramWebAppHandler.send_form()`~~ — does not exist; the
  handler only renders the WebApp page. Sending happens via
  `parrot_formdesigner.tools/` agents, which are out of scope here.
- ~~A `templates.html_index` function~~ — verify the actual function
  names in `handlers/templates.py` before importing them in
  `ui/handlers.py`. They are likely things like `render_index`,
  `render_gallery`, etc.; preserve the exact names.
- ~~`session = await user_session(request)` inside `_page_wrap`~~ —
  `_page_wrap` does NOT call `user_session`. That's an inner-handler
  concern; only `is_authenticated` gates entry.

---

## Implementation Notes

### Pattern to Follow

1. **Open `handlers/forms.py`, `handlers/telegram.py`,
   `handlers/templates.py`** in your editor.
2. Copy each file VERBATIM into its `ui/` counterpart.
3. Update only:
   - Internal cross-imports (e.g.
     `from parrot_formdesigner.handlers.templates import X`
     → `from parrot_formdesigner.ui.templates import X`).
   - Anything currently doing `from parrot_formdesigner.handlers.api
     import _bump_version` etc. now points to
     `parrot_formdesigner.api._utils`.
4. Build `ui/routes.py` from scratch but mirror the route table from
   `handlers/routes.py:setup_form_routes` (UI half only).
5. **Do NOT delete the old files** — TASK-1044 owns deletion.

### Key Constraints

- Telegram routes MUST remain public (no `is_authenticated`).
- `protect_pages=True` is the default — production-safe by default.
- `setup_form_ui` MUST be importable WITHOUT
  `parrot_formdesigner.api` being imported first
  (test `test_ui_imports.py` enforces this).
- Logger: `logger = logging.getLogger(__name__)` at module top in
  `routes.py`.

### `setup_form_ui` skeleton

```python
def setup_form_ui(
    app: web.Application,
    registry: FormRegistry,
    *,
    base_path: str = "",
    protect_pages: bool = True,
) -> None:
    app.setdefault("form_registry", registry)
    page = FormPageHandler(registry=registry)
    tg = TelegramWebAppHandler(registry=registry)
    app.router.add_get(f"{base_path}/", _page_wrap(page.index, protect=protect_pages))
    app.router.add_get(f"{base_path}/gallery", _page_wrap(page.gallery, protect=protect_pages))
    app.router.add_get(f"{base_path}/forms/{{form_id}}",
                       _page_wrap(page.form_page, protect=protect_pages))
    app.router.add_post(f"{base_path}/forms/{{form_id}}",
                        _page_wrap(page.form_submit, protect=protect_pages))
    # Telegram — NO auth wrap
    app.router.add_get(f"{base_path}/forms/{{form_id}}/telegram", tg.render_form)
```

(Adjust constructors to match the actual signatures in
`handlers/forms.py` / `handlers/telegram.py` once you've read them.)

---

## Acceptance Criteria

- [ ] `from parrot_formdesigner.ui import setup_form_ui` succeeds.
- [ ] `parrot_formdesigner.ui.templates` exposes the same module-level
      names as the old `handlers/templates.py`.
- [ ] `parrot_formdesigner.ui.handlers.FormPageHandler` and
      `parrot_formdesigner.ui.telegram.TelegramWebAppHandler` exist
      with the same signatures as their `handlers/` counterparts.
- [ ] After `setup_form_ui(app, registry)`, the route table matches
      the documented set; Telegram route has NO auth wrapper.
- [ ] `setup_form_ui(app, registry, protect_pages=False)` mounts HTML
      routes WITHOUT `is_authenticated` wrapping.
- [ ] `import parrot_formdesigner.ui` does NOT cause
      `parrot_formdesigner.api` to be imported (verified via
      `sys.modules`).
- [ ] All unit tests in `tests/unit/ui/` pass.
- [ ] No linting errors.

---

## Test Specification

```python
# tests/unit/ui/test_setup_form_ui_routes.py
from aiohttp import web
from parrot_formdesigner.ui import setup_form_ui
from parrot_formdesigner.services.registry import FormRegistry

def test_routes_mounted():
    app = web.Application()
    setup_form_ui(app, FormRegistry())
    paths = [r.resource.canonical for r in app.router.routes()]
    assert "/" in paths
    assert "/gallery" in paths
    assert "/forms/{form_id}" in paths
    assert "/forms/{form_id}/telegram" in paths


# tests/unit/ui/test_ui_imports.py
import sys, importlib

def test_importing_ui_does_not_pull_api():
    # snapshot: ensure api module is not loaded after importing ui
    for k in list(sys.modules):
        if k.startswith("parrot_formdesigner."):
            sys.modules.pop(k, None)
    importlib.import_module("parrot_formdesigner.ui")
    api_loaded = any(k.startswith("parrot_formdesigner.api")
                     for k in sys.modules)
    assert not api_loaded
```

---

## Agent Instructions

1. Read the spec; pay attention to §3 Module 3 and §6 Codebase Contract.
2. Verify TASK-1042 (api package) is in `tasks/completed/` — `ui/`
   does not import from `api/`, but order matters because TASK-1044
   depends on both.
3. Migrate the three files verbatim, then build `routes.py`.
4. Move this task to `sdd/tasks/completed/`, update the index.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Completed by**: sdd-worker (Claude Sonnet)
**Date**: 2026-05-07
**Notes**:
- Created `parrot_formdesigner/ui/` with `templates.py` (verbatim copy from handlers/templates.py — 457 LoC), `handlers.py` (`FormPageHandler`), `telegram.py` (`TelegramWebAppHandler`), and `routes.py` (`setup_form_ui` with HARD navigator-auth import + `_page_wrap` helper).
- Telegram routes are public (no auth wrapper); HTML page routes honour `protect_pages=True` (default).
- All 8 unit tests pass (`tests/unit/ui/`).
- Verified that `import parrot_formdesigner.ui` does NOT trigger `parrot_formdesigner.api` import (independence test).
- The `setup_form_ui` uses `app.setdefault("form_registry", registry)` so it doesn't clobber the registry set by `setup_form_api` when both are mounted together.
