---
type: Wiki Overview
title: 'TASK-1265: Core event models and FormEventAbort exception'
id: doc:sdd-tasks-completed-task-1265-core-events-models-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Foundation task. Defines the Pydantic models and typed exception that all
  later tasks (registry, dispatcher, schema extension, handlers, renderer) import.
  Without these, every other task is blocked.
relates_to:
- concept: mod:parrot.core.events.lifecycle
  rel: mentions
---

# TASK-1265: Core event models and FormEventAbort exception

**Feature**: FEAT-188 — Form Lifecycle Events for parrot-formdesigner
**Spec**: `sdd/specs/formdesigner-lifecycle-events.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Foundation task. Defines the Pydantic models and typed exception that all later tasks (registry, dispatcher, schema extension, handlers, renderer) import. Without these, every other task is blocked.

Implements §2 *Data Models* of the spec.

---

## Scope

- Create `packages/parrot-formdesigner/src/parrot_formdesigner/core/events.py` with:
  - `FormEventName` Literal type.
  - `FormEventBinding` Pydantic model (with `handler_ref` regex validation).
  - `FormEventsConfig` Pydantic model (mapping of event → binding).
  - `FormEventContext` Pydantic model (passed to handlers).
  - `EventResolution` Pydantic model (handler return type).
  - `FormEventAbort` Exception class with `reason`, `user_message`, `status_code`.
- Re-export the public surface from `packages/parrot-formdesigner/src/parrot_formdesigner/core/__init__.py`.
- Write unit tests in `packages/parrot-formdesigner/tests/unit/core/test_form_events_models.py`.

**NOT in scope**: any registry, dispatcher, schema modifications, handlers, or renderer changes. These live in later tasks.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/core/events.py` | CREATE | Module with all 5 Pydantic models + `FormEventAbort` |
| `packages/parrot-formdesigner/src/parrot_formdesigner/core/__init__.py` | MODIFY | Re-export new public symbols |
| `packages/parrot-formdesigner/tests/unit/core/test_form_events_models.py` | CREATE | Unit tests for all models + exception |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# Imports this task needs:
from collections.abc import Mapping
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field
```

### Existing Signatures to Use

```python
# Reference pattern from packages/parrot-formdesigner/src/parrot_formdesigner/api/operations.py:150
class OperationError(Exception):
    """Raised by per-op apply functions on validation failure."""
    # carries: op_index, op_name, message
```

### Does NOT Exist

- ~~`parrot_formdesigner.core.events`~~ — module does NOT exist; create it.
- ~~`FormEventName`, `FormEventBinding`, `FormEventsConfig`, `FormEventContext`, `EventResolution`, `FormEventAbort`~~ — none of these exist; create them.
- ~~`parrot.core.events.lifecycle.LifecycleEvent`~~ — FEAT-176 has no code merged. Do NOT import from there.

---

## Implementation Notes

### Pattern to Follow

Copy structure from spec §2 *Data Models* verbatim. All Pydantic models must use `ConfigDict(extra="forbid")` to catch JSON typos. The `FormEventAbort` mirrors the `OperationError` pattern at `api/operations.py:150`.

### Key Constraints

- `handler_ref` regex: `r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)+$"` (at least one dot — namespaced obligatorio per spec §7).
- `FormEventContext.auth_context: Any` — use `Any` to avoid importing `AuthContext` from `services/` (would create a circular import via `core/`).
- `EventResolution` fields all optional; an empty `EventResolution()` is a valid no-op return.
- `FormEventAbort.__init__` accepts `reason: str` positional and `user_message: str`, `status_code: int = 403` as kwargs.

### References in Codebase

- `packages/parrot-formdesigner/src/parrot_formdesigner/api/operations.py:150` — `OperationError` pattern.
- `packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py` — see existing Pydantic usage in `FormMetadataField` (l.185) for `ConfigDict(extra="forbid")` style.

---

