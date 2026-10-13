# TASK-4269: Make the voice-envelope predicate exact (photos are never voice)

**Feature**: FEAT-656 — Audio form client-submit mode (voice collects, the host submits)
**Spec**: `sdd/specs/audio-form-client-submit.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Found by the FieldSync FEAT-715 worker (2026-10-12) and approved by Juan as a parrot fix inside FEAT-656
(same voice release). `is_voice_envelope` (`core/voice_answer.py:55-61`) treats ANY dict with `answer`
and a `blob_ref` key as a voice envelope:

```python
return value.get("source") == "speech" or "blob_ref" in value
```

Upload/photo answers stored in FieldSync have exactly that shape — the legacy pre-0.10.1 upload shape
`{answer, blob_ref, display}` and the stored file shape `{answer: "image.jpg", filename, content_type, blob_ref}`
(fixture `fieldsync/tests/reporting/test_export_photo_links.py:43`). So every photo is classified as voice:
`unwrap_voice` replaces it with its filename, and FieldSync (FEAT-715) would count/serve photos as audio.
The same loose rule is copied in migration 009 (`fd_unwrap_voice`, `migrations/009_voice_envelope_form_data.sql:11-13`)
and migration 010 (`_is_voice_envelope`, `migrations/010_voice_envelope_report.py:43-44`), where
`010 --downgrade --apply` would turn every photo into its filename and lose its `blob_ref`.

**The exact rule.** A voice envelope is:
- a `VoiceAnswerEnvelope` instance (or subclass, i.e. `VoiceEvidenceEnvelope`); or
- a dict with `answer` and `source == "speech"` (FEAT-649 evidence envelope); or
- a dict with `answer` and `blob_ref` whose keys are a SUBSET of `{"answer", "blob_ref", "data_url"}` — the
  FEAT-488 v1 shape. `VoiceAnswerEnvelope` is `extra="forbid"`, so any other key (`filename`, `content_type`,
  `display`, `size`, `checksum`, `thumbnail_url`, …) proves it is not a v1 voice envelope.

Migration 009's legacy normalisation writes `{"answer": <s>, "blob_ref": null}` — still voice under the new rule.

---

## Scope

- Implement the exact rule in `is_voice_envelope` (`core/voice_answer.py`), add a module constant
  `_V1_VOICE_KEYS = frozenset({"answer", "blob_ref", "data_url"})`.
- Same rule in `fd_unwrap_voice` (009 SQL): `kv.value->>'source' = 'speech' OR (kv.value ? 'blob_ref' AND (kv.value - 'answer' - 'blob_ref' - 'data_url') = '{}'::jsonb)`.
  `CREATE OR REPLACE` keeps the migration idempotent; re-running it replaces the function.
- Same rule in 010's local mirror `_is_voice_envelope` (kept standalone on purpose — do not import).
- Tests (below). Update the existing `test_is_voice_envelope_shape` (it asserts the v1 shape, still valid).

**NOT in scope**: `wrap_voice` / `unwrap_voice` signatures (they call the predicate and inherit the fix);
FieldSync code (FEAT-715); any data migration.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/core/voice_answer.py` | MODIFY | exact predicate |
| `packages/parrot-formdesigner/migrations/009_voice_envelope_form_data.sql` | MODIFY | same rule in `fd_unwrap_voice` |
| `packages/parrot-formdesigner/migrations/010_voice_envelope_report.py` | MODIFY | same rule in the mirror |
| `packages/parrot-formdesigner/tests/formdesigner/test_voice_evidence_envelope.py` | MODIFY | predicate + unwrap tests |
| `packages/parrot-formdesigner/tests/formdesigner/test_voice_envelope_migrations.py` | MODIFY | 009 text + 010 mirror parity |

---

## Codebase Contract (Anti-Hallucination)

```python
# core/voice_answer.py
class VoiceAnswerEnvelope(BaseModel)          # :20 — extra="forbid"; answer, blob_ref, data_url
class VoiceEvidenceEnvelope(VoiceAnswerEnvelope)   # adds confidence, source="speech", audio_mime, duration_ms, language, plausibility (:~40-52)
def is_voice_envelope(value: Any) -> bool     # :55-61
#   occurrences 1: grep -cF 'return value.get("source") == "speech" or "blob_ref" in value' core/voice_answer.py
def unwrap_voice(data) -> dict                # :64-74 (uses is_voice_envelope)
def wrap_voice(scalars, evidence) -> dict     # :77+ (uses is_voice_envelope for idempotency)
# migrations/009_voice_envelope_form_data.sql :4-21 fd_unwrap_voice; line 13:
#   AND (kv.value->>'source' = 'speech' OR kv.value ? 'blob_ref')
# migrations/010_voice_envelope_report.py :43-44
#   return isinstance(value, dict) and "answer" in value and (value.get("source") == "speech" or "blob_ref" in value)
# tests: test_voice_evidence_envelope.py:28-32 test_is_voice_envelope_shape ; test_voice_envelope_migrations.py:106 (SQL text assertion pattern)
```
### Does NOT Exist
- ~~a field-type-aware predicate~~ — keep it value-only (callers have no schema).
- ~~`FileEnvelope` import in voice_answer.py~~ — not needed; the key-subset rule is enough.

