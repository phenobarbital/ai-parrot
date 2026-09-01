# TASK-2677: FormField Schema Extension — Add content_type and accept_content_types

**Feature**: FEAT-488 — FormField Content-Type
**Spec**: `sdd/specs/formfield-content-type.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

This is the foundational task of FEAT-488. All other tasks depend on the
`FormField` schema having the two new optional fields. Once these fields are
added and committed in the worktree, the renderer and validator tasks can
proceed.

Implements spec §3 Module 1.

---

## Scope

- Add `content_type: str | None = None` to `FormField` **after** the `meta` field (line 123 of `core/schema.py`).
- Add `accept_content_types: list[str] | None = None` to `FormField` immediately after `content_type`.
- Update the `FormField` class docstring to document both new attributes.
- Verify that `FormField.model_rebuild()` at line 172 still runs cleanly after the additions.

**NOT in scope**: `VoiceAnswerEnvelope`, validator changes, renderer changes, or `field_helpers.py`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py` | MODIFY | Add two new optional fields to `FormField` after `meta` (line 123) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# core/schema.py — no new imports required; all needed types already present
from pydantic import BaseModel, ConfigDict, Field, model_validator  # line 17
from typing import Any  # line 15 (for existing meta: dict[str, Any] | None)
```

### Existing Signatures to Use

```python
# packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py

class FormField(BaseModel):
    model_config = ConfigDict(extra="forbid")           # line 104
    field_uid: uuid.UUID = Field(default_factory=uuid.uuid4)  # line 106
    field_id: str                                        # line 107
    field_type: FieldType                                # line 108
    label: LocalizedString                               # line 109
    description: LocalizedString | None = None           # line 110
    placeholder: LocalizedString | None = None           # line 111
    required: bool = False                               # line 112
    default: Any = None                                  # line 113
    read_only: bool = False                              # line 114
    constraints: FieldConstraints | None = None          # line 115
    options: list[FieldOption] | None = None             # line 116
    options_source: OptionsSource | None = None          # line 117
    depends_on: DependencyRule | None = None             # line 118
    post_depends: list[PostDependency] | None = None     # line 119
    children: list[FormField] | None = None              # line 120
    item_template: FormField | None = None               # line 121
    relation: RelationSpec | None = None                 # line 122
    meta: dict[str, Any] | None = None                  # line 123
    # ← insert the two new fields HERE

# Line 172 (must not break):
FormField.model_rebuild()
```

### Does NOT Exist

- ~~`FormField.content_type`~~ — does not exist yet; this task creates it.
- ~~`FormField.accept_content_types`~~ — does not exist yet; this task creates it.
- ~~`FormField.content_type_validator`~~ — no validator is added in this task; advisory-only.

---

## Implementation Notes

### Pattern to Follow

Both new fields follow the same optional-with-None-default pattern used by
the existing fields (`meta`, `depends_on`, etc.):
```python
content_type: str | None = None
accept_content_types: list[str] | None = None
```

No `Field(...)` wrapper is needed (no `description` or validation constraint);
plain type annotation with `= None` default is sufficient and matches the
existing field style.

### Key Constraints

- Insert **after** `meta` at line 123 to preserve existing field ordering.
- Both fields must be explicit Pydantic field declarations (not just class
  attributes) — required because `model_config = ConfigDict(extra="forbid")`.
- `FormField.model_rebuild()` at line 172 must continue to run without error.
- Do NOT add any MIME-type validation logic — enforcement is advisory-only in v1.
- Run `pytest packages/parrot-formdesigner/tests/unit/test_core_models.py -v`
  immediately after the change to catch any `model_rebuild()` or
  `extra="forbid"` breakage.

### References in Codebase

- `packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py` — target file
- `packages/parrot-formdesigner/src/parrot_formdesigner/core/file_envelope.py` — style reference for optional fields

---

## Acceptance Criteria

- [ ] `FormField` has `content_type: str | None = None` field (after `meta`).
- [ ] `FormField` has `accept_content_types: list[str] | None = None` field (after `content_type`).
- [ ] `FormField` docstring documents both new attributes.
- [ ] `FormField.model_rebuild()` runs without error.
- [ ] `FormField(**existing_payload)` (no new keys) deserializes without error (backward compat).
- [ ] `FormField(..., content_type="text/markdown")` round-trips correctly.
- [ ] `FormField(..., accept_content_types=["text/plain", "application/json"])` round-trips correctly.
- [ ] All tests pass: `pytest packages/parrot-formdesigner/tests/unit/test_core_models.py -v`
- [ ] No linting errors: `ruff check packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py`

---

## Test Specification

```python
# packages/parrot-formdesigner/tests/unit/test_core_models.py
# Add to the existing test file (do not overwrite):

def test_formfield_content_type_defaults_to_none():
    """Existing FormField construction is unaffected by new fields."""
    field = FormField(field_id="q1", field_type=FieldType.TEXT_AREA, label="Q1")
    assert field.content_type is None
    assert field.accept_content_types is None


def test_formfield_content_type_set():
    """content_type round-trips correctly."""
    field = FormField(
        field_id="notes",
        field_type=FieldType.TEXT_AREA,
        label="Notes",
        content_type="text/markdown",
    )
    assert field.content_type == "text/markdown"
    data = field.model_dump()
    assert data["content_type"] == "text/markdown"


def test_formfield_accept_content_types_set():
    """accept_content_types round-trips correctly."""
    field = FormField(
        field_id="answer",
        field_type=FieldType.TEXT_AREA,
        label="Answer",
        accept_content_types=["text/plain", "application/json"],
    )
    assert field.accept_content_types == ["text/plain", "application/json"]


def test_formfield_extra_field_still_forbidden():
    """extra='forbid' is still enforced after adding the new fields."""
    with pytest.raises(Exception):
        FormField(
            field_id="q1",
            field_type=FieldType.TEXT,
            label="Q",
            nonexistent_field="boom",
        )
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/formfield-content-type.spec.md` for full context.
2. **Check dependencies** — none; this is the first task.
3. **Verify the Codebase Contract** — read `core/schema.py` lines 104–173 before making any change.
4. **Update status** in `sdd/tasks/index/formfield-content-type.json` → `"in_progress"`.
5. **Implement** by inserting the two fields after line 123, updating the docstring.
6. **Verify** all acceptance criteria above.
7. **Move this file** to `sdd/tasks/completed/TASK-2677-formfield-schema-extension.md`.
8. **Update index** → `"completed"`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: —
**Date**: —
**Notes**: —
**Deviations from spec**: none
