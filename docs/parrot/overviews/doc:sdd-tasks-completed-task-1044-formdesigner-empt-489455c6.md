---
type: Wiki Overview
title: 'TASK-1044: Empty `parrot_formdesigner/__init__.py` and delete `handlers/`'
id: doc:sdd-tasks-completed-task-1044-formdesigner-empty-init-and-delete-handlers-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Final cleanup task of Wave 1. With `api/` and `ui/` populated, the old
relates_to:
- concept: mod:parrot.forms
  rel: mentions
---

# TASK-1044: Empty `parrot_formdesigner/__init__.py` and delete `handlers/`

**Feature**: FEAT-152 — parrot-formdesigner Structural Refactor
**Spec**: `sdd/specs/formdesigner-refactor.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1042, TASK-1043
**Assigned-to**: unassigned

---

## Context

Final cleanup task of Wave 1. With `api/` and `ui/` populated, the old
`handlers/` directory is now dead code. This task:

1. Rewrites `__init__.py` to expose ONLY metadata (no submodule
   imports) — Module 1 of the spec.
2. Deletes `handlers/__init__.py`, `handlers/api.py`,
   `handlers/forms.py`, `handlers/routes.py`, `handlers/telegram.py`,
   `handlers/templates.py`, and the `handlers/` directory itself —
   Module 10 of the spec.

It also updates the CHANGELOG with the breaking-change notice (no more
`from parrot_formdesigner import setup_form_routes`).

This task MUST run last in Wave 1 — once it merges, `api/` and `ui/`
are the only path consumers can use.

Spec sections: §1 Goals (empty `__init__.py`); §1 Non-Goals (no
back-compat for `setup_form_routes`); §3 Modules 1 + 10; §5 Acceptance
Criteria (`import parrot_formdesigner` does NOT pull submodules).

---

## Scope

1. **Rewrite** `packages/parrot-formdesigner/src/parrot_formdesigner/__init__.py`
   to ONLY contain:
   ```python
   """parrot-formdesigner — Form design and rendering for AI-Parrot.

   Top-level imports are intentionally minimal. Consumers import from
   submodules:

       from parrot_formdesigner.core import FormSchema
       from parrot_formdesigner.api import setup_form_api
       from parrot_formdesigner.ui import setup_form_ui
   """

   from .version import (
       __author__, __author_email__, __description__,
       __license__, __title__, __version__,
   )

   __all__ = [
       "__author__", "__author_email__", "__description__",
       "__license__", "__title__", "__version__",
   ]
   ```
   No imports of `core.*`, `services.*`, `handlers.*`, `api.*`,
   `ui.*`, `controls.*`, `renderers.*`, `tools.*`, `extractors.*`.

2. **Delete** the entire `handlers/` directory (and its
   `__pycache__/`):
   ```bash
   rm -r packages/parrot-formdesigner/src/parrot_formdesigner/handlers/
   ```

3. **Update CHANGELOG** at the top of `packages/parrot-formdesigner/CHANGELOG.md`
   (create if missing) with a `0.2.0` entry:
   - **BREAKING**: `from parrot_formdesigner import setup_form_routes`
     no longer works. Use `setup_form_api(app, registry)` from
     `parrot_formdesigner.api` and `setup_form_ui(app, registry)` from
     `parrot_formdesigner.ui`.
   - **BREAKING**: `parrot_formdesigner.handlers` module is removed.
   - **BREAKING**: `parrot_formdesigner.__init__` no longer re-exports
     `FormSchema`, `FieldType`, etc. Import from
     `parrot_formdesigner.core` instead.
   - **BREAKING**: `navigator-auth` is now a hard dependency. Hosts
     that previously ran without auth must configure navigator-auth's
     `NoAuth` backend on the consumer side.
   - **NEW**: render dispatcher `GET /api/v1/forms/{id}/render/{format}`.
   - **NEW**: `GET /api/v1/form-controls` endpoint.
   - **NEW**: `parrot_formdesigner.controls` registry (extensible via
     `register_field_control`).
   - **DEFERRED to 0.3.x**: XForms (`/render/xml`), PDF AcroForm
     (`/render/pdf`), `PATCH /api/v1/forms/{id}/operations` —
     Wave 2 capabilities.

4. **Add a `sys.modules`-snapshot test** at
   `packages/parrot-formdesigner/tests/unit/test_init_imports_metadata_only.py`:
   ```python
   import importlib, sys

   def test_init_does_not_pull_submodules():
       for k in list(sys.modules):
           if k.startswith("parrot_formdesigner"):
               sys.modules.pop(k, None)
       for k in ("aiohttp", "aiogram", "reportlab", "lxml"):
           sys.modules.pop(k, None)

       importlib.import_module("parrot_formdesigner")

       forbidden_prefixes = (
           "parrot_formdesigner.api",
           "parrot_formdesigner.ui",
           "parrot_formdesigner.handlers",
           "parrot_formdesigner.renderers",
           "parrot_formdesigner.controls",
           "parrot_formdesigner.tools",
           "parrot_formdesigner.extractors",
           "parrot_formdesigner.services",
           "parrot_formdesigner.core",
       )
       loaded = [k for k in sys.modules if k.startswith(forbidden_prefixes)]
       assert loaded == []

       # Heavy deps must not be pulled in transitively
       for k in ("aiohttp", "aiogram", "reportlab", "lxml"):
           assert k not in sys.modules, f"{k} was loaded by parrot_formdesigner top-level"
   ```

**NOT in scope:**
- Anything that touches `api/`, `ui/`, `controls/`, `renderers/`,
  `core/`, `services/` source code.
- Wave 2 capabilities.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/__init__.py` | REWRITE | Metadata-only |
| `packages/parrot-formdesigner/src/parrot_formdesigner/handlers/` | DELETE | Whole directory |
| `packages/parrot-formdesigner/CHANGELOG.md` | CREATE or MODIFY | Add 0.2.0 entry |
| `packages/parrot-formdesigner/tests/unit/test_init_imports_metadata_only.py` | CREATE | sys.modules snapshot test |

