# TASK-4250: Persist post-processor provenance in the voice evidence envelope

**Feature**: FEAT-653 — Audio form voice post-processors
**Spec**: `sdd/specs/audio-form-voice-postprocessors.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-4248
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 10, owner decision §8 Q2: every non-sensitive spoken answer stores which
post-processor produced it, for all field types. That means `normalized_by` (`"rules"` /
`"llm"`), plus `llm_confidence` when the LLM produced it. Spoken answers reach the submission as
`VoiceEvidenceEnvelope` dicts built by `wrap_voice` from the engine's `AudioAnswer`s. The
validator recognises evidence envelopes by key (`FormValidator._EVIDENCE_KEYS`).

---

## Scope

- Add optional `normalized_by` and `llm_confidence` to `VoiceEvidenceEnvelope`.
- Copy them in `wrap_voice` from the `AudioAnswer` (`getattr`, like the other fields).
- Extend `FormValidator._EVIDENCE_KEYS` with both keys.
- Write `test_voice_evidence_postprocessor.py`.

**NOT in scope**: setting `normalized_by` on answers (engine, TASK-4251/4252); sink DDL (JSONB
needs no change, spec §7).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/core/voice_answer.py` | MODIFY | Two envelope fields + `wrap_voice` copy |
| `packages/parrot-formdesigner/src/parrot_formdesigner/services/validators.py` | MODIFY | `_EVIDENCE_KEYS` |
| `packages/parrot-formdesigner/tests/formdesigner/test_voice_evidence_postprocessor.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_formdesigner.core.voice_answer import VoiceEvidenceEnvelope, is_voice_envelope, unwrap_voice, wrap_voice  # voice_answer.py:39,55,64,77
from parrot_formdesigner.audio.models import AudioAnswer           # models.py:214 (normalized_by / llm_confidence added by TASK-4248)
from parrot_formdesigner.services.validators import FormValidator  # validators.py:200
```

### Existing Signatures to Use
```python
# core/voice_answer.py
class VoiceAnswerEnvelope(BaseModel): model_config = ConfigDict(extra="forbid"); answer: str; blob_ref; data_url   # :20-36
class VoiceEvidenceEnvelope(VoiceAnswerEnvelope):                                    # :39
    answer: Any; confidence; source: Literal["speech"]="speech"; audio_mime; duration_ms; language
    plausibility: PlausibilityVerdict | None = None                                  # :52 (last field)
def wrap_voice(scalars: dict[str, Any], evidence: dict[str, AudioAnswer]) -> dict[str, Any]   # :77
    #   VoiceEvidenceEnvelope(answer=..., confidence=getattr(answer, "confidence", None), blob_ref=..., audio_mime=...,
    #   duration_ms=..., language=getattr(answer, "stt_language", None),).model_dump()    # :89-97
# services/validators.py
class FormValidator:
    _EVIDENCE_KEYS = frozenset({"source", "confidence", "audio_mime", "duration_ms", "language", "plausibility"})  # :580
    # _coerce_value picks VoiceEvidenceEnvelope when `self._EVIDENCE_KEYS & value.keys()` (:684)
```

### Does NOT Exist
- ~~`VoiceEvidenceEnvelope.normalized_by`~~ / ~~`.llm_confidence`~~ — added here.
- ~~Envelopes for sensitive answers~~ — `_submission_data` never wraps them (engine.py:1143-1150); nothing to change.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/parrot-formdesigner/src/parrot_formdesigner/core/voice_answer.py", "action": "MODIFY"},
    {"path": "packages/parrot-formdesigner/src/parrot_formdesigner/services/validators.py", "action": "MODIFY"},
    {"path": "packages/parrot-formdesigner/tests/formdesigner/test_voice_evidence_postprocessor.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/core/voice_answer.py#VoiceEvidenceEnvelope",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/core/voice_answer.py#wrap_voice",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/services/validators.py#FormValidator"
  ]
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Add the two optional fields — *why*: `extra="forbid"` means old envelopes must keep validating, so both default to `None`.
2. Copy them in `wrap_voice` — *why*: G8 / AC15.
3. Extend `_EVIDENCE_KEYS` — *why*: an envelope carrying only these keys must still be recognised as evidence.
4. Write the tests.

