# TASK-4210: VoiceEvidenceEnvelope subclass + is_voice_envelope/unwrap_voice/wrap_voice helpers

**Feature**: FEAT-649 — Audio Form Interaction Workflow
**Spec**: `sdd/specs/audio-form-interaction-workflow.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-4209
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 1 (envelope part), §2 Data Models, owner decision "VoiceEvidenceEnvelope
is a subclass of VoiceAnswerEnvelope". Every spoken answer, of any field type, is stored
as an envelope in `FormSubmission.data[field_id]` (G6, AC8). The planner (TASK-4217),
validator (TASK-4223), pipeline (TASK-4222) and sinks (TASK-4229) all go through the three
helpers created here, so the scalar ↔ envelope rule lives in exactly one place.

---

## Scope

- Add `VoiceEvidenceEnvelope(VoiceAnswerEnvelope)` to `core/voice_answer.py` with `answer: Any`
  and the evidence fields from spec §2.
- Add `is_voice_envelope()`, `unwrap_voice()`, `wrap_voice()`.
- Export the four names from `core/__init__.py`.
- Write `test_voice_evidence_envelope_subclass`.

**NOT in scope**: validator envelope widening (TASK-4223); sink JSONB serialisation (TASK-4229);
adding `blob_ref`/`audio_mime`/… to `AudioAnswer` (TASK-4211 — this task must not depend on it).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/core/voice_answer.py` | MODIFY | Subclass + 3 helpers below the base class |
| `packages/parrot-formdesigner/src/parrot_formdesigner/core/__init__.py` | MODIFY | Export new names |
| `packages/parrot-formdesigner/tests/formdesigner/test_voice_evidence_envelope.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.

### Verified Imports
```python
# inside core/voice_answer.py
from pydantic import BaseModel, ConfigDict, Field                       # verified: core/voice_answer.py:10 (already imported)
from .llm_validation import PlausibilityVerdict                         # created by TASK-4209 (core/llm_validation.py)
# TYPE_CHECKING only:
from ..audio.models import AudioAnswer                                  # verified: audio/models.py:153

# tests
from parrot_formdesigner.core import VoiceAnswerEnvelope                # verified: core/__init__.py:53
from parrot_formdesigner.core import PlausibilityVerdict                # exported by TASK-4209
```

### Existing Signatures to Use
```python
# core/voice_answer.py
class VoiceAnswerEnvelope(BaseModel):                                   # line 13 <- anchor
    model_config = ConfigDict(extra="forbid")                           # line 25
    answer: str = Field(..., description="Transcribed text answer")     # line 27
    blob_ref: str | None = Field(default=None, ...)                     # line 28
    data_url: str | None = Field(default=None, ...)                     # line 29  (last line of file)

# audio/models.py — current AudioAnswer (TASK-4211 later ADDS blob_ref, audio_mime, duration_ms, stt_language)
class AudioAnswer(BaseModel):                                           # line 153
    field_id: str; value: str; source: Literal["text", "speech", "selection"]; confidence: Optional[float]   # :171-175
```

### Does NOT Exist
- ~~`VoiceEvidenceEnvelope`~~, ~~`is_voice_envelope`~~, ~~`unwrap_voice`~~, ~~`wrap_voice`~~ — created here.
- ~~`AudioAnswer.blob_ref` / `.audio_mime` / `.duration_ms` / `.stt_language`~~ — do not exist yet (TASK-4211 adds them in parallel); `wrap_voice` reads them with `getattr(answer, name, None)`.
- ~~`VoiceAnswerEnvelope.source`~~ / `.confidence` — only on the subclass.
- Do NOT change `VoiceAnswerEnvelope` itself — FEAT-488 tests pin `answer: str` + `extra="forbid"`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/parrot-formdesigner/src/parrot_formdesigner/core/voice_answer.py", "action": "MODIFY"},
    {"path": "packages/parrot-formdesigner/src/parrot_formdesigner/core/__init__.py", "action": "MODIFY"},
    {"path": "packages/parrot-formdesigner/tests/formdesigner/test_voice_evidence_envelope.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/core/voice_answer.py#VoiceAnswerEnvelope",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/audio/models.py#AudioAnswer"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Pydantic v2 allows a subclass to override `answer: str` with `answer: Any`; `extra="forbid"` is inherited — keep it.
- `is_voice_envelope` shape rule (spec §3 M1): a `VoiceAnswerEnvelope` instance, or a `dict` with an `answer` key AND (`source == "speech"` OR a `blob_ref` key). A plain FEAT-488 dict `{"answer": "x"}` with neither marker is NOT treated as an envelope (it is arbitrary JSON on a JSON field).
- `unwrap_voice` / `wrap_voice` are idempotent and never mutate their input.
- `data_url` is never produced server-side (AC8): `wrap_voice` leaves it `None`.
- `core/voice_answer.py` must not import `audio/` at runtime (TYPE_CHECKING only).

---

## Implementation Blueprint

### Steps (in order)
1. Append the subclass and helpers to `core/voice_answer.py` — *why*: one owner of the envelope rule.
2. Export from `core/__init__.py` — *why*: consumers import from `parrot_formdesigner.core`.
3. Write tests; run them plus the FEAT-488 tests in `tests/unit/test_core_models.py` — *why*: base contract must not move.

### `packages/parrot-formdesigner/src/parrot_formdesigner/core/voice_answer.py` (MODIFY — imports)
```python
# occurrences: 1 (verified: grep -c 'from pydantic import BaseModel, ConfigDict, Field' core/voice_answer.py)
# REPLACE the import block at core/voice_answer.py:8-10 with:
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .llm_validation import PlausibilityVerdict