## Complexity Contract
```json
{"schema_version": 1, "targets": [
 {"path": "packages/parrot-formdesigner/src/parrot_formdesigner/core/voice_answer.py", "action": "MODIFY"},
 {"path": "packages/parrot-formdesigner/migrations/009_voice_envelope_form_data.sql", "action": "MODIFY"},
 {"path": "packages/parrot-formdesigner/migrations/010_voice_envelope_report.py", "action": "MODIFY"},
 {"path": "packages/parrot-formdesigner/tests/formdesigner/test_voice_evidence_envelope.py", "action": "MODIFY"},
 {"path": "packages/parrot-formdesigner/tests/formdesigner/test_voice_envelope_migrations.py", "action": "MODIFY"}],
 "contract_symbols": ["sym:packages/parrot-formdesigner/src/parrot_formdesigner/core/voice_answer.py#is_voice_envelope"]}
```

## Implementation Blueprint

### `core/voice_answer.py` (MODIFY)
```python
_V1_VOICE_KEYS = frozenset({"answer", "blob_ref", "data_url"})  # VoiceAnswerEnvelope is extra="forbid"


def is_voice_envelope(value: Any) -> bool:
    """True for a voice envelope: a model instance, a speech evidence dict, or the exact v1 dict shape.

    Upload/photo answers (``{answer, blob_ref, display}`` or ``{answer, filename, content_type, blob_ref, …}``)
    are NOT voice: any key outside ``answer`` / ``blob_ref`` / ``data_url`` rules the v1 shape out.
    """
    if isinstance(value, VoiceAnswerEnvelope):
        return True
    if not isinstance(value, dict) or "answer" not in value:
        return False
    if value.get("source") == "speech":
        return True
    return "blob_ref" in value and set(value) <= _V1_VOICE_KEYS
```

### Tests (FILL IN bodies)
```python
PHOTO_LEGACY = {"answer": "a.jpg", "blob_ref": "s3://b/k", "display": "a.jpg"}
PHOTO_FILE = {"answer": "a.jpg", "filename": "a.jpg", "content_type": "image/jpeg", "blob_ref": "s3://b/k"}
V1_NULL = {"answer": "hi", "blob_ref": None}
V1_FULL = {"answer": "hi", "blob_ref": "voice-s-f", "data_url": None}
SPEECH = {"answer": 3, "source": "speech", "blob_ref": "voice-s-f", "confidence": 0.9}
# FILL IN: test_photo_shapes_are_not_voice (both photos False), test_v1_and_speech_are_voice,
#          test_unwrap_voice_keeps_photos (photo dicts unchanged; voice → answer)
# FILL IN: 010 mirror parity — for every sample, migrations 010 _is_voice_envelope(sample) == is_voice_envelope(sample)
#          (load the script module with importlib from its path, as test_voice_envelope_migrations.py does)
# FILL IN: 009 SQL text — contains "- 'answer' - 'blob_ref' - 'data_url'" and no bare "OR kv.value ? 'blob_ref')"
```
Mutation-check: revert the subset clause → the photo tests go RED; restore from a saved copy.

## Acceptance Criteria
- [ ] Photo/upload envelopes (legacy and file shapes) are never voice in Python, 009 SQL and 010.
- [ ] v1 voice (`{answer, blob_ref}` / `+ data_url`) and speech evidence envelopes remain voice.
- [ ] `unwrap_voice` leaves photo answers untouched.
- [ ] All existing tests in the two test files pass; ruff clean.

## Validation Commands
- `pytest packages/parrot-formdesigner/tests/formdesigner/test_voice_evidence_envelope.py -q`
- `pytest packages/parrot-formdesigner/tests/formdesigner/test_voice_envelope_migrations.py -q`
- `pytest packages/parrot-formdesigner/tests/formdesigner/test_audio_ws_v2_integration.py -q`

## Completion Note
*(Agent fills this in when done)*
