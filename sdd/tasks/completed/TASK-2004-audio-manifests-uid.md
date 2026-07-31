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

**Completed by**: sdd-worker (autonomous)
**Date**: 2026-07-31
**Notes**:

Implemented exactly per Scope: `AudioQuestion.field_uid: uuid.UUID`
(required — a question always maps to a real field), `AudioAnswer.field_uid:
Optional[uuid.UUID] = None` (optional — answers may be reconstructed from
wire data with no UID). `renderers/audio.py` populates
`field_uid=field.field_uid` at the single `AudioQuestion(...)` construction
site. No WS wire changes: `api/audio_ws.py` untouched, confirmed by the full
`test_audio_ws_handler.py` suite passing unmodified in behavior (only its
fixture constructions needed a `field_uid` value — see below).

Test fallout (root-caused individually, all directly caused by
`AudioQuestion.field_uid` becoming a required field):
- `tests/formdesigner/test_audio_models.py` (9 sites) and
  `tests/formdesigner/test_audio_ws_handler.py` (38 sites) construct
  `AudioQuestion(...)` directly and needed a `field_uid` value to satisfy
  the new required field. Neither file is in the task's Files table, but
  both are genuine, mechanical fallout (ValidationError: field_uid missing)
  — not a design change. Fixed via a shared module-level `_UID =
  uuid.uuid4()` sentinel constant + `AudioQuestion(field_uid=_UID, ...)`
  at every site, since none of these tests assert on field_uid values
  themselves (only presence/validity was required).
- Added the task's 3 named Test Specification tests to
  `test_audio_models.py`: `test_audio_question_carries_uid` (field_uid
  round-trips exactly), a `test_field_uid_required` companion (rejects
  construction without it), and `test_audio_answer_field_uid_optional`
  (defaults to `None`, accepts an explicit UUID).
- Added `test_question_carries_field_uid` to
  `tests/formdesigner/test_audio_form_renderer.py` (the file explicitly
  listed in scope) asserting the renderer-built questions carry the
  SAME `field_uid` as their source `FormField`.

Deviation (documented, not in the task's file list):
`renderers/audio.py`'s `manifest.model_dump(exclude=...)` used the default
`mode="python"`, which kept `field_uid` (and `form_uid`) as raw
`uuid.UUID` objects. `api/render.py`'s `_coerce_body` calls plain
`json.dumps()` on that dict, which raised
`TypeError: Object of type UUID is not JSON serializable` — a genuine
runtime-breaking bug surfaced by 3 previously-passing
`test_audio_integration.py::TestRenderEndpoint` tests (500 errors).
Fixed with the minimal, already-established codebase convention
(`model_dump(mode="json", ...)`, used identically in `operations.py`,
`edit_toolkit.py`, `rbac.py`, `question_bank.py`) rather than touching
`api/render.py`'s generic `_coerce_body` — mirrors the TASK-1995
html5.py/audio.py `str()`-wrapping precedent for genuine field_uid-typing
fallout outside a task's stated file list.

Full suite: `pytest packages/parrot-formdesigner/tests/ -q` → 1820 passed,
exactly the same 20 pre-existing/unrelated baseline failures as every prior
task in this feature. `ruff check` diffed via `git stash` before/after: one
new finding (`UP045` on the new `Optional[uuid.UUID]` field) — matches the
file's own pre-existing, unaddressed style (12 other `Optional[X]` fields
in this exact file use the same `Optional[...]` form, not `X | None`);
left as-is for local consistency rather than introducing one field with a
different style than its 5 siblings in the same class.

**Deviations from spec**: `tests/formdesigner/test_audio_models.py`,
`tests/formdesigner/test_audio_ws_handler.py`, and
`renderers/audio.py`'s `model_dump(mode="json")` fix were not in the
task's "Files to Create/Modify" table but were genuine, directly-caused
fallout (verified via actual failing test output, not assumed) — same
precedent as prior tasks in this feature.
