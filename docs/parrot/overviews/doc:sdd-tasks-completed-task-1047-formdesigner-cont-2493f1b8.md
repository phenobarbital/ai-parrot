---
type: Wiki Overview
title: 'TASK-1047: Form-controls REST contract tests + extension hooks'
id: doc:sdd-tasks-completed-task-1047-formdesigner-controls-rest-contract-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Wave 2c of FEAT-152 — parallelizable with TASK-1045 / 1046 / 1048.
---

# TASK-1047: Form-controls REST contract tests + extension hooks

**Feature**: FEAT-152 — parrot-formdesigner Structural Refactor
**Spec**: `sdd/specs/formdesigner-refactor.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1044
**Assigned-to**: unassigned

---

## Context

Wave 2c of FEAT-152 — parallelizable with TASK-1045 / 1046 / 1048.

Wave 1 (TASK-1042) already wires `GET /api/v1/form-controls` with the
seeded controls registry, so this task is primarily about **locking in
the response contract** and adding a small extension surface that
third-party consumers can use to extend the toolbar without forking.

Spec sections: §1 Goals (form controls registry); §2 Data Models
(`FieldControlMetadata`); §3 Module 8.

---

## Scope

1. **Response-shape contract test** at
   `packages/parrot-formdesigner/tests/integration/test_form_controls_contract.py`:
   - Boot aiohttp app, `setup_form_api(app, registry)`, hit
     `GET /api/v1/form-controls`.
   - Assert response is `{"controls": [<entry>, ...]}`.
   - Assert each entry has every key in the `FieldControlMetadata`
     model (no missing keys, no extra keys beyond what
     `model_dump()` produces).
   - Assert each entry's `type` ∈ `{ft.value for ft in FieldType}`
     OR equals one of the extension types added in this task's
     fixtures (see step 3).
   - Assert `len(controls) == len(FieldType)` when ONLY builtins are
     loaded.
2. **Stability test** —
   `tests/unit/controls/test_metadata_dump_keys.py`: dumping
   `FieldControlMetadata.model_dump()` produces exactly:
   `{"type", "label", "description", "category", "icon", "snippet",
   "render_hint", "supports_constraints", "is_container"}`.
   This guards against accidental field additions / renames in future
   PRs without a contract bump.
3. **Extension test** —
   `tests/unit/controls/test_extension_registration.py`:
   - Calls `register_field_control("rich_text", label="Rich Text",
     ...)` (string type, NOT a `FieldType` enum value) — exercising
     the `field_type: FieldType | str` overload from spec §2 New
     Public Interfaces.
   - Asserts the new entry appears in `get_controls()` and in the
     HTTP response.
4. **Documentation** — add a short docstring at the top of
   `parrot_formdesigner/controls/registry.py` (created by TASK-1041)
   documenting the extension pattern:
   ```python
   """Form-control registry.

   Extending the toolbar:

       from parrot_formdesigner.controls import register_field_control

       register_field_control(
           "rich_text",
           label="Rich Text",
           description="Rich text editor",
           category="advanced",
           icon="rich-text",
           snippet={"type": "string", "format": "rich-text"},
           render_hint="rich",
           supports_constraints=True,
       )

   Call this once at consumer startup, before `setup_form_api(app, registry)`
   is called (or any time before the first request — the seed and
   extensions live in the same module-level dict).
   """
   ```
   Updating an existing file written by TASK-1041 — coordinate via
   the `feat-152` worktree (this task lands AFTER Wave 1).

5. **OpenAPI / response-schema fixture** at
   `packages/parrot-formdesigner/tests/fixtures/form_controls_response_schema.json`:
   the JSON Schema for the `{"controls": [{...}]}` payload, used by
   the contract test and importable by downstream consumers (e.g. the
   form-designer UI team).

**NOT in scope:**
- Adding any new `FieldType` enum values (keep `FieldType` stable —
  only string-keyed extension types are exercised).
- Localization of `label` / `description`.
- Modifying the controls handler in `api/controls.py` beyond what is
  needed to keep the contract green.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/controls/registry.py` | MODIFY | Add docstring (extension pattern) |
