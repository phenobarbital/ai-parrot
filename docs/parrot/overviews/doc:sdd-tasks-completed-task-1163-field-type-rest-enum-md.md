---
type: Wiki Overview
title: 'TASK-1163: Add `FieldType.REST` enum value'
id: doc:sdd-tasks-completed-task-1163-field-type-rest-enum-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Append the new field type to `core/types.py::FieldType`. Trivial but
---

# TASK-1163: Add `FieldType.REST` enum value

**Feature**: FEAT-170 — FormDesigner `FieldType.REST`
**Spec**: `sdd/specs/new-formdesigner-field-rest.spec.md` (Module 4)
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Append the new field type to `core/types.py::FieldType`. Trivial but
unblocks every Phase 2 module.

---

## Scope

- Append `REST = "rest"` to `FieldType` after `RANKING = "ranking"`.
- Add a single-line marker comment `# Phase 3 — FEAT-170` (or extend
  the existing `# Phase 2 — new field types (FEAT-167)` block — match
  the style at `core/types.py:39`).
- One unit test asserting `FieldType.REST.value == "rest"` and that
  the enum still round-trips via Pydantic (re-run the existing
  `FieldType`-coverage test if present; otherwise add a minimal one).

**NOT in scope**: registering metadata (TASK-1164), validator branch
(TASK-1166), renderer entries (TASK-1167).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/core/types.py` | MODIFY | +1 enum value |
| `packages/parrot-formdesigner/tests/unit/test_core_types.py` | MODIFY or CREATE | Assert `FieldType.REST` present |

---

## Codebase Contract (Anti-Hallucination)

### Verified Signature (target file)

```python
# packages/parrot-formdesigner/src/parrot_formdesigner/core/types.py:16-49
class FieldType(str, Enum):
    TEXT = "text"
    # ... through line 49 ...
    RANKING = "ranking"   # line 49
# Append REST = "rest" after RANKING.
```

### Does NOT Exist

- ~~`FieldType.REST`~~ — added by this task.

---

## Implementation Notes

Exactly one line + matching comment. No other changes anywhere.

---

## Acceptance Criteria

- [ ] `from parrot_formdesigner.core.types import FieldType; FieldType.REST.value == "rest"`.
- [ ] Pre-existing enum-iteration tests still pass.
- [ ] `ruff check packages/parrot-formdesigner/src/parrot_formdesigner/core/types.py` clean.

---

## Test Specification

```python
from parrot_formdesigner.core.types import FieldType

def test_field_type_rest_present():
    assert FieldType.REST.value == "rest"
    assert FieldType("rest") is FieldType.REST
```

---

## Completion Note

*(Agent fills this in when done)*