if TYPE_CHECKING:
    from ..audio.models import AudioAnswer
```

### `packages/parrot-formdesigner/src/parrot_formdesigner/core/voice_answer.py` (MODIFY — append at end of file)
```python
# occurrences: 1 (verified: grep -c 'class VoiceAnswerEnvelope(BaseModel):' core/voice_answer.py)
# AFTER — append below the VoiceAnswerEnvelope class body (class at core/voice_answer.py:13, file ends at :29)


class VoiceEvidenceEnvelope(VoiceAnswerEnvelope):
    """Envelope for any spoken answer (FEAT-649): typed answer + STT/recording evidence.

    ``answer`` carries the field's normalised scalar (list for MULTI_SELECT,
    bool for BOOLEAN, ...). The FEAT-488 base keeps ``answer: str``.
    """

    answer: Any = Field(..., description="Normalised answer value")
    confidence: float | None = None
    source: Literal["speech"] = "speech"
    audio_mime: str | None = None
    duration_ms: int | None = None
    language: str | None = None
    plausibility: PlausibilityVerdict | None = None


def is_voice_envelope(value: Any) -> bool:
    """Return True for a value carrying the voice-envelope shape."""
    if isinstance(value, VoiceAnswerEnvelope):
        return True
    if not isinstance(value, dict) or "answer" not in value:
        return False
    return value.get("source") == "speech" or "blob_ref" in value


def unwrap_voice(data: dict[str, Any]) -> dict[str, Any]:
    """Return a new dict where every envelope is replaced by its ``answer``."""
    out: dict[str, Any] = {}
    for key, value in data.items():
        if isinstance(value, VoiceAnswerEnvelope):
            out[key] = value.answer
        elif is_voice_envelope(value):
            out[key] = value["answer"]
        else:
            out[key] = value
    return out


def wrap_voice(scalars: dict[str, Any], evidence: dict[str, AudioAnswer]) -> dict[str, Any]:
    """Re-fold sanitised scalars into envelopes for spoken answers.

    For each ``field_id`` whose ``evidence[field_id].source == "speech"`` the scalar
    becomes ``VoiceEvidenceEnvelope(...).model_dump()``; all other values are copied.
    Values that already are envelopes are kept as-is (idempotent).
    """
    out: dict[str, Any] = dict(scalars)
    for field_id, answer in evidence.items():
        if field_id not in scalars or getattr(answer, "source", None) != "speech":
            continue
        if is_voice_envelope(scalars[field_id]):
            continue
        # FILL IN: build VoiceEvidenceEnvelope(answer=scalars[field_id], confidence=answer.confidence,
        #          blob_ref/audio_mime/duration_ms via getattr(answer, name, None), language=getattr(answer, "stt_language", None))
        #          and store .model_dump(); data_url stays None — bounded by AC8 ("data_url is never produced server-side")
    return out
