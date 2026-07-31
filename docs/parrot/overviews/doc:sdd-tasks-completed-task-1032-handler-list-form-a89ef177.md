---
type: Wiki Overview
title: 'TASK-1032: Refactor `FormAPIHandler.list_forms()` — merged rich descriptors'
id: doc:sdd-tasks-completed-task-1032-handler-list-forms-merge-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: This task replaces the body of `FormAPIHandler.list_forms()` to merge
---

# TASK-1032: Refactor `FormAPIHandler.list_forms()` — merged rich descriptors

**Feature**: FEAT-148 — Enriched List of Created Forms in parrot-formdesigner
**Spec**: `sdd/specs/formbuilder-list-created-forms.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1028, TASK-1030
**Assigned-to**: unassigned

---

## Context

`GET /api/v1/forms` currently returns `{"forms": [<form_id>, ...]}`.
This task replaces the body of `FormAPIHandler.list_forms()` to merge
the in-memory `FormRegistry` with the optional `FormStorage` and emit
rich descriptors. This is the central change of FEAT-148. **The
response shape becomes a list of dicts, which is a documented breaking
change** (spec §1 Goals, §7 Known Risks).

Implements Module 4 of the spec.

---

## Scope

- Add a module-level helper `_loc_to_str(value) -> str | None` in
  `handlers/api.py` that flattens `LocalizedString` (`str | dict[str, str]`)
  to a plain string. Returns `None` for `None` and for empty values.
- Replace the body of `FormAPIHandler.list_forms`:
  1. `forms_in_memory = await self.registry.list_forms()` →
     `list[FormSchema]`. Build a dict `{form.form_id: form}` for
     dedupe lookups.
  2. If `self.registry._storage is not None`:
     - Call `await self.registry._storage.list_forms()` inside `try/except`.
     - On exception: `self.logger.warning("FormStorage.list_forms failed: %s", exc)` and continue with registry-only data.
  3. Build the merged dict keyed by `form_id`:
     - For every `FormSchema` from the registry, emit a descriptor
       with `source="memory"` and `created_at = _iso(form.created_at)`.
     - For every storage row, either:
       - the form is also in the registry → upgrade existing descriptor
         to `source="db"`, override `created_at` with the storage row's
         value (string), keep registry's `title`/`description`/`version`.
       - the form is NOT in the registry → add a new descriptor built
         from the storage dict (`source="db"`, `title`/`description`
         flattened via `_loc_to_str` for safety).
  4. Sort the final list by `form_id` ascending.
  5. `return web.json_response({"forms": <list>})`.

**Descriptor shape** (every key always present, values may be `None`):
```python
{
  "form_id": str,
  "title": str | None,
  "description": str | None,
  "version": str,
  "source": "memory" | "db",
  "created_at": str | None,   # ISO-8601 string or None
}
```

**NOT in scope**:
- Adding `org_id` / `programs` filtering (spec §1 Non-Goals).
- Pagination.
- Adding a public accessor for `FormRegistry._storage` — direct access
  mirrors `update_form()` and `patch_form()` (api.py:391, :442).
- Updating tests (TASK-1033).
- `FormSchema` schema change (TASK-1028) or storage change (TASK-1030).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot/formdesigner/handlers/api.py` | MODIFY | Replace `list_forms()` body (~lines 200-210) and add `_loc_to_str` module helper |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# Already present in api.py (lines 11-29):
from __future__ import annotations
import json
import logging
from typing import TYPE_CHECKING
from aiohttp import web
from pydantic import ValidationError
from ..core.schema import FormSchema, RenderedForm
from ..renderers.html5 import HTML5Renderer
from ..renderers.jsonschema import JsonSchemaRenderer
from ..services.registry import FormRegistry
from ..services.validators import FormValidator
# verified: packages/parrot-formdesigner/src/parrot/formdesigner/handlers/api.py:11-24
```

No new imports required. Do NOT import `datetime` here — `created_at`
strings come from `FormSchema.created_at` (already a `datetime`, easily
`.isoformat()`-ed) or from the storage dict (already an ISO string after
TASK-1030).

### Existing Signatures to Use

```python
# packages/parrot-formdesigner/src/parrot/formdesigner/handlers/api.py
class FormAPIHandler:                                     # line 85
    self.registry: FormRegistry                           # line 108
    self.logger: logging.Logger                           # line 115

    async def list_forms(self, request: web.Request) -> web.Response:  # line 200
        # Current body — REPLACE entirely:
        # form_ids = await self.registry.list_form_ids()         # line 209
        # return web.json_response({"forms": form_ids})          # line 210

