---
type: Wiki Overview
title: 'TASK-1268: Add `FormSchema.events` field'
id: doc:sdd-tasks-completed-task-1268-formschema-events-field-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'Implements §3 Module 4. Adds the `events: FormEventsConfig | None = None`
  field to `FormSchema` so forms can declaratively bind lifecycle events to logical
  handler refs.'
---

# TASK-1268: Add `FormSchema.events` field

**Feature**: FEAT-188 — Form Lifecycle Events for parrot-formdesigner
**Spec**: `sdd/specs/formdesigner-lifecycle-events.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1265
**Assigned-to**: unassigned

---

## Context

Implements §3 Module 4. Adds the `events: FormEventsConfig | None = None` field to `FormSchema` so forms can declaratively bind lifecycle events to logical handler refs.

This is a small Pydantic extension but it is the contract that everything else reads — must be implemented carefully to remain backward-compatible.

---

## Scope

- Add `events: FormEventsConfig | None = None` to `FormSchema` (core/schema.py:241).
- Update `FormSchema`'s docstring to document the new field.
- Ensure `model_dump(exclude_none=True)` does not produce `"events": null` for forms without events declared (no-breaking acid test in spec §5).
- Add unit tests in `tests/unit/test_core_models.py` (existing file) OR create `tests/unit/test_form_schema_events.py` if the existing file is crowded.

**NOT in scope**: dispatcher, handlers integration, renderer.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py` | MODIFY | Add `events` field to `FormSchema` (l.241) + update docstring |
| `packages/parrot-formdesigner/tests/unit/test_form_schema_events.py` | CREATE | Tests for new field |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# Add to core/schema.py:
from parrot_formdesigner.core.events import FormEventsConfig  # from TASK-1265
```

### Existing Signatures to Use

```python
# packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py:241
class FormSchema(BaseModel):
    form_id: str                                      # line 266
    version: str = "1.0"                              # line 267
    title: LocalizedString                            # line 268
    description: LocalizedString | None = None        # line 269
    sections: list[FormSection]                       # line 270
    submit: SubmitAction | None = None                # line 271
    cancel_allowed: bool = True                       # line 272
    meta: dict[str, Any] | None = None                # line 273
    created_at: datetime | None = None                # line 274
    tenant: str | None = None                         # line 275
    metadata: list[FormMetadataField] | None = None   # line 276
    # NEW: events: FormEventsConfig | None = None     ← add here
```

### Does NOT Exist

- ~~`FormSchema.events`~~ — does not exist yet; THIS task adds it.
- ~~Any validator hook that resolves `handler_ref` at model construction time~~ — do NOT implement. Resolution happens at dispatch time (deferred to TASK-1267's runtime), keeping `FormSchema` decoupled from the registry.

---

## Implementation Notes

### Pattern to Follow

Add the new field at the end of the existing field list (after `metadata`). Update the class docstring to mention `events` with one line describing it. No new validators are needed — `FormEventsConfig` and `FormEventBinding` already enforce their constraints from TASK-1265.

### Key Constraints

- Field is optional with default `None`. NO change to existing field defaults or order.
- The import of `FormEventsConfig` must be at module top, NOT inside a function. `core/events.py` does not import from `core/schema.py`, so no circular import.
- `FormSchema.model_dump()` with default `exclude_none` behavior must omit `events` for forms that don't declare them. This is the no-breaking acid test (spec §5 acceptance criterion).

### References in Codebase

- `packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py:241` — target class.
- `tests/unit/test_core_models.py` — existing test patterns for `FormSchema`.

---

## Acceptance Criteria

- [ ] `FormSchema(form_id="f", title={"en":"t"}, sections=[], events=FormEventsConfig(...))` constructs OK.
- [ ] `FormSchema(form_id="f", title={"en":"t"}, sections=[])` (without `events`) constructs OK; `form.events is None`.
- [ ] `form.model_dump(exclude_none=True)` for a form without `events` does NOT contain the key `"events"`.
- [ ] `form.model_dump()` for a form WITH events includes the nested `FormEventsConfig` structure correctly.
- [ ] All existing `tests/unit/test_core_models.py` tests still pass unchanged.
- [ ] New tests in `tests/unit/test_form_schema_events.py` pass.
- [ ] `ruff` + `mypy --strict` clean on `core/schema.py`.

---

## Test Specification

```python
# tests/unit/test_form_schema_events.py
import pytest
from parrot_formdesigner.core.schema import FormSchema
from parrot_formdesigner.core.events import FormEventsConfig, FormEventBinding


class TestFormSchemaEvents:
    def test_default_is_none(self):
        f = FormSchema(form_id="f1", title={"en": "t"}, sections=[])
        assert f.events is None

    def test_accepts_events_config(self):
        f = FormSchema(
            form_id="f1", title={"en": "t"}, sections=[],
            events=FormEventsConfig(
                onBeforeSubmit=FormEventBinding(handler_ref="f1.onBeforeSubmit"),
            ),
        )
        assert f.events is not None
        assert f.events.onBeforeSubmit.handler_ref == "f1.onBeforeSubmit"

    def test_dump_without_events_omits_field_when_exclude_none(self):
        f = FormSchema(form_id="f1", title={"en": "t"}, sections=[])
        dumped = f.model_dump(exclude_none=True)
        assert "events" not in dumped

    def test_dump_with_events_includes_field(self):
        f = FormSchema(
            form_id="f1", title={"en": "t"}, sections=[],
            events=FormEventsConfig(
                onError=FormEventBinding(handler_ref="f1.onError"),
            ),
        )
        dumped = f.model_dump(exclude_none=True)
        assert dumped["events"]["onError"]["handler_ref"] == "f1.onError"
```

---

## Agent Instructions

1. **Read the spec** §3 Module 4.
2. **Check dependencies** — TASK-1265.
3. **Verify the Codebase Contract** — confirm the line numbers of `FormSchema` fields.
4. **Implement** — single-field addition.
5. **Verify** acceptance criteria, especially the no-breaking dump test.
6. **Move** this file to `sdd/tasks/completed/`.

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet 4.6)
**Date**: 2026-05-20
**Notes**: events field added to FormSchema in core/schema.py. Import of FormEventsConfig added. Docstring updated. 8 unit tests passing including no-breaking acid test. Ruff clean.
**Deviations from spec**: none