## Acceptance Criteria

- [ ] `from parrot_formdesigner.core.events import FormEventName, FormEventBinding, FormEventsConfig, FormEventContext, EventResolution, FormEventAbort` works.
- [ ] `FormEventBinding(handler_ref="survey_v1.onBeforeSubmit")` validates OK.
- [ ] `FormEventBinding(handler_ref="no_dot")` raises `pydantic.ValidationError`.
- [ ] `FormEventAbort("blocked", user_message="Nope", status_code=403)` round-trips its three attributes.
- [ ] `FormEventAbort("blocked", user_message="Nope")` defaults `status_code` to 403.
- [ ] `EventResolution()` (no args) is a valid empty no-op.
- [ ] `EventResolution(payload={"x": 1}, extra_field=True)` raises `pydantic.ValidationError` (`extra="forbid"`).
- [ ] All unit tests pass: `pytest packages/parrot-formdesigner/tests/unit/core/test_form_events_models.py -v`.
- [ ] `ruff check packages/parrot-formdesigner/src/parrot_formdesigner/core/events.py` clean.
- [ ] `mypy --strict packages/parrot-formdesigner/src/parrot_formdesigner/core/events.py` clean.

---

## Test Specification

```python
# tests/unit/core/test_form_events_models.py
import pytest
from pydantic import ValidationError
from parrot_formdesigner.core.events import (
    FormEventBinding,
    FormEventsConfig,
    FormEventContext,
    EventResolution,
    FormEventAbort,
)


class TestFormEventBinding:
    def test_namespaced_handler_ref_valid(self):
        b = FormEventBinding(handler_ref="survey_v1.onBeforeSubmit")
        assert b.handler_ref == "survey_v1.onBeforeSubmit"
        assert b.remote is False
        assert b.required is False

    def test_handler_ref_without_dot_rejected(self):
        with pytest.raises(ValidationError, match="handler_ref"):
            FormEventBinding(handler_ref="no_dot")

    def test_extra_fields_forbidden(self):
        with pytest.raises(ValidationError):
            FormEventBinding(handler_ref="a.b", unknown=True)


class TestFormEventsConfig:
    def test_all_fields_optional(self):
        c = FormEventsConfig()
        assert c.onBeforeSubmit is None

    def test_accepts_bindings(self):
        c = FormEventsConfig(
            onBeforeSubmit=FormEventBinding(handler_ref="x.y"),
        )
        assert c.onBeforeSubmit.handler_ref == "x.y"


class TestFormEventAbort:
    def test_default_status_code(self):
        e = FormEventAbort("blocked", user_message="No")
        assert e.reason == "blocked"
        assert e.user_message == "No"
        assert e.status_code == 403

    def test_custom_status_code(self):
        e = FormEventAbort("nope", user_message="X", status_code=409)
        assert e.status_code == 409

    def test_is_exception(self):
        with pytest.raises(FormEventAbort):
            raise FormEventAbort("r", user_message="m")


class TestEventResolution:
    def test_empty_is_valid(self):
        r = EventResolution()
        assert r.payload is None

    def test_extra_forbidden(self):
        with pytest.raises(ValidationError):
            EventResolution(unknown_field=True)
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context (§2 Data Models).
2. **Check dependencies** — none.
3. **Verify the Codebase Contract** — confirm `api/operations.py:150` `OperationError` still exists.
4. **Update status** in `sdd/tasks/index/formdesigner-lifecycle-events.json` → `"in-progress"`.
5. **Implement** following the scope and codebase contract above.
6. **Verify** all acceptance criteria.
7. **Move this file** to `sdd/tasks/completed/TASK-1265-core-events-models.md`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet 4.6)
**Date**: 2026-05-20
**Notes**: All 5 Pydantic models + FormEventAbort created in core/events.py. Re-exported from core/__init__.py. 29 unit tests written and passing. Ruff clean.
**Deviations from spec**: none
