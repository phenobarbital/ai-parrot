---
type: Wiki Overview
title: 'TASK-1244: Caller updates — tools, uploads, render, operations'
id: doc:sdd-tasks-completed-task-1244-caller-updates-tools-uploads-render-ops-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements Module 5 of the spec. Mirror of TASK-1243 for the remaining call
---

# TASK-1244: Caller updates — tools, uploads, render, operations

**Feature**: FEAT-183 — FormRegistry Multi-Tenancy
**Spec**: `sdd/specs/formregistry-multi-tenancy.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1239
**Assigned-to**: unassigned

---

## Context

Implements Module 5 of the spec. Mirror of TASK-1243 for the remaining call
sites: tools, uploads, render, and operations. Same pattern (kwarg-only
`tenant=` on every registry call), different tenant sources depending on
the execution context (tool execution context vs. HTTP request).

---

## Scope

Update every `registry.get / contains / unregister / list_forms /
list_form_ids / register / clear` call site in:

- **`packages/parrot-formdesigner/src/parrot_formdesigner/tools/database_form.py`**
  - line 213: `await self._registry.register(form, persist=persist)`
- **`packages/parrot-formdesigner/src/parrot_formdesigner/tools/create_form.py`**
  - line 306: `existing = await self._registry.get(refine_form_id)`
  - line 366: `await self._registry.register(...)` (multi-line call —
    re-verify the exact line range when editing)
- **`packages/parrot-formdesigner/src/parrot_formdesigner/api/uploads.py`**
  - line 231: `form = await registry.get(form_id)`
- **`packages/parrot-formdesigner/src/parrot_formdesigner/api/render.py`**
  - line 127: `form = await registry.get(form_id)`
- **`packages/parrot-formdesigner/src/parrot_formdesigner/api/operations.py`**
  - line 383: `form = await registry.get(form_id)`
  - line 459: `await registry.register(working, persist=True, overwrite=True)`

For each call, pass `tenant=` resolved from the surrounding context:
- **Tools** (`database_form.py`, `create_form.py`): the tool execution
  context. Tools generally carry tenant via their input schema or the
  enclosing toolkit's configuration. Read each tool's `__init__` and any
  config object to find the tenant attribute. If tenant is not yet
  threaded through to the tool, add it minimally — the AbstractToolkit
  pattern in `parrot/tools/` is the reference.
- **`api/uploads.py`, `api/render.py`, `api/operations.py`**: aiohttp
  request handlers; tenant comes from the same request accessor used by
  TASK-1243 (consult that task's Completion Note for the exact pattern).

Also: if any of these call sites pass a `FormSchema` with `form.tenant=None`
to `register()`, set the tenant on the form before calling (via
`form.model_copy(update={"tenant": resolved_tenant})`) or pass `tenant=` to
`register()`. With `require_tenant=True`, a `None`-tenant `register()`
raises `ValueError`.

**NOT in scope**:
- Files covered by TASK-1243.
- `on_unregister` callback consumer updates (TASK-1245).
- Test additions (final sweep in TASK-1246).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/tools/database_form.py` | MODIFY | Plumb tenant into the `register()` call (line 213). |
| `packages/parrot-formdesigner/src/parrot_formdesigner/tools/create_form.py` | MODIFY | Plumb tenant into get/register (lines 306, 366). |
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/uploads.py` | MODIFY | Plumb tenant into get (line 231). |
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/render.py` | MODIFY | Plumb tenant into get (line 127). |
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/operations.py` | MODIFY | Plumb tenant into get/register (lines 383, 459). |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# Already present in these files; no new imports needed beyond what each file
# already pulls in:
from parrot_formdesigner.services import FormRegistry      # services/__init__.py:8
from parrot_formdesigner.core.schema import FormSchema     # core/schema.py:154
```

### Existing Signatures to Use

Same as TASK-1243's contract:

```python
class FormRegistry:
    async def get(self, form_id: str, *, tenant: str | None = None) -> FormSchema | None: ...
    async def register(
        self, form: FormSchema, *,
        persist: bool = False, overwrite: bool = True, tenant: str | None = None,
    ) -> None: ...
```

For the tools, the AbstractToolkit pattern lives at:
```python
# packages/parrot-formdesigner/src/parrot_formdesigner/tools/services/abstract.py
# (Read this file before editing tool call sites — it shows how the toolkit
# threads runtime state, including any tenant context.)
```

### Does NOT Exist

- ~~`tool.context.tenant` (or any similar magic attribute)~~ — verify the
  tool's actual context shape before referencing.
