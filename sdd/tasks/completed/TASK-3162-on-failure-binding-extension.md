# TASK-3162: `on_failure` field on `FormEventBinding` — `core/events.py`

**Feature**: FEAT-459 — Form Builder: Sandboxed Custom Code on Lifecycle Events
**Spec**: `sdd/specs/formbuilder-custom-code.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2, resolving OQ-3. `required=True` on `FormEventBinding`
already means "handler is not registered → `RuntimeError`" (FEAT-188,
unchanged). This feature adds a **second**, independent failure axis:
"the handler ran and failed" (raised, timed out, exceeded its sandbox
budget, or returned an invalid `EventResolution`). Widening `required` to
cover both was explicitly rejected in the spec — it would silently change
behavior for every existing binding that already sets `required=True`
(violating G10, zero breaking changes).

This task only adds the field. TASK-3172 (M12, Tier Router) is what
actually reads and applies it.

---

## Scope

- Add `on_failure: Literal["abort", "continue"] = "continue"` to
  `FormEventBinding` in `core/events.py`, with a docstring `Attributes`
  entry explaining how it differs from `required`.
- Add a test asserting the new field defaults correctly and that
  `required`'s existing semantics are untouched.

**NOT in scope**: reading or acting on `on_failure` anywhere (that is
TASK-3172); any change to `FormEventsConfig`, `FormEventContext`, or any
other model in this file.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/core/events.py` | MODIFY | Add `on_failure` field to `FormEventBinding` |
| `packages/parrot-formdesigner/tests/unit/test_form_event_binding_on_failure.py` | CREATE | Unit tests for the new field |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from typing import Literal
from parrot_formdesigner.core.events import FormEventBinding  # verified: core/events.py:54
```

### Existing Signatures to Use
```python
# packages/parrot-formdesigner/src/parrot_formdesigner/core/events.py
class FormEventBinding(BaseModel):                           # line 54
    """Declaración por-formulario de un binding evento → handler.

    Attributes:
        handler_ref: Logical handler name, namespaced as
            '<form_id>.<event>'. ...
        remote: When True, the HTML5 client bridges the event to the
            server via a fetch call to the remote endpoint.
        required: When True and the handler is not registered, the
            dispatcher raises RuntimeError instead of silently no-op-ing.
    """
    model_config = ConfigDict(extra="forbid")

    handler_ref: str = Field(                                # line 69
        ...,
        description="Logical handler name, namespaced as '<form_id>.<event>'.",
        pattern=r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)+$",
    )
    remote: bool = False    # line 74
    required: bool = False  # line 75 — MISSING handler → RuntimeError. Unrelated
                             #   to on_failure, which governs a handler that
                             #   ran and failed.
```
`FormEventBinding` is re-exported from `core/__init__.py:20` and listed in
`__all__` at `core/__init__.py:106` — no change needed there, re-export is
by name and the class object itself is unchanged, only gains a field.

### Does NOT Exist
- ~~`FormEventBinding.on_failure`~~ — does not exist yet; this task adds it.
  Do not assume it is present when reading other modules' current source.
- ~~`FormEventBinding.failure_policy`~~ / ~~`.on_error`~~ — the field name is
  `on_failure`, matching the spec's exact naming (distinct from the
  existing `onError` *event name*, which is unrelated).
- ~~A change to `required`'s meaning~~ — `required` continues to mean
  *handler missing*, unconditionally. Do not touch its docstring's
  semantics, only clarify the distinction from the new field.

---

## Implementation Notes

### Key Constraints
- The new field MUST have a default (`"continue"`) — every existing
  `FormEventBinding(...)` construction (including ones with no
  `on_failure` kwarg) must keep working unchanged (G10).
- `Literal["abort", "continue"]`, not a `StrEnum` — match the existing
  `FormEventName`/`VisitEventName` style in this same file (both are
  `Literal[...]`, not enums).
- Do not add `on_failure` to any other model in this file.

### References in Codebase
- `core/events.py:54-76` — the exact block being modified, shown in full above.

---

## Implementation Blueprint

### Steps (in order)
1. Add `on_failure` as the last field of `FormEventBinding`, after
   `required` — *why*: keeps the new field visually adjacent to the field
   it is most often confused with, reinforcing the docstring distinction.
2. Extend the class docstring's `Attributes` section — *why*: this is the
   field an implementer is most likely to conflate with `required`; the
   docstring is the first thing they will read.
3. Write and run the test.

### `packages/parrot-formdesigner/src/parrot_formdesigner/core/events.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    required: bool = False  # if True and handler missing' packages/parrot-formdesigner/src/parrot_formdesigner/core/events.py)
# AFTER — insert below `    required: bool = False  # if True and handler missing → 500` (verified: core/events.py:75)
    on_failure: Literal["abort", "continue"] = "continue"
    # NEW (FEAT-459) — governs a handler that RAN and FAILED (raised, timed
    # out, exceeded its sandbox budget, or returned an invalid
    # EventResolution). Distinct from `required`, which governs a handler
    # that is MISSING from the registry. Widening `required` to cover both
    # was rejected: it would silently change runtime behavior for every
    # existing binding already setting required=True (G10).
