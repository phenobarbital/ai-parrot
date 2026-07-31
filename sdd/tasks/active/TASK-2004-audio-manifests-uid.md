# TASK-2004: Audio session manifests carry field_uid

**Feature**: FEAT-393 — Stable UUID-Based Field Identity (field_uid)
**Spec**: `sdd/specs/formdesigner-field-uid.spec.md`
**Status**: pending
**Priority**: low
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1996
**Assigned-to**: unassigned

---

## Context

Implements Module 10 of FEAT-393 (spec §3, blueprint §9). Audio conversation
manifests (`AudioQuestion`/`AudioAnswer`) gain UID identity; the WebSocket
wire protocol keeps `field_id` keys (answer-payload semantics — resolved at
spec time).

---

## Scope

- `audio/models.py`: `AudioQuestion.field_uid: uuid.UUID`;
  `AudioAnswer.field_uid: uuid.UUID | None = None`; keep `field_id` on both.
- `renderers/audio.py` (:358): populate `field_uid=field.field_uid` when
  building questions.
- `api/audio_ws.py`: NO wire changes — inbound/outbound messages keep
  `"field_id"` keys; internal manifest lookups unchanged semantics.
- Update audio tests for the new fields.

**NOT in scope**: WS protocol changes (explicit non-goal); the audio HTML
field template `data-field-uid` attribute (TASK-2005).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/audio/models.py` | MODIFY | AudioQuestion/AudioAnswer field_uid |
| `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/audio.py` | MODIFY | populate field_uid (:358) |
| `packages/parrot-formdesigner/tests/formdesigner/test_audio_form_renderer.py` | MODIFY | new-field assertions |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_formdesigner.audio.models import AudioQuestion, AudioAnswer
```

### Existing Signatures to Use
```python
# audio/models.py
class AudioQuestion(BaseModel):   # field_id: str (:98) — "The FormField.field_id this question maps to" (:74)
class AudioAnswer(BaseModel):     # field_id: str (:152)
# AudioSessionState.answers — "Map of field_id → AudioAnswer" (:170) — KEY STAYS field_id

# renderers/audio.py — AudioQuestion(field_id=field.field_id, ...) (:358)

# api/audio_ws.py — class AudioFormWSHandler (:102)
# wire handlers read data.get("field_id", ...) (:511, :537, :588, :621-627, :822)
# _question_for_field(self, ..., field_id: str) (:915-926)
# turn-order gate _current_question (:928-956) — compares field_id strings
```

### Does NOT Exist
- ~~`field_uid` keys in WS messages~~ — wire protocol is field_id by DESIGN (spec §8, resolved)
- ~~UID-keyed AudioSessionState.answers~~ — stays field_id-keyed

---

## Implementation Notes

### Pattern to Follow
Spec §9 "Module 10" blueprint.

### Key Constraints
- Purely additive: existing WS tests must pass without modification.
- `AudioAnswer.field_uid` optional (answers may be reconstructed from wire
  data that has no UID).

---

## Acceptance Criteria

- [ ] `AudioQuestion.field_uid` populated from the source field
- [ ] WS wire messages unchanged (existing audio_ws tests green untouched)
- [ ] `pytest packages/parrot-formdesigner/tests/ -k audio -v` passes; `ruff check` clean

---

## Test Specification

```python
def test_audio_question_carries_uid(sample_form): ...
def test_audio_answer_field_uid_optional(): ...
def test_ws_wire_shape_unchanged(existing_ws_fixture): ...
```

---

## Agent Instructions

1. **Read the spec** §9 Module 10; verify TASK-1996 completed.
2. **Verify the contract** anchors.
3. **Update status** in `sdd/tasks/index/formdesigner-field-uid.json` → `"in-progress"`.
4. **Implement**, run tests, verify acceptance criteria.
5. **Move this file** to `sdd/tasks/completed/`, update index → `"done"`, fill Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