- ~~`registry.get_for_tool(...)`~~ — there is no such helper. Plumb tenant
  through the tool's `__init__` or its call args.
- ~~A "current tenant" thread-local~~ — out of scope (spec Non-Goals).

---

## Implementation Notes

### Pattern to Follow

For tools, the tenant typically flows in via the tool's constructor or its
input schema. Example (sketch):

```python
# Before
class CreateFormTool:
    def __init__(self, registry: FormRegistry, ...):
        self._registry = registry

    async def _arun(self, form_id: str, ...):
        existing = await self._registry.get(form_id)

# After
class CreateFormTool:
    def __init__(self, registry: FormRegistry, *, tenant: str, ...):
        self._registry = registry
        self._tenant = tenant   # bound at toolkit-construction time

    async def _arun(self, form_id: str, ...):
        existing = await self._registry.get(form_id, tenant=self._tenant)
```

Choose whichever shape matches the surrounding tool architecture — input-schema
field, constructor arg, or session-bound context. Don't over-engineer.

For aiohttp handlers in `api/uploads.py`, `api/render.py`, `api/operations.py`:
use the same accessor that TASK-1243 settled on. Reference TASK-1243's
Completion Note for the exact resolver.

### Key Constraints

- kwarg `tenant=` always.
- Tool tenant must NOT be hard-coded `"navigator"` — it must come from
  the toolkit's configuration or the tool's call args.
- For `register()`: if the form's tenant is `None`, set it before calling
  OR pass `tenant=` to `register()` explicitly. With `require_tenant=True`,
  the call will raise otherwise.
- Maintain existing return shapes and error handling.

### References in Codebase

- `packages/parrot-formdesigner/src/parrot_formdesigner/tools/services/abstract.py`
  — toolkit/services scaffold.
- TASK-1243's Completion Note (after it lands) — tenant accessor for
  aiohttp handlers.

---

## Acceptance Criteria

- [ ] Every targeted call site (5 files, 7 call sites) passes `tenant=`
      explicitly.
- [ ] No hard-coded tenant strings in production paths.
- [ ] `grep -n "self\._registry\.\|self\.registry\.\| registry\." packages/parrot-formdesigner/src/parrot_formdesigner/{tools,api/uploads.py,api/render.py,api/operations.py}`
      shows zero un-tenant'd calls (the grep should be refined to ignore
      docstrings/comments).
- [ ] `pytest packages/parrot-formdesigner/tests/unit/test_database_form_tool_dispatch.py packages/parrot-formdesigner/tests/integration/test_operations_e2e.py packages/parrot-formdesigner/tests/integration/test_upload_rest.py packages/parrot-formdesigner/tests/integration/test_render_*.py -v`
      passes.
- [ ] `ruff check` clean for the modified files.

---

## Test Specification

No new unit tests — existing test files (listed above) MUST continue to
pass. Update test fixtures to supply tenant where the existing tests
construct tools / handlers.

End-to-end propagation tests live in TASK-1246.

---

## Agent Instructions

1. **Read the spec** §3 Module 5.
2. **Check dependencies**: TASK-1239 done. Read TASK-1243's Completion Note
   for the aiohttp tenant accessor pattern.
3. **For tools**: read each tool's source and its `__init__` / call-site to
   find the cleanest place to add tenant. Read `services/abstract.py` for
   the surrounding pattern.
4. **For aiohttp handlers** (`uploads.py`, `render.py`, `operations.py`):
   reuse TASK-1243's accessor.
5. **Edit and run tests** per Acceptance Criteria.
6. **Move this file** to `sdd/tasks/completed/`.
7. **Update index** → `done`.
8. **Fill in the Completion Note** with the tenant resolver used per tool.

---

## Completion Note

**Completed by**: sdd-worker (claude-sonnet-4-6)
**Date**: 2026-05-19
**Notes**: Tenant resolver per tool/handler:
- database_form.py: Added `tenant: str | None = None` kwarg to `__init__`; stored as `self._tenant`; passed to `register()`.
- create_form.py: Added `tenant: str | None = None` kwarg to `__init__`; stored as `self._tenant`; passed to `get()` and `register()`.
- api/uploads.py: Added `_get_request_tenant(request)` call before `registry.get()`.
- api/render.py: Same pattern — `_get_request_tenant(request)` before `registry.get()`.
- api/operations.py: `_get_request_tenant(request)` before `registry.get()` and `registry.register()`.
- api/_utils.py: Added shared `_get_request_tenant(request)` helper (mirrors `FormAPIHandler._get_tenant` from TASK-1243).
551 unit tests pass (excluding 1 pre-existing version-mismatch test).

**Deviations from spec**: None.