# packages/parrot-formdesigner/src/parrot/formdesigner/services/registry.py
class FormRegistry:                                       # line 94
    self._forms: dict[str, FormSchema]                    # line 117
    self._storage: FormStorage | None                     # line 119
    async def list_forms(self) -> list[FormSchema]: ...   # line 204
    async def list_form_ids(self) -> list[str]: ...       # line 213  (no longer needed)

# packages/parrot-formdesigner/src/parrot/formdesigner/services/registry.py
class FormStorage(ABC):                                   # line 29
    async def list_forms(self) -> list[dict[str, str]]: ...  # line 85
    # After TASK-1030, dicts include: form_id, version, title, description, created_at

# packages/parrot-formdesigner/src/parrot/formdesigner/core/schema.py
class FormSchema(BaseModel):                              # line 107
    form_id: str
    version: str
    title: LocalizedString
    description: LocalizedString | None
    # AFTER TASK-1028:
    created_at: datetime | None

# packages/parrot-formdesigner/src/parrot/formdesigner/core/types.py
LocalizedString = str | dict[str, str]                    # line 13
```

### Existing private-attribute access pattern

Reaching into `self.registry._storage` is intentional — same pattern
used by:
- `update_form()` at `api.py:391`: `persist = self.registry._storage is not None`
- `patch_form()` at `api.py:442`: same.

### Does NOT Exist

- ~~`FormRegistry.list_descriptors()`~~ — does not exist.
- ~~`FormRegistry.list_forms_with_metadata()`~~ — does not exist.
- ~~`FormRegistry.storage` (public)~~ — only `_storage`.
- ~~`FormSchema.to_descriptor()`~~ — do not invent it.
- ~~`web.json_response(default=str)`~~ — do not pass `default=`; we
  serialize datetimes to strings ourselves before responding.
- ~~`asyncio.gather(...)` for the two list calls~~ — overkill; sequential
  awaits keep the logic readable and storage call is optional.

---

## Implementation Notes

### Helper

Place the helper at module level (above `FormAPIHandler`, near
`_deep_merge` and `_bump_version`):

```python
def _loc_to_str(value: object) -> str | None:
    """Flatten a LocalizedString (str | dict[str, str]) to a plain str.

    Mirrors the title-extraction pattern used in
    ``PostgresFormStorage.list_forms`` so the API and storage layers
    agree on rendering.

    Args:
        value: Raw value — string, ``{lang: text}`` dict, or ``None``.

    Returns:
        Plain string if a non-empty value was provided; ``None`` if the
        input is ``None`` or an empty string/dict.
    """
    if value is None:
        return None
    if isinstance(value, dict):
        value = next(iter(value.values()), None)
    if not value:
        return None
    return str(value)
```

### `list_forms` body skeleton

```python
async def list_forms(self, request: web.Request) -> web.Response:
    """GET /api/forms — List all registered forms with rich metadata.

    Merges in-memory FormRegistry entries with persisted FormStorage rows
    (when a storage backend is configured). Each entry includes form_id,
    title, description, version, source ("memory" | "db"), and an
    ISO-8601 created_at (or None).

    Args:
        request: Incoming HTTP request.

    Returns:
        JSON response ``{"forms": [<descriptor>, ...]}`` sorted by form_id.
    """
    in_memory = await self.registry.list_forms()
    descriptors: dict[str, dict] = {}

    for form in in_memory:
        ts = form.created_at
        descriptors[form.form_id] = {
            "form_id": form.form_id,
            "title": _loc_to_str(form.title),
            "description": _loc_to_str(form.description),
            "version": form.version,
            "source": "memory",
            "created_at": ts.isoformat() if ts is not None else None,
        }

    storage = self.registry._storage
    if storage is not None:
        try:
            persisted = await storage.list_forms()
        except Exception as exc:
            self.logger.warning("FormStorage.list_forms failed: %s", exc)
            persisted = []

        for row in persisted:
            fid = row.get("form_id")
            if not fid:
                continue
            existing = descriptors.get(fid)
            if existing is not None:
                # In both: registry wins for title/description/version,
                # storage wins for created_at; mark source as "db".
                existing["source"] = "db"
                if row.get("created_at") is not None:
                    existing["created_at"] = row["created_at"]
            else:
                descriptors[fid] = {
                    "form_id": fid,
                    "title": _loc_to_str(row.get("title")),
                    "description": _loc_to_str(row.get("description")),
                    "version": row.get("version", "1.0"),
                    "source": "db",
                    "created_at": row.get("created_at"),
                }

    forms = sorted(descriptors.values(), key=lambda d: d["form_id"])
    return web.json_response({"forms": forms})
