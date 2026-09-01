# TASK-2683: Field Helpers — Update TEXT_AREA Snippet with content_type Example

**Feature**: FEAT-488 — FormField Content-Type
**Spec**: `sdd/specs/formfield-content-type.spec.md`
**Status**: pending
**Priority**: low
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-2677
**Assigned-to**: unassigned

---

## Context

`tools/field_helpers.py` contains `_FIELD_SCHEMA_SNIPPETS` — minimal JSON
reference payloads for each `FieldType`, used by agents and UIs as quick
examples. The `TEXT_AREA` snippet currently lacks a `content_type` example.
This task adds one so users know the new field is available.

Implements spec §3 Module 7.

---

## Scope

- In `tools/field_helpers.py`, update the `_FIELD_SCHEMA_SNIPPETS[FieldType.TEXT_AREA.value]`
  dict (lines 22-26) to add `"content_type": "text/markdown"` as an example key.

**NOT in scope**: changes to any other snippet, new tool functions, or test additions.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/tools/field_helpers.py` | MODIFY | Add `"content_type": "text/markdown"` to the `TEXT_AREA` snippet |

---

## Codebase Contract (Anti-Hallucination)

### Existing Signatures to Use

```python
# packages/parrot-formdesigner/src/parrot_formdesigner/tools/field_helpers.py

_FIELD_SCHEMA_SNIPPETS: dict[str, dict[str, Any]] = {  # line 15
    FieldType.TEXT_AREA.value: {                         # line 22
        "field_id": "comments",
        "field_type": "text_area",
        "label": "Comments",
        # ← add: "content_type": "text/markdown"
    },
    # ... other field types follow
}
```

### Does NOT Exist

- ~~`"accept_content_types"` in the TEXT_AREA snippet~~ — only `content_type` is
  added in this task; `accept_content_types` is a more complex case and does not
  belong in the basic snippet.

---

## Implementation Notes

### Key Constraints

- Add exactly one key: `"content_type": "text/markdown"`.
- Do NOT add `"accept_content_types"` to the snippet (the basic snippet should
  demonstrate the simplest use case).
- Verify the actual line numbers by reading the file before editing — the line
  numbers in this contract are approximate.

---

## Acceptance Criteria

- [ ] `_FIELD_SCHEMA_SNIPPETS["text_area"]` contains `"content_type": "text/markdown"`.
- [ ] No other snippets are modified.
- [ ] All existing field helper tests pass: `pytest packages/parrot-formdesigner/tests/unit/test_field_helpers.py -v`
- [ ] No linting errors: `ruff check packages/parrot-formdesigner/src/parrot_formdesigner/tools/field_helpers.py`

---

## Test Specification

```python
# packages/parrot-formdesigner/tests/unit/test_field_helpers.py
# Add to the existing test file:

from parrot_formdesigner.tools.field_helpers import _FIELD_SCHEMA_SNIPPETS


def test_text_area_snippet_has_content_type():
    """TEXT_AREA snippet documents the content_type field."""
    snippet = _FIELD_SCHEMA_SNIPPETS.get("text_area", {})
    assert "content_type" in snippet
    assert snippet["content_type"] == "text/markdown"
```

---

## Agent Instructions

1. **Read the spec** at `sdd/specs/formfield-content-type.spec.md`.
2. **Check dependencies** — verify TASK-2677 is in `sdd/tasks/completed/`.
3. **Read `tools/field_helpers.py`** lines 15-30 to verify the current TEXT_AREA snippet.
4. **Update status** → `"in_progress"`.
5. **Implement** the single key addition.
6. **Verify** all acceptance criteria.
7. **Move** to `sdd/tasks/completed/TASK-2683-field-helpers-text-area-snippet.md`.
8. **Update index** → `"completed"`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: —
**Date**: —
**Notes**: —
**Deviations from spec**: none
