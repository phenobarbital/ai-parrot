---
type: Wiki Overview
title: 'TASK-1028: Add `created_at` field to FormSchema'
id: doc:sdd-tasks-completed-task-1028-formschema-created-at-field-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: The enriched `GET /api/v1/forms` response (FEAT-148, Module 4) needs a
relates_to:
- concept: mod:parrot
  rel: mentions
---

# TASK-1028: Add `created_at` field to FormSchema

**Feature**: FEAT-148 — Enriched List of Created Forms in parrot-formdesigner
**Spec**: `sdd/specs/formbuilder-list-created-forms.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

The enriched `GET /api/v1/forms` response (FEAT-148, Module 4) needs a
`created_at` value for every form. `PostgresFormStorage` already records
`created_at TIMESTAMPTZ` in the `form_schemas` table, but `FormSchema`
itself has no field to carry that timestamp end-to-end. This task adds
the optional field so the timestamp can flow from storage → registry →
HTTP response.

Implements Module 1 of the spec.

---

## Scope

- Add `from datetime import datetime` import to `core/schema.py`.
- Add `created_at: datetime | None = None` as the **last** attribute of
  `FormSchema` (after `meta`).
- Update the `FormSchema` class docstring `Attributes:` block to document
  the new field as: *"Optional creation timestamp (UTC). Populated by
  storage backends when forms are loaded from persistence; ``None`` for
  ad-hoc forms registered in memory."*

**NOT in scope**:
- Adding `updated_at`, `created_by`, or any other audit field.
- Auto-populating `created_at` in `FormRegistry.register()`.
- Modifying `PostgresFormStorage.load()` to fill `created_at` on the
  returned `FormSchema` (handled implicitly via Pydantic if the JSON
  carries the field; not a deliverable of this task).
- Touching `extra="forbid"` config — `FormSchema` does not set it, the
  field add is non-breaking.
- Writing handler code or integration tests — covered by TASK-1032 / TASK-1033.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot/formdesigner/core/schema.py` | MODIFY | Add `datetime` import + `created_at` field on `FormSchema` |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# Already present at top of file (do NOT duplicate):
from __future__ import annotations
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict
from .auth import AuthConfig
from .constraints import DependencyRule, FieldConstraints
from .options import FieldOption, OptionsSource
from .types import FieldType, LocalizedString
# verified: packages/parrot-formdesigner/src/parrot/formdesigner/core/schema.py:1-17

# NEW import to add (top of module, alongside `from typing ...`):
from datetime import datetime
```

### Existing Signatures to Use

```python
# packages/parrot-formdesigner/src/parrot/formdesigner/core/schema.py
class FormSchema(BaseModel):                              # line 107
    """Docstring with Attributes block at lines 113-123."""

    form_id: str                                          # line 125
    version: str = "1.0"                                  # line 126
    title: LocalizedString                                # line 127
    description: LocalizedString | None = None            # line 128
    sections: list[FormSection]                           # line 129
    submit: SubmitAction | None = None                    # line 130
    cancel_allowed: bool = True                           # line 131
    meta: dict[str, Any] | None = None                    # line 132
    # ← INSERT here: created_at: datetime | None = None
```

`FormSchema` does **not** declare `model_config = ConfigDict(extra="forbid")`,
so adding an optional field is backwards-compatible at parse time. (Verified
on schema.py lines 107-132.)

### Does NOT Exist

- ~~`FormSchema.model_config`~~ — not declared on `FormSchema`. Do not add it.
- ~~`FormSchema.updated_at`~~ — out of scope (spec §1 Non-Goals).
- ~~`FormSchema.created_by`~~ — out of scope.
- ~~`pydantic.AwareDatetime`~~ — not needed; plain `datetime | None` is
  sufficient and Pydantic v2 round-trips it as ISO-8601 by default.

---

## Implementation Notes

### Pattern to Follow

Mirror the way `description` and `meta` are declared (one-liner, no
custom serializer needed):

```python
class FormSchema(BaseModel):
    ...
    meta: dict[str, Any] | None = None
    created_at: datetime | None = None
```

### Key Constraints

- Field default MUST be `None`, not `datetime.utcnow` or similar.
- Order: place `created_at` AFTER `meta` (last position).
- Do NOT add a `model_validator` or custom `field_serializer` — Pydantic v2
  natively serializes `datetime` to ISO-8601 in `model_dump_json()`.
- Do NOT touch `FormField`, `FormSection`, `SubmitAction`, or `RenderedForm`.

### References in Codebase

- `packages/parrot-formdesigner/src/parrot/formdesigner/services/storage.py:65`
  — DB column `created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()` that this
  field will eventually receive values from.

---

## Acceptance Criteria

- [ ] `from datetime import datetime` is imported in `core/schema.py`.
- [ ] `FormSchema` has `created_at: datetime | None = None` as the last
      attribute, after `meta`.
- [ ] Class docstring `Attributes:` block lists `created_at` with a
      one-line description.
- [ ] `FormSchema(form_id="x", title="t", sections=[])` still parses
      (no required-field regression).
- [ ] `FormSchema(form_id="x", title="t", sections=[],
      created_at=datetime(2026,4,12,10,31, tzinfo=timezone.utc))`
      parses, and `model_dump_json()` emits `"created_at":"2026-04-12T10:31:00+00:00"`.
- [ ] No linting errors: `ruff check packages/parrot-formdesigner/src/parrot/formdesigner/core/schema.py`.
- [ ] Existing test suite still passes: `pytest packages/parrot-formdesigner/tests/unit/test_core_models.py -v` (no regressions).

---

## Test Specification

> A dedicated test for `created_at` is added in TASK-1033. This task
> only needs to ensure existing tests still pass.

```python
# Smoke check — run inside .venv:
python -c "
from datetime import datetime, timezone
from parrot.formdesigner.core.schema import FormSchema

# Without created_at — must still work
f = FormSchema(form_id='x', title='t', sections=[])
assert f.created_at is None

# With created_at
ts = datetime(2026, 4, 12, 10, 31, tzinfo=timezone.utc)
f2 = FormSchema(form_id='x', title='t', sections=[], created_at=ts)
assert f2.created_at == ts

# Round-trip through JSON
js = f2.model_dump_json()
assert '\"created_at\":\"2026-04-12T10:31:00+00:00\"' in js

print('OK')
"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** (`sdd/specs/formbuilder-list-created-forms.spec.md`)
   §2 (Architectural Design — Data Models) and §6 (Codebase Contract).
2. **Check dependencies** — none.
3. **Verify the Codebase Contract**:
   - `grep -n "class FormSchema" packages/parrot-formdesigner/src/parrot/formdesigner/core/schema.py`
     → confirm line 107 still matches.
   - Confirm `FormSchema` does NOT have `model_config` set with
     `extra="forbid"`. If that has changed, update the contract first.
4. **Implement** the field add.
5. **Run** the smoke check above and the existing
   `tests/unit/test_core_models.py` suite.
6. **Move this file** to `sdd/tasks/completed/`.
7. **Update** `sdd/tasks/index/formbuilder-list-created-forms.json` →
   `"done"`.
8. **Fill in the Completion Note** below.

---

## Completion Note

**Completed by**: sdd-worker (claude-sonnet-4-6)
**Date**: 2026-05-05
**Notes**: Added `from datetime import datetime` import and `created_at: datetime | None = None` field as the last attribute of `FormSchema`. Updated class docstring Attributes block. All 8 existing core model tests pass; ruff check clean.

**Deviations from spec**: none