### `core/voice_answer.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    plausibility: PlausibilityVerdict | None = None' voice_answer.py)
# AFTER — insert below `    plausibility: PlausibilityVerdict | None = None` (verified: voice_answer.py:52)
    normalized_by: Literal["rules", "llm"] | None = None  # FEAT-653: which post-processor produced `answer`
    llm_confidence: float | None = None
```
```python
# occurrences: 1 (verified: grep -c '            language=getattr(answer, "stt_language", None),' voice_answer.py)
# AFTER — insert below `            language=getattr(answer, "stt_language", None),` (verified: voice_answer.py:96)
            normalized_by=getattr(answer, "normalized_by", None),
            llm_confidence=getattr(answer, "llm_confidence", None),
```
**Why**: `Literal` is already imported (`voice_answer.py:10`). `model_dump()` keeps `None` keys —
that matches the existing behaviour of the other optional fields.

### `services/validators.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    _EVIDENCE_KEYS = frozenset(' validators.py)
# REPLACE line validators.py:580 with:
    _EVIDENCE_KEYS = frozenset(
        {"source", "confidence", "audio_mime", "duration_ms", "language", "plausibility", "normalized_by", "llm_confidence"}
    )
```

### `tests/formdesigner/test_voice_evidence_postprocessor.py` (CREATE)
```python
"""FEAT-653 TASK-4250 — post-processor provenance in the voice evidence envelope."""

from __future__ import annotations

from parrot_formdesigner.audio.models import AudioAnswer
from parrot_formdesigner.core.voice_answer import VoiceEvidenceEnvelope, unwrap_voice, wrap_voice


def test_wrap_voice_carries_postprocessor() -> None:
    ans = AudioAnswer(field_id="email", value="john@gmail.com", source="speech", confidence=0.9,
                      normalized_by="llm", llm_confidence=0.93)
    out = wrap_voice({"email": "john@gmail.com"}, {"email": ans})
    assert out["email"]["normalized_by"] == "llm" and out["email"]["llm_confidence"] == 0.93
    assert unwrap_voice(out) == {"email": "john@gmail.com"}


def test_rules_provenance_without_llm() -> None:
    ans = AudioAnswer(field_id="phone", value="5550123", source="speech", normalized_by="rules")
    env = wrap_voice({"phone": "5550123"}, {"phone": ans})["phone"]
    assert env["normalized_by"] == "rules" and env["llm_confidence"] is None


def test_old_envelope_still_validates() -> None:
    old = {"answer": "x", "source": "speech", "confidence": 0.8}
    assert VoiceEvidenceEnvelope.model_validate(old).normalized_by is None


def test_validator_recognises_new_keys() -> None:
    # FILL IN: a FormField NUMBER answered with {"answer": 25, "normalized_by": "rules"} (no other evidence
    # keys) is unwrapped/validated as an evidence envelope via FormValidator (see _scalar_view / _coerce_value)
```

### FILL IN checklist
- [ ] `test_validator_recognises_new_keys` — bounded by `FormValidator._is_evidence_envelope_value` / `_scalar_view`

---

## Acceptance Criteria

- [ ] `wrap_voice` output carries both keys for every spoken answer (AC15).
- [ ] Pre-FEAT-653 envelopes validate unchanged.
- [ ] Existing envelope / validator tests pass unmodified; `ruff check` clean.

---

## Validation Commands

- `pytest packages/parrot-formdesigner/tests/formdesigner/test_voice_evidence_postprocessor.py -q`
- `pytest packages/parrot-formdesigner/tests/formdesigner/test_voice_evidence_envelope.py -q`

---

## Test Specification

See the CREATE block above.

---

## Agent Instructions

1. Work in the feature worktree: `python -m scripts.sdd.ensure_worktree --slug audio-form-voice-postprocessors --feature-id FEAT-653`.
2. Read the spec; check `Depends-on` tasks are `done` in `sdd/tasks/index/audio-form-voice-postprocessors.json`.
3. Verify the Codebase Contract before writing code.
4. Set this task `in-progress` in the index and commit only the index.
5. Implement from the blueprint; complete every `FILL IN`; never change a fixed name or path.
6. Run the Validation Commands with `PYTHONPATH=packages/parrot-formdesigner/src`.
7. Commit only the listed files; close with `scripts/sdd/close_task.sh TASK-4250 audio-form-voice-postprocessors verified`; fill the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