```
**Why this shape**: a bare additive field with a default is the only change
that cannot break an existing caller. The inline comment (not just the
docstring) is deliberate — this field sits one line below `required` and a
future reader skimming the class body should see the distinction without
having to scroll to the docstring.

Also update the class docstring's `Attributes:` block — add, after the
existing `required:` line:
```python
# occurrences: 1 (verified: grep -c '            server via a fetch call to the remote endpoint.' packages/parrot-formdesigner/src/parrot_formdesigner/core/events.py)
# AFTER — insert below the `required:` docstring line (verified: core/events.py, class FormEventBinding docstring)
        on_failure: When the handler runs and fails (raises, times out, or
            returns an invalid resolution), "abort" rejects the submission
            via FormEventAbort semantics; "continue" (default) logs the
            failure and proceeds as if the handler returned EventResolution().
            Distinct from `required`, which governs a MISSING handler.
```
**Why**: keeps the docstring the single source of truth for the
`required` vs `on_failure` distinction that TASK-3172's router must
implement correctly.

### `packages/parrot-formdesigner/tests/unit/test_form_event_binding_on_failure.py` (CREATE)
```python
"""Unit tests for FormEventBinding.on_failure — FEAT-459 / TASK-3162."""

from __future__ import annotations

from parrot_formdesigner.core.events import FormEventBinding


def test_on_failure_defaults_to_continue() -> None:
    binding = FormEventBinding(handler_ref="survey_v1.onBeforeSubmit")
    assert binding.on_failure == "continue"


def test_on_failure_accepts_abort() -> None:
    binding = FormEventBinding(
        handler_ref="survey_v1.onBeforeSubmit", on_failure="abort"
    )
    assert binding.on_failure == "abort"


def test_required_semantics_unchanged() -> None:
    """required still means MISSING handler, independent of on_failure."""
    binding = FormEventBinding(
        handler_ref="survey_v1.onBeforeSubmit", required=True, on_failure="continue"
    )
    assert binding.required is True
    assert binding.on_failure == "continue"


def test_existing_bindings_deserialize() -> None:
    """A binding serialised before this feature (no on_failure key) still parses."""
    # FILL IN: FormEventBinding.model_validate({"handler_ref": "x.onBeforeSubmit"})
    #   assert on_failure == "continue" — bounded by G10 (zero breaking changes)
    pass
```
**Why**: the three positive-path tests are complete; the deserialize test
is the one that most directly proves G10 and is a one-line stub.

### FILL IN checklist
- [ ] `test_existing_bindings_deserialize` — `model_validate` on a dict with no `on_failure` key

---

## Acceptance Criteria

- [ ] `FormEventBinding(handler_ref="x.y").on_failure == "continue"`
- [ ] `FormEventBinding(handler_ref="x.y", on_failure="abort").on_failure == "abort"`
- [ ] `FormEventBinding.model_validate({"handler_ref": "x.y"})` succeeds with `on_failure == "continue"` (no `on_failure` key present)
- [ ] `required=True` still raises `RuntimeError` semantics are documented as unrelated to `on_failure` (docstring check, not runtime — the dispatcher itself is untouched by this task)
- [ ] All tests pass: `pytest packages/parrot-formdesigner/tests/unit/test_form_event_binding_on_failure.py -v`
- [ ] Existing suite still green: `pytest packages/parrot-formdesigner/tests/ -k events -v`
- [ ] `ruff check` and `mypy` clean on `core/events.py`

---

## Test Specification

See the blueprint's test file above — 4 test functions, 1 stubbed.

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above (§2 "Design note on on_failure", §3 Module 2)
2. **Check dependencies** — none
3. **Verify the Codebase Contract** — confirm `FormEventBinding` still ends at `required: bool = False` (line 75) before appending
4. **Update status** in `sdd/tasks/index/formbuilder-custom-code.json` → `"in-progress"`
5. **Implement** from the blueprint; complete the one `# FILL IN:`
6. **Verify** all acceptance criteria
7. **Move this file** to `sdd/tasks/completed/TASK-3162-on-failure-binding-extension.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (orchestrated via parrot-sdd-coder)
**Date**: 2026-09-11
**Notes**: Added `on_failure: Literal["abort", "continue"] = "continue"` to
`FormEventBinding` in `core/events.py`, governing handler-run failures
(raised / timed out / sandbox-budget-exceeded / invalid `EventResolution`),
distinct from `required` (which governs missing handlers). Default
`"continue"` preserves G10 backward compatibility. 4/4 new tests pass
(`test_form_event_binding_on_failure.py`); existing `events` suite still
green (103 passed). `ruff check` and `mypy` clean.

**Deviations from spec**: none

**Seat: minimax · Backend: nova · Model: minimax.minimax-m2.5 · Attempts: 1 · Duration: 268.5s · Tokens: 292,074 in / 3,002 out**