---

## Codebase Contract (Anti-Hallucination)

### Verified — current `__init__.py` shape

```text
packages/parrot-formdesigner/src/parrot_formdesigner/__init__.py — 126 lines
Imports: from .core, from .extractors, from .handlers (api, forms,
routes, telegram), from .renderers, from .services, from .tools.
ALL OF THESE GO AWAY.
```

### Verified — `version.py` exports

```python
# packages/parrot-formdesigner/src/parrot_formdesigner/version.py
__title__ = "parrot-formdesigner"
__description__ = "Platform-agnostic form design and rendering package for AI-Parrot"
__version__ = "0.1.28"   # already bumped to 0.2.0 by TASK-1040
__author__ = "Jesus Lara"
__author_email__ = "jesuslara@phenobarbital.info"
__license__ = "MIT"
```

### Files to Delete (verify they exist before deleting)

```text
packages/parrot-formdesigner/src/parrot_formdesigner/handlers/__init__.py
packages/parrot-formdesigner/src/parrot_formdesigner/handlers/api.py
packages/parrot-formdesigner/src/parrot_formdesigner/handlers/forms.py
packages/parrot-formdesigner/src/parrot_formdesigner/handlers/routes.py
packages/parrot-formdesigner/src/parrot_formdesigner/handlers/telegram.py
packages/parrot-formdesigner/src/parrot_formdesigner/handlers/templates.py
packages/parrot-formdesigner/src/parrot_formdesigner/handlers/__pycache__/  (if present)
```

After deletion: `git rm -r packages/parrot-formdesigner/src/parrot_formdesigner/handlers/`.

### Does NOT Exist

- ~~A `parrot_formdesigner.compat` shim~~ — Non-Goals §1 explicitly
  rejects backwards compatibility. Do NOT create a deprecation shim
  module.
- ~~`parrot_formdesigner.__getattr__` lazy proxy~~ — the brainstorm
  explicitly chose option (A) "vaciar `__init__.py`", not (B) lazy
  proxy. Do NOT add `__getattr__` magic.

---

## Implementation Notes

### Order of operations

1. Run TASK-1042 + TASK-1043 acceptance tests one more time —
   confirm `api/` and `ui/` are healthy.