```
**Why this shape**: the subclass and helper signatures are fixed by spec §3 M1; `getattr` keeps this task independent of TASK-4211, which adds the evidence fields to `AudioAnswer` concurrently.

### `packages/parrot-formdesigner/src/parrot_formdesigner/core/__init__.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'from .voice_answer import VoiceAnswerEnvelope' core/__init__.py)
# REPLACE `from .voice_answer import VoiceAnswerEnvelope` (verified: core/__init__.py:53) with:
from .voice_answer import (
    VoiceAnswerEnvelope,
    VoiceEvidenceEnvelope,
    is_voice_envelope,
    unwrap_voice,
    wrap_voice,
)
# and add after the "VoiceAnswerEnvelope", entry in __all__ (core/__init__.py:60):
#   "VoiceEvidenceEnvelope", "is_voice_envelope", "unwrap_voice", "wrap_voice",
```
**Why**: TASK-4209 already added other FEAT-649 lines near this anchor; the anchor line itself is unchanged by it — re-run `grep -c` before editing.

### FILL IN checklist
- [ ] `core/voice_answer.py::wrap_voice` — envelope construction from evidence; bounded by AC8
- [ ] test bodies marked `FILL IN`

---

## Acceptance Criteria

- [ ] `VoiceAnswerEnvelope(answer=["a"])` still fails validation; `VoiceAnswerEnvelope(answer="x", foo=1)` still fails (FEAT-488 contract unchanged).
- [ ] `VoiceEvidenceEnvelope(answer=["a", "b"])` and `VoiceEvidenceEnvelope(answer=True)` validate; `extra="forbid"` still rejects unknown keys.
- [ ] `unwrap_voice` and `wrap_voice` are idempotent and do not mutate inputs.
- [ ] `{"answer": "x"}` without `source`/`blob_ref` is not an envelope.
- [ ] Wrapped envelopes never carry `data_url`.
- [ ] `ruff check` passes on touched files.

---

## Validation Commands

- `pytest packages/parrot-formdesigner/tests/formdesigner/test_voice_evidence_envelope.py -q`
- `pytest packages/parrot-formdesigner/tests/unit/test_core_models.py -q`

---

## Test Specification

```python
# packages/parrot-formdesigner/tests/formdesigner/test_voice_evidence_envelope.py
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from parrot_formdesigner.core import (
    VoiceAnswerEnvelope,
    VoiceEvidenceEnvelope,
    is_voice_envelope,
    unwrap_voice,
    wrap_voice,
)


class TestVoiceEvidenceEnvelopeSubclass:
    def test_base_contract_unchanged(self):
        with pytest.raises(ValidationError):
            VoiceAnswerEnvelope(answer=["a"])
        with pytest.raises(ValidationError):
            VoiceAnswerEnvelope(answer="x", foo=1)

    def test_subclass_accepts_typed_answers(self):
        assert VoiceEvidenceEnvelope(answer=["a", "b"]).answer == ["a", "b"]
        assert VoiceEvidenceEnvelope(answer=True).source == "speech"
        with pytest.raises(ValidationError):
            VoiceEvidenceEnvelope(answer="x", bogus=1)

    def test_is_voice_envelope_shape(self):
        assert is_voice_envelope({"answer": "x", "blob_ref": None})
        assert is_voice_envelope({"answer": 3, "source": "speech"})
        assert not is_voice_envelope({"answer": "x"})
        assert not is_voice_envelope("x")

    def test_unwrap_idempotent_and_pure(self):
        data = {"a": {"answer": 1, "source": "speech"}, "b": "plain"}
        once = unwrap_voice(data)
        assert once == {"a": 1, "b": "plain"}
        assert unwrap_voice(once) == once
        assert data["a"] == {"answer": 1, "source": "speech"}

    def test_wrap_only_speech_and_idempotent(self):
        evidence = {
            "a": SimpleNamespace(source="speech", confidence=0.9, blob_ref="voice-s-1", audio_mime="audio/webm"),
            "b": SimpleNamespace(source="text", confidence=None),
        }
        wrapped = wrap_voice({"a": "red", "b": "typed"}, evidence)
        # FILL IN: assert wrapped["a"] is an envelope dict with answer "red", blob_ref "voice-s-1", data_url None;
        #          wrapped["b"] == "typed"; wrap_voice(wrapped, evidence) == wrapped
        ...
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug audio-form-interaction-workflow --feature-id FEAT-649`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in the
   per-spec index `sdd/tasks/index/audio-form-interaction-workflow.json`
4. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
5. **Update status** in `sdd/tasks/index/audio-form-interaction-workflow.json` → `"in-progress"`
   (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes
7. **Verify** all acceptance criteria are met — run the Validation Commands
   (with `PYTHONPATH=packages/parrot-formdesigner/src` inside the worktree)
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4210 audio-form-interaction-workflow verified`
   — it moves this file to `sdd/tasks/completed/` and marks it `"done"` in the
   index; never move or copy the file by hand
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
