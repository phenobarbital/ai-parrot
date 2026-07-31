---
type: Wiki Overview
title: 'TASK-1147: FieldType Enum — 10 New Values'
id: doc:sdd-tasks-completed-task-1147-fieldtype-enum-additions-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Phase 2, Module 9. Appends 10 new enum values to `FieldType` in `core/types.py`.
---

# TASK-1147: FieldType Enum — 10 New Values

**Feature**: FEAT-167 — FormDesigner New Field Types
**Spec**: `sdd/specs/formdesigner-new-fields.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1146
**Assigned-to**: unassigned

---

## Context

Phase 2, Module 9. Appends 10 new enum values to `FieldType` in `core/types.py`.
This is purely additive — no existing values change. All Phase 2 tasks depend on
this task because they reference the new enum values.

---

## Scope

- Append 10 new values to `FieldType` enum:
  `SIGNATURE`, `DYNAMIC_SELECT`, `TRANSFER_LIST`, `REMOTE_RESPONSE`,
  `AVAILABILITY`, `LOCATION`, `TAGS`, `NPS`, `LIKERT`, `RANKING`
- Do NOT add `IMAGE_DROPZONE` or `COLOR_PICKER` enum values (use `meta.render_as`)
- Do NOT modify or remove any existing 20 values

**NOT in scope**: Any model changes, renderer changes, validator changes.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/core/types.py` | MODIFY | Append 10 new enum values |
| `packages/parrot-formdesigner/tests/unit/test_core_models.py` | MODIFY | Add `test_field_type_enum_has_new_values` |

---

## Codebase Contract (Anti-Hallucination)

### Existing Signatures to Use
```python
# core/types.py:16 — current FieldType (verified):
class FieldType(str, Enum):
    """Supported form field types."""
    TEXT = "text"            # line 19
    TEXT_AREA = "text_area"  # line 20
    NUMBER = "number"        # line 21
    INTEGER = "integer"      # line 22
    BOOLEAN = "boolean"      # line 23
    DATE = "date"            # line 24
    DATETIME = "datetime"    # line 25
    TIME = "time"            # line 26
    SELECT = "select"        # line 27
    MULTI_SELECT = "multi_select"  # line 28
    FILE = "file"            # line 29
    IMAGE = "image"          # line 30
    COLOR = "color"          # line 31
    URL = "url"              # line 32
    EMAIL = "email"          # line 33
    PHONE = "phone"          # line 34
    PASSWORD = "password"    # line 35
    HIDDEN = "hidden"        # line 36
    GROUP = "group"          # line 37
    ARRAY = "array"          # line 38
```

### Does NOT Exist
- ~~`FieldType.SIGNATURE`~~ — THIS task adds it
- ~~`FieldType.DYNAMIC_SELECT`~~ — THIS task adds it
- ~~`FieldType.TRANSFER_LIST`~~ — THIS task adds it
- ~~`FieldType.REMOTE_RESPONSE`~~ — THIS task adds it
- ~~`FieldType.AVAILABILITY`~~ — THIS task adds it
- ~~`FieldType.LOCATION`~~ — THIS task adds it
- ~~`FieldType.TAGS`~~ — THIS task adds it
- ~~`FieldType.NPS`~~ — THIS task adds it
- ~~`FieldType.LIKERT`~~ — THIS task adds it
- ~~`FieldType.RANKING`~~ — THIS task adds it
- ~~`FieldType.IMAGE_DROPZONE`~~ — MUST NOT be added (use `meta.render_as="dropzone"`)
- ~~`FieldType.COLOR_PICKER`~~ — MUST NOT be added (use `meta.render_as="picker"`)

---

## Implementation Notes

Append after `ARRAY = "array"`:

```python
    # Phase 2 — new field types (FEAT-167)
    SIGNATURE = "signature"
    DYNAMIC_SELECT = "dynamic_select"
    TRANSFER_LIST = "transfer_list"
    REMOTE_RESPONSE = "remote_response"
    AVAILABILITY = "availability"
    LOCATION = "location"
    TAGS = "tags"
    NPS = "nps"
    LIKERT = "likert"
    RANKING = "ranking"
```

String values must exactly match the spec (lowercase, underscores). These are
used as JSON keys in serialized forms stored in PostgreSQL.

---

## Acceptance Criteria

- [ ] All 10 new values present in `FieldType`
- [ ] All 20 existing values unchanged
- [ ] `FieldType("signature") == FieldType.SIGNATURE` (string alias works)
- [ ] `len(FieldType) == 30`
- [ ] `test_field_type_enum_has_new_values` passes
- [ ] All existing tests that use `FieldType` pass unchanged
- [ ] `ruff check packages/parrot-formdesigner/` passes

---

## Test Specification

```python
# packages/parrot-formdesigner/tests/unit/test_core_models.py
from parrot_formdesigner.core.types import FieldType


def test_field_type_enum_has_new_values():
    """All 10 new FieldType values are present with stable string aliases."""
    new_types = {
        FieldType.SIGNATURE: "signature",
        FieldType.DYNAMIC_SELECT: "dynamic_select",
        FieldType.TRANSFER_LIST: "transfer_list",
        FieldType.REMOTE_RESPONSE: "remote_response",
        FieldType.AVAILABILITY: "availability",
        FieldType.LOCATION: "location",
        FieldType.TAGS: "tags",
        FieldType.NPS: "nps",
        FieldType.LIKERT: "likert",
        FieldType.RANKING: "ranking",
    }
    for ft, expected_value in new_types.items():
        assert ft.value == expected_value, f"{ft} has wrong value"
        assert FieldType(expected_value) == ft, f"String alias broken for {expected_value}"


def test_field_type_enum_total_count():
    """FieldType now has exactly 30 values (20 existing + 10 new)."""
    assert len(FieldType) == 30


def test_field_type_existing_values_unchanged():
    """All original 20 FieldType values are unchanged."""
    assert FieldType.TEXT.value == "text"
    assert FieldType.ARRAY.value == "array"
    assert FieldType.GROUP.value == "group"
```

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