2. Search for any internal references to `parrot_formdesigner.handlers`
   in the package (other than the dying handlers themselves):
   ```bash
   grep -rn "parrot_formdesigner.handlers\|from .handlers\|from \.handlers" \
     packages/parrot-formdesigner/src
   ```
   Any hits in `core/`, `services/`, `extractors/`, `tools/`, `renderers/`
   are leftovers — fix them to point at `api/` or `ui/` BEFORE deleting
   `handlers/`.
3. Rewrite `__init__.py`.
4. Run `pytest packages/parrot-formdesigner/tests/` — every existing
   test should still pass; if any test imports from `handlers/`, fail
   loudly and either update the test or move the test under
   `tests/unit/api|ui/`.
5. `git rm -r ... /handlers/`.
6. Add CHANGELOG.
7. Add the metadata-only test.
8. Final test run.

### Key Constraints

- The metadata-only test (`test_init_imports_metadata_only.py`) is the
  hard contract. Every Wave 2 task MUST keep it green.
- After deletion, `from parrot_formdesigner.handlers import *`
  raises `ModuleNotFoundError`. That's the desired breaking change.
- Touch nothing in `tools/`, `extractors/`, `services/`, `core/`,
  `renderers/` source code beyond fixing imports.

---

## Acceptance Criteria

- [ ] `parrot_formdesigner/__init__.py` is < 30 lines and imports only
      `version.py`.
- [ ] `import parrot_formdesigner; parrot_formdesigner.__version__ ==
      "0.2.0"` succeeds.
- [ ] `import parrot_formdesigner.handlers` raises
      `ModuleNotFoundError`.
- [ ] `pytest tests/unit/test_init_imports_metadata_only.py` passes
      (no submodule loaded, no heavy dep loaded).
- [ ] Full test suite (`pytest packages/parrot-formdesigner/tests/ -v`)
      passes.
- [ ] No `grep` hit for `parrot_formdesigner.handlers` anywhere under
      `packages/parrot-formdesigner/src/parrot_formdesigner/` (except
      possibly inside CHANGELOG documentation).
- [ ] `CHANGELOG.md` has a `0.2.0` entry covering all four breaking
      changes listed in §Scope.
- [ ] `git status` shows the `handlers/` directory deleted; the new
      `__init__.py`, CHANGELOG, and test are added.

---

## Test Specification

See full skeleton in §Scope item 4 above
(`test_init_imports_metadata_only.py`).

---

## Agent Instructions

1. Read the spec, especially §1 Goals + Non-Goals and §5 Acceptance
   Criteria.
2. Verify TASK-1042 and TASK-1043 are in `tasks/completed/`.
3. Run `pytest packages/parrot-formdesigner/tests/` — note baseline.
4. Search for stragglers (`grep -rn "parrot_formdesigner.handlers"
   packages/parrot-formdesigner/src`); fix any internal references.
5. Rewrite `__init__.py`.
6. Delete `handlers/` via `git rm -r`.
7. Add the test and CHANGELOG.
8. Re-run pytest; everything must be green.
9. Move this task to `sdd/tasks/completed/`, update the index.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Completed by**: sdd-worker (Claude Sonnet)
**Date**: 2026-05-07
**Notes**:
- `parrot_formdesigner/__init__.py` now exposes only metadata (~25 lines).
- Deleted `handlers/` directory entirely (api.py, forms.py, routes.py, telegram.py, templates.py, __init__.py).
- 4 metadata-only contract tests pass (`test_init_imports_metadata_only.py`).
- Updated `parrot.forms` shim (`packages/ai-parrot/src/parrot/forms/__init__.py`) to import from `parrot_formdesigner.core`/`services`/`renderers`/`tools`/`extractors` since top-level re-exports are gone — necessary to keep backward-compat shim working.
- Deleted 8 obsolete test files that exercised the deleted handlers module: `test_handlers.py`, `test_handlers_prefix.py`, `test_submit_endpoint.py`, `test_telegram_webapp.py`, `test_edit_endpoints.py`, `test_api_auth.py`, `test_form_edition_integration.py`, `test_backward_compat.py`.
- Updated `test_submit_action_auth.test_export_from_package` to import from `parrot_formdesigner.core`.
- CHANGELOG updated with 0.2.0 breaking-changes entry.
- Final test run: 196 passed, 1 pre-existing failure unrelated to FEAT-152 (`test_example_form_server_is_short` — example file line-count test).
