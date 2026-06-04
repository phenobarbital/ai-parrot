# TASK-1459: Add FieldType.AUDIO to Core Type Enum

**Feature**: FEAT-224 — FormDesigner Audio Renderer
**Spec**: `sdd/specs/formdesigner-audio-renderer.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

This is the foundation task for the Audio Renderer feature. All other tasks
depend on `FieldType.AUDIO` existing in the enum. It implements Spec §3 Module 1.

---

## Scope

- Add `AUDIO = "audio"` to the `FieldType` enum in `core/types.py`, after the
  existing Phase 3 field types.
- Verify that `FormField(field_type=FieldType.AUDIO, ...)` validates correctly
  via Pydantic.
- Write a minimal unit test confirming the new enum member exists and is usable.

**NOT in scope**: Audio field renderer, control metadata, or any rendering logic.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/core/types.py` | MODIFY | Add `AUDIO = "audio"` to `FieldType` |
| `tests/formdesigner/test_audio_fieldtype.py` | CREATE | Unit test for new enum member |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_formdesigner.core.types import FieldType  # verified: core/types.py:16
from parrot_formdesigner.core.schema import FormField  # verified: core/schema.py:24
```

### Existing Signatures to Use
```python
# packages/parrot-formdesigner/src/parrot_formdesigner/core/types.py:16
class FieldType(str, Enum):
    TEXT = "text"           # line 19
    # ... 30 members
    REST = "rest"           # line 51 — last current member
    # AUDIO does NOT exist — add after REST
```

### Does NOT Exist
- ~~`FieldType.AUDIO`~~ — does not exist yet, this task creates it
- ~~`FieldType.VOICE`~~ — does not exist, use `AUDIO` not `VOICE`
- ~~`parrot_formdesigner.core.types.AudioFieldType`~~ — no separate type class

---

## Implementation Notes

### Pattern to Follow
```python
# Add after line 51 (REST = "rest"):
# Phase 4 — audio form renderer (FEAT-224)
AUDIO = "audio"
```

### Key Constraints
- The enum value MUST be `"audio"` (lowercase, matches the renderer format key).
- Place the new member after the Phase 3 comment block, with its own Phase 4 comment.

### References in Codebase
- `packages/parrot-formdesigner/src/parrot_formdesigner/core/types.py` — enum definition

---

## Acceptance Criteria

- [ ] `FieldType.AUDIO` is a valid enum member with value `"audio"`
- [ ] `FieldType("audio") == FieldType.AUDIO` returns `True`
- [ ] `FormField(field_id="test", field_type=FieldType.AUDIO, label="Test")` validates
- [ ] Unit test passes: `pytest tests/formdesigner/test_audio_fieldtype.py -v`
- [ ] No linting errors: `ruff check packages/parrot-formdesigner/src/parrot_formdesigner/core/types.py`

---

## Test Specification

```python
# tests/formdesigner/test_audio_fieldtype.py
import pytest
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.core.schema import FormField


class TestAudioFieldType:
    def test_audio_enum_exists(self):
        assert hasattr(FieldType, "AUDIO")
        assert FieldType.AUDIO.value == "audio"

    def test_audio_from_value(self):
        assert FieldType("audio") == FieldType.AUDIO

    def test_formfield_accepts_audio(self):
        field = FormField(
            field_id="voice_note",
            field_type=FieldType.AUDIO,
            label="Leave a voice note",
        )
        assert field.field_type == FieldType.AUDIO

    def test_audio_is_str_enum(self):
        assert isinstance(FieldType.AUDIO, str)
        assert FieldType.AUDIO == "audio"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/formdesigner-audio-renderer.spec.md` for full context
2. **Check dependencies** — this task has none
3. **Verify the Codebase Contract** — confirm `FieldType` enum is still at `core/types.py:16` and `REST` is still the last member
4. **Update status** in `sdd/tasks/index/formdesigner-audio-renderer.json` → `"in-progress"`
5. **Implement** — add the enum member
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-1459-fieldtype-audio-enum.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
