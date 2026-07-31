---
type: Wiki Overview
title: 'TASK-1465: Audio Control Metadata Registration'
id: doc:sdd-tasks-completed-task-1465-audio-control-metadata-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Registers `FieldType.AUDIO` metadata in the form-controls registry so it
---

# TASK-1465: Audio Control Metadata Registration

**Feature**: FEAT-224 — FormDesigner Audio Renderer
**Spec**: `sdd/specs/formdesigner-audio-renderer.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1459
**Assigned-to**: unassigned

---

## Context

Registers `FieldType.AUDIO` metadata in the form-controls registry so it
appears in the `GET /api/v1/form-controls` toolbar endpoint. This allows
the frontend form builder to show the AUDIO field type as a draggable
control. Implements Spec §3 Module 7.

---

## Scope

- Add a `FieldType.AUDIO` entry to `_BUILTIN_METADATA` dict in `controls/builtin.py`.
- Set appropriate metadata: label, description, category, icon, render_hint.
- Write a unit test confirming the metadata is registered.

**NOT in scope**: Frontend rendering, audio recording UI, or any backend logic.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/controls/builtin.py` | MODIFY | Add AUDIO entry to `_BUILTIN_METADATA` |
| `tests/formdesigner/test_audio_control_metadata.py` | CREATE | Unit test |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_formdesigner.core.types import FieldType  # verified: core/types.py:16
from parrot_formdesigner.controls.registry import register_field_control  # verified: controls/builtin.py:21
```

### Existing Signatures to Use
```python
# packages/parrot-formdesigner/src/parrot_formdesigner/controls/builtin.py:26
_BUILTIN_METADATA: dict[FieldType, dict[str, Any]] = {
    FieldType.TEXT: {
        "label": "Text",
        "description": "Single-line text input.",
        "category": "basic",
        "icon": "text",
        "render_hint": "input",
        "supports_constraints": True,
        "is_container": False,
    },
    # ... one entry per FieldType
}
# This dict is iterated at module import time to call register_field_control()
# for each entry.
```

### Does NOT Exist
- ~~`FieldType.AUDIO` entry in `_BUILTIN_METADATA`~~ — does not exist yet
- ~~`parrot_formdesigner.controls.builtin.register_audio_control()`~~ — no such function; just add to `_BUILTIN_METADATA` dict

---

## Implementation Notes

### Pattern to Follow
```python
# Add to _BUILTIN_METADATA dict in controls/builtin.py:
FieldType.AUDIO: {
    "label": "Audio",
    "description": "Audio recording input with speech-to-text transcription.",
    "category": "advanced",
    "icon": "microphone",
    "render_hint": "audio-recorder",
    "supports_constraints": False,
    "is_container": False,
},
```

### Key Constraints
- Category should be `"advanced"` (not `"basic"`) since audio requires special infrastructure.
- `supports_constraints` is `False` — no min/max/pattern constraints apply to audio.
- `is_container` is `False` — AUDIO fields don't contain children.
- The icon name `"microphone"` follows the existing naming convention (symbolic, not a file path).

### References in Codebase
- `packages/parrot-formdesigner/src/parrot_formdesigner/controls/builtin.py:26` — metadata dict

---

## Acceptance Criteria

- [ ] `FieldType.AUDIO` has an entry in `_BUILTIN_METADATA`
- [ ] Metadata includes label, description, category, icon, render_hint, supports_constraints, is_container
- [ ] `GET /api/v1/form-controls` response includes AUDIO field type
- [ ] Tests pass: `pytest tests/formdesigner/test_audio_control_metadata.py -v`
- [ ] No linting errors

---

## Test Specification

```python
# tests/formdesigner/test_audio_control_metadata.py
import pytest
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.controls.builtin import _BUILTIN_METADATA


class TestAudioControlMetadata:
    def test_audio_in_builtin_metadata(self):
        assert FieldType.AUDIO in _BUILTIN_METADATA

    def test_audio_metadata_fields(self):
        meta = _BUILTIN_METADATA[FieldType.AUDIO]
        assert meta["label"] == "Audio"
        assert "category" in meta
        assert "icon" in meta
        assert meta["is_container"] is False

    def test_audio_category_is_advanced(self):
        meta = _BUILTIN_METADATA[FieldType.AUDIO]
        assert meta["category"] == "advanced"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/formdesigner-audio-renderer.spec.md` §3 Module 7
2. **Check dependencies** — TASK-1459 (FieldType.AUDIO) must be complete
3. **Verify the Codebase Contract** — confirm `_BUILTIN_METADATA` dict structure
4. **Update status** in `sdd/tasks/index/formdesigner-audio-renderer.json` → `"in-progress"`
5. **Implement** the metadata entry
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-1465-audio-control-metadata.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (claude-sonnet-4-6)
**Date**: 2026-06-04
**Notes**: Added `FieldType.AUDIO` entry to `_BUILTIN_METADATA` in `controls/builtin.py` with all required fields (label, description, category='advanced', icon='microphone', render_hint='audio-recorder', supports_constraints=False, is_container=False). This was necessary to fix a KeyError when importing `parrot_formdesigner.api` after adding FieldType.AUDIO to the enum. 7 unit tests pass.

**Deviations from spec**: none