| `packages/parrot-formdesigner/tests/integration/test_form_controls_contract.py` | CREATE | Contract test |
| `packages/parrot-formdesigner/tests/unit/controls/test_metadata_dump_keys.py` | CREATE | Key-stability test |
| `packages/parrot-formdesigner/tests/unit/controls/test_extension_registration.py` | CREATE | Extension test |
| `packages/parrot-formdesigner/tests/fixtures/form_controls_response_schema.json` | CREATE | Response JSON Schema |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# From TASK-1041
from parrot_formdesigner.controls import (
    register_field_control, get_controls, iter_controls,
    FieldControlMetadata,
)
# From TASK-1042
from parrot_formdesigner.api import setup_form_api
from parrot_formdesigner.services.registry import FormRegistry
from parrot_formdesigner.core.types import FieldType
```

### Required `FieldControlMetadata` keys

```python
# Authoritative list — must match the model defined in TASK-1041:
{
    "type", "label", "description", "category",
    "icon", "snippet", "render_hint",
    "supports_constraints", "is_container",
}
```

### Does NOT Exist

- ~~An `OpenAPI` decorator on the route~~ — there is no automatic
  OpenAPI generation in this package. The schema fixture is for
  consumers, not for runtime validation.
- ~~`register_field_control` with `id=` kwarg~~ — the parameter is
  the positional `field_type` (FieldType | str). No `id=`.
- ~~`get_controls()` returning a Pydantic root model~~ — it returns
  `list[FieldControlMetadata]`. The `{"controls": [...]}` envelope is
  applied by the HTTP handler, not the registry function.

---

## Implementation Notes

### Pattern to Follow

Use the codebase's existing aiohttp test fixtures (look at how
`test_setup_form_api.py` from TASK-1042 sets up the app). Re-use that
pattern; do not invent a new one.

### Key Constraints

- Tests MUST clear the `_REGISTRY` dict at the start of each
  extension test, then re-import `controls.builtin` to re-seed.
  Use the `_clear_registry` autouse fixture pattern from TASK-1041.
- The JSON Schema fixture should be a draft-2020-12 schema. Keep it
  human-readable and include `description` strings.

### Coordination with TASK-1041

This task edits `controls/registry.py` (which TASK-1041 created).
That's fine — the file is owned by TASK-1041 in Wave 1 and gets a
small docstring update in Wave 2c. If you find any other gap in
TASK-1041's implementation while running these contract tests
(e.g. `iter_controls` not preserving order), DO fix it here and note
the deviation in the Completion Note.

---

## Acceptance Criteria

- [ ] `GET /api/v1/form-controls` returns `{"controls": [<entry>, ...]}`
      with one entry per `FieldType` value (after `controls.builtin`
      is loaded).
- [ ] Every entry has exactly the 9 keys listed under
      `FieldControlMetadata`.
- [ ] `register_field_control("rich_text", ...)` adds a new entry
      retrievable via `GET /api/v1/form-controls`.
- [ ] `tests/fixtures/form_controls_response_schema.json` is a valid
      JSON Schema and matches an actual response from the endpoint
      (validate via `jsonschema.validate(response_body, schema)`).
- [ ] `controls/registry.py` has a top-of-file docstring documenting
      the extension pattern.
- [ ] All tests pass:
      `pytest packages/parrot-formdesigner/tests/unit/controls/ packages/parrot-formdesigner/tests/integration/test_form_controls_contract.py -v`.

---

## Test Specification

```python
# tests/unit/controls/test_metadata_dump_keys.py
from parrot_formdesigner.controls import FieldControlMetadata, register_field_control, get_controls
from parrot_formdesigner.controls.registry import _REGISTRY


def test_dump_has_exact_keys():
    _REGISTRY.clear()
    register_field_control(
        "x", label="X", description="d", category="basic",
        icon="x", snippet={}, render_hint="input", supports_constraints=True,
    )
    dump = get_controls()[0].model_dump()
    assert set(dump.keys()) == {
        "type", "label", "description", "category", "icon",
        "snippet", "render_hint", "supports_constraints", "is_container",
    }


# tests/integration/test_form_controls_contract.py
import json, pathlib
import pytest
import jsonschema
from aiohttp import web
from parrot_formdesigner.api import setup_form_api
from parrot_formdesigner.services.registry import FormRegistry
from parrot_formdesigner.core.types import FieldType


SCHEMA_PATH = pathlib.Path(
    "packages/parrot-formdesigner/tests/fixtures/form_controls_response_schema.json"
)


async def test_endpoint_matches_schema(aiohttp_client):
    app = web.Application()
    setup_form_api(app, FormRegistry())
    client = await aiohttp_client(app)
    resp = await client.get("/api/v1/form-controls")
    assert resp.status == 200
    body = await resp.json()
    schema = json.loads(SCHEMA_PATH.read_text())
    jsonschema.validate(body, schema)
    assert len(body["controls"]) == len(FieldType)
```

---

## Agent Instructions

1. Read TASK-1041 + TASK-1042 (already completed) so you understand
   what's wired.
2. Verify TASK-1044 is completed — Wave 1 must be done.
3. Run `pytest packages/parrot-formdesigner/tests/ -v` baseline.
4. Add the three test files + the fixture + the docstring update.
5. Move this task to `sdd/tasks/completed/`, update the index.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Completed by**: sdd-worker (Claude Sonnet)
**Date**: 2026-05-07
**Notes**:
- Created `tests/fixtures/form_controls_response_schema.json` — draft-2020-12 JSON Schema for the `{"controls": [...]}` payload, with `$ref` to a `FieldControlMetadata` def, full per-key descriptions, and `additionalProperties: false`.
- Created `tests/unit/controls/test_metadata_dump_keys.py` (3 tests): exact-key dump assertion, model_fields match, `extra='forbid'` enforcement.
- Created `tests/unit/controls/test_extension_registration.py` (2 tests): string-keyed type registration appears in `get_controls()` and in the HTTP response.
- Created `tests/integration/test_form_controls_contract.py` (5 tests): envelope shape, schema validation via `jsonschema.validate`, len(controls) == len(FieldType), full key coverage per entry, fixture-is-valid-schema meta-check.
- All 10 tests pass.
- Note: TASK-1041 already added the extension docstring to `controls/registry.py`; no further edits needed there.
- Installed `jsonschema` in dev environment (already declared in `pyproject.toml [project.optional-dependencies].test` from TASK-1040).