```

### Key Constraints

- Do NOT import `datetime` at module top — only `FormSchema.created_at`
  needs it and it's already typed there.
- Do NOT mutate `FormSchema` instances — read-only.
- Do NOT swallow non-`Exception`-derived errors (`BaseException`); use
  bare `except Exception:`.
- Auth wrapping in `routes.py` is unchanged — do not touch it.

### References in Codebase

- `packages/parrot-formdesigner/src/parrot/formdesigner/handlers/api.py:391`
  and `:442` — same `_storage`-access pattern.
- `packages/parrot-formdesigner/src/parrot/formdesigner/services/storage.py:236-238`
  — original LocalizedString flattening to mirror in `_loc_to_str`.

---

## Acceptance Criteria

- [ ] Module-level helper `_loc_to_str` added in `handlers/api.py`.
- [ ] `FormAPIHandler.list_forms` body fully replaced — no call to
      `self.registry.list_form_ids()` remains in this method.
- [ ] Response is `{"forms": [<descriptor>, ...]}` where every descriptor
      has the keys `form_id`, `title`, `description`, `version`,
      `source`, `created_at`.
- [ ] When `self.registry._storage is None`, every descriptor has
      `source == "memory"`.
- [ ] When a form exists only in storage, its descriptor has
      `source == "db"` and `created_at` is the storage row's ISO-8601
      string (or `None`).
- [ ] When a form exists in both: one descriptor; `source == "db"`;
      registry's title/description/version preserved; storage's
      `created_at` used when present.
- [ ] Storage exceptions are logged via `self.logger.warning` and the
      handler still returns the registry-only payload (no 500).
- [ ] Result list sorted ascending by `form_id`.
- [ ] Endpoint stays at `GET /api/v1/forms` with the same auth wrapping
      (no edits in `routes.py`).
- [ ] No linting errors:
      `ruff check packages/parrot-formdesigner/src/parrot/formdesigner/handlers/api.py`.

---

## Test Specification

> Tests live in TASK-1033. Manual smoke test (run inside `.venv`):

```bash
pytest packages/parrot-formdesigner/tests/unit/test_handlers.py::TestFormAPIHandler -v
# Until TASK-1033 lands, the existing tests will fail because the
# response shape changed. That is expected — TASK-1033 fixes them.
```

---

## Agent Instructions

1. **Read the spec** §2 (Architectural Design — Overview, Component
   Diagram, New Public Interfaces) and §7 (Known Risks).
2. **Check dependencies** — TASK-1028 and TASK-1030 must be in
   `tasks/completed/`. If either is still pending, STOP and run them
   first.
3. **Verify the Codebase Contract**:
   - Confirm `api.py:200` is the `list_forms` method.
   - Confirm `FormSchema.created_at` exists (TASK-1028 effect).
   - Confirm `PostgresFormStorage.list_forms` returns the new keys
     (TASK-1030 effect).
4. **Implement** the helper + body replacement.
5. **Lint** the modified file.
6. **Move this file** to `sdd/tasks/completed/`.
7. **Update** `sdd/tasks/index/formbuilder-list-created-forms.json` →
   `"done"`.

---

## Completion Note

**Completed by**: sdd-worker (claude-sonnet-4-6)
**Date**: 2026-05-05
**Notes**: Added `_loc_to_str` module-level helper above `_bump_version`. Replaced `list_forms()` body with merge logic: registry forms get `source="memory"`, storage-only forms get `source="db"`, overlapping forms upgrade to `source="db"` with storage's `created_at` and registry's title/description/version. Storage failures caught and logged via `self.logger.warning`. Result sorted by `form_id` ascending. Ruff check clean.

**Deviations from spec**: none
