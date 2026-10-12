# TASK-4248: Post-processor config + protocol models

**Feature**: FEAT-653 — Audio form voice post-processors
**Spec**: `sdd/specs/audio-form-voice-postprocessors.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 5. This task adds every new setting and wire/internal message field that the
engine (TASK-4251/4252) and the WS adapter (TASK-4253) consume. Every addition is optional with a
default, so v1/v2 clients that send none of the new fields keep working (G7), and stored
snapshots of the `extra="forbid"` models still load.

---

## Scope

- `core/voice.py`:
  - `FieldVoiceMeta.normalize: bool = True`;
  - `FieldVoiceMeta.llm_refine: bool | None = None`;
  - `VoiceFormConfig.llm_refine_values: bool = False`;
  - `VoiceFormConfig.llm_refine_threshold: float = 0.8`;
  - `VoiceFormConfig.llm_refine_timeout_s: float = 4.0`.
- `audio/events.py`:
  - `StartSession.timezone`;
  - `ConfirmRequest.value` and `ConfirmRequest.refined_by`;
  - `AnswerRejected.value`;
  - new internal inbound `ValueRefined` (joins `InboundEvent`, never a client type);
  - new I/O request `RefineValue` (joins `IORequest`);
  - update `__all__`.
- `audio/models.py`: `AudioSessionState.timezone`, `AudioAnswer.normalized_by`,
  `AudioAnswer.llm_confidence`.
- Write `test_audio_postprocess_models.py`.

**NOT in scope**: any behaviour (engine/adapter); `Phase` (deliberately NOT extended, spec §6
Does NOT Exist); `VoiceEvidenceEnvelope` (TASK-4250).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/core/voice.py` | MODIFY | Field meta + form refine settings |
| `packages/parrot-formdesigner/src/parrot_formdesigner/audio/events.py` | MODIFY | Wire fields, `ValueRefined`, `RefineValue` |
| `packages/parrot-formdesigner/src/parrot_formdesigner/audio/models.py` | MODIFY | `timezone`, `normalized_by`, `llm_confidence` |
| `packages/parrot-formdesigner/tests/formdesigner/test_audio_postprocess_models.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_formdesigner.core.voice import FieldVoiceMeta, VoiceFormConfig, field_voice_meta  # core/voice.py:35,50,84
from parrot_formdesigner.audio.events import (StartSession, ConfirmRequest, AnswerRejected, parse_inbound,
    InboundEvent, IORequest, is_io_request)                                                     # events.py:93,334,353,529
from parrot_formdesigner.audio.models import AudioAnswer, AudioSessionState                    # models.py:214,258
from pydantic import TypeAdapter                                                                # already imported in events.py:12
```

### Existing Signatures to Use
```python
# core/voice.py
class FieldVoiceMeta(BaseModel):  model_config = ConfigDict(extra="ignore") ... sensitive: bool = False   # :35, :48
class VoiceFormConfig(BaseModel): ... llm_refine_options: bool = False (:64, unused) ... max_recording_seconds   # :50
def field_voice_meta(field, *, logger=None) -> FieldVoiceMeta   # :84 — unknown keys warn; new keys become known
# audio/events.py
__all__ = [...]                                                  # :18-87
class _Inbound(BaseModel): model_config = ConfigDict(extra="forbid")   # :89
class StartSession(_Inbound): ... enumerate_options: bool | None = None   # :93-106 (last line :106)
class SubmitDone(_Inbound)                                        # :207
InboundEvent = Annotated[Union[..., SubmitDone, IOFailed,], Field(discriminator="type")]   # :250-274 (`        IOFailed,` :271, 1 occurrence)
_CLIENT_TYPES / ClientInbound                                     # :219-249 — DO NOT add ValueRefined there
class _Wire(BaseModel): to_wire() → model_dump(mode="json", exclude_none=True)   # :281
class ConfirmRequest(_Wire): ... purpose: Literal["answer", "stop"] = "answer"  # :334-341
class AnswerRejected(_Wire): field_id; error; code: str | None = None           # :353-357
class _IORequest(BaseModel)                                       # :451
class Submit(_IORequest)                                          # :491
IORequest = Union[Synthesize, Transcribe, StoreBlob, DeleteBlob, SaveSnapshot, RunPlausibility, Submit, Replan]   # :525
# audio/models.py
class AudioAnswer(BaseModel): model_config = ConfigDict(extra="forbid") ... stt_language: Optional[str] = None (:253) ...   # :214
class AudioSessionState(BaseModel): extra="forbid" ... flagged: dict[str, int] = Field(default_factory=dict)  (:317, last field)   # :258
```

### Does NOT Exist
- ~~`Phase.REFINING`~~ — do not add (spec §6).
- ~~`ConfirmAnswer.value`~~ — corrections arrive as `answer_text`; do not add.
- ~~`StartSession.takeover`~~, ~~`SessionReplaced`~~ — the session-lock spec, not this one.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/parrot-formdesigner/src/parrot_formdesigner/core/voice.py", "action": "MODIFY"},
    {"path": "packages/parrot-formdesigner/src/parrot_formdesigner/audio/events.py", "action": "MODIFY"},
    {"path": "packages/parrot-formdesigner/src/parrot_formdesigner/audio/models.py", "action": "MODIFY"},
    {"path": "packages/parrot-formdesigner/tests/formdesigner/test_audio_postprocess_models.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/core/voice.py#FieldVoiceMeta",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/core/voice.py#VoiceFormConfig",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/audio/events.py#StartSession",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/audio/events.py#ConfirmRequest",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/audio/events.py#AnswerRejected",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/audio/models.py#AudioAnswer",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/audio/models.py#AudioSessionState"
  ]
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Add the config fields in `core/voice.py` — *why*: per-field opt-out of rules, per-field/per-form LLM opt-in (G4).
2. Add the wire and internal messages in `events.py` — *why*: the engine stays pure; the LLM call is an I/O request (design research S6).
3. Add the state/answer fields in `models.py` — *why*: provenance must survive confirm and resume (S8).
4. Write the tests.

### `core/voice.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    sensitive: bool = False' core/voice.py)
# AFTER — insert below `    sensitive: bool = False` (verified: core/voice.py:48)
    normalize: bool = True  # FEAT-653: typed rules post-processor for spoken answers of this field
    llm_refine: bool | None = None  # FEAT-653: None → inherit VoiceFormConfig.llm_refine_values
```
```python
# occurrences: 1 (verified: grep -c '    llm_refine_options: bool = False' core/voice.py)
# AFTER — insert below `    llm_refine_options: bool = False` (verified: core/voice.py:64)
    llm_refine_values: bool = False  # FEAT-653: LLM post-processor for spoken typed-family answers (opt-in)
    llm_refine_threshold: float = Field(default=0.8, ge=0.0, le=1.0)
    llm_refine_timeout_s: float = Field(default=4.0, gt=0.0)
```
**Why**: names fixed by spec §3 M5. The defaults are provisional until the calibration run (TASK-4256) replaces them.

### `audio/events.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    enumerate_options: bool | None = None' events.py)
# AFTER — insert below `    enumerate_options: bool | None = None` (verified: events.py:106, last field of StartSession)
    timezone: str | None = None  # FEAT-653: client IANA timezone (validated by the adapter)
```
```python
# occurrences: 1 (verified: grep -c '    purpose: Literal\["answer", "stop"\] = "answer"' events.py)
# AFTER — insert below the `    purpose: Literal["answer", "stop"] = "answer"  # ...` line (verified: events.py:341)
    value: Any = None  # FEAT-653: normalized candidate (v2 only; omitted for sensitive fields)
    refined_by: Literal["rules", "llm"] | None = None
```
```python
# occurrences: 1 (verified: grep -c '    code: str | None = None' events.py) — AnswerRejected's last field
# AFTER — insert below `    code: str | None = None` (verified: events.py:357)
    value: Any = None  # FEAT-653: best-effort candidate of a rejected spoken value (v2 only; never for sensitive)
```
```python
# occurrences: 1 (verified: grep -c 'class SubmitDone(_Inbound):' events.py)
# BEFORE — insert above `class SubmitDone(_Inbound):` (verified: events.py:207)
class ValueRefined(_Inbound):
    """Adapter → engine: result of a RefineValue request (FEAT-653)."""

    type: Literal["_value_refined"]
    field_id: str
    request_id: str
    status: Literal["ok", "failed", "unavailable"]
    value: str | None = None
    confidence: float | None = None


```
```python
# occurrences: 1 (verified: grep -c '        IOFailed,' events.py)
# AFTER — insert below `        IOFailed,` inside InboundEvent (verified: events.py:271)
        ValueRefined,
```
```python
# occurrences: 1 (verified: grep -c 'class Submit(_IORequest):' events.py)
# BEFORE — insert above `class Submit(_IORequest):` (verified: events.py:491)
class RefineValue(_IORequest):
    """Engine → adapter: ask the LLM post-processor to correct one spoken value (FEAT-653)."""

    type: Literal["_refine_value"] = "_refine_value"
    field_id: str
    request_id: str
    transcript: str
    candidate: Any = None
    field_type: str
    label: str
    today: str  # ISO date in the client timezone


```
```python
# occurrences: 1 (verified: grep -c '^IORequest = Union\[' events.py)
# REPLACE line events.py:525 with:
IORequest = Union[
    Synthesize, Transcribe, StoreBlob, DeleteBlob, SaveSnapshot, RunPlausibility, Submit, Replan, RefineValue
]
```
Also add `"ValueRefined"` under `# adapter-internal inbound` and `"RefineValue"` under `# I/O requests` in `__all__` (events.py:18-87).
**Why**: `ValueRefined` must stay out of `_CLIENT_TYPES` so a client can never forge it (`parse_inbound` rejects internal types).

### `audio/models.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    stt_language: Optional\[str\] = None' models.py)
# AFTER — insert below `    stt_language: Optional[str] = None` (verified: models.py:253, AudioAnswer)
    normalized_by: Optional[Literal["rules", "llm"]] = None  # FEAT-653 post-processor provenance
    llm_confidence: Optional[float] = None
```
```python
# occurrences: 1 (verified: grep -c '    flagged: dict\[str, int\] = Field(default_factory=dict)' models.py)
# AFTER — insert below `    flagged: dict[str, int] = Field(default_factory=dict)` (verified: models.py:317, AudioSessionState)
    timezone: Optional[str] = None  # FEAT-653: client IANA timezone; set on every start/resume, never snapshotted
```
Add the two fields to the docstring `Attributes:` sections of both classes. Ensure `Literal` is imported in models.py (it is used at :64 already).

### `tests/formdesigner/test_audio_postprocess_models.py` (CREATE)
```python
"""FEAT-653 TASK-4248 — post-processor config + protocol models."""

from __future__ import annotations

import pytest

from parrot_formdesigner.audio.events import (
    AnswerRejected,
    ConfirmRequest,
    RefineValue,
    StartSession,
    UnknownMessageType,
    ValueRefined,
    is_io_request,
    parse_inbound,
)
from parrot_formdesigner.audio.models import AudioAnswer, AudioSessionState
from parrot_formdesigner.core.voice import FieldVoiceMeta, VoiceFormConfig


def test_config_defaults() -> None:
    cfg = VoiceFormConfig()
    assert cfg.llm_refine_values is False and 0.0 <= cfg.llm_refine_threshold <= 1.0 and cfg.llm_refine_timeout_s > 0
    meta = FieldVoiceMeta()
    assert meta.normalize is True and meta.llm_refine is None


def test_start_session_timezone_optional() -> None:
    s = parse_inbound({"type": "start_session", "form_uid": "f", "timezone": "America/New_York"}, protocol_version=2)
    assert isinstance(s, StartSession) and s.timezone == "America/New_York"
    assert parse_inbound({"type": "start_session", "form_uid": "f"}, protocol_version=2).timezone is None


def test_wire_fields_omitted_when_unset() -> None:
    assert "value" not in ConfirmRequest(field_id="a", transcript="t").to_wire()
    wire = ConfirmRequest(field_id="a", transcript="t", value="x@y.io", refined_by="rules").to_wire()
    assert wire["value"] == "x@y.io" and wire["refined_by"] == "rules"
    assert "value" not in AnswerRejected(field_id="a", error="e").to_wire()


def test_value_refined_is_internal_only() -> None:
    with pytest.raises(UnknownMessageType):
        parse_inbound({"type": "_value_refined", "field_id": "a", "request_id": "r", "status": "ok"}, protocol_version=2)
    ValueRefined(type="_value_refined", field_id="a", request_id="r", status="failed")


def test_refine_value_is_io_request() -> None:
    req = RefineValue(field_id="a", request_id="r", transcript="t", field_type="email", label="Email", today="2026-10-12")
    assert is_io_request(req)


def test_answer_and_state_fields_default_none() -> None:
    a = AudioAnswer(field_id="a", value="v", source="speech")
    assert a.normalized_by is None and a.llm_confidence is None
    assert AudioAnswer.model_validate({"field_id": "a", "value": "v", "source": "speech"})  # old snapshot shape
    assert AudioSessionState(session_id="s", form_uid="f", user_id="u").timezone is None
```
**Note**: check how `parse_inbound` rejects internal types (`UnknownMessageType` vs a validation error) by reading `events.py::parse_inbound` and adjust the `pytest.raises` accordingly — it must reject.

### FILL IN checklist
- [ ] `test_value_refined_is_internal_only` — exception type matches `parse_inbound`'s behaviour

---

## Acceptance Criteria

- [ ] All new fields exist with the listed defaults; old payloads/snapshots still validate (G7).
- [ ] `ValueRefined` is in `InboundEvent` but not in `ClientInbound`; `RefineValue` is in `IORequest`.
- [ ] Existing event/model tests pass unmodified.
- [ ] `ruff check` clean.

---

## Validation Commands

- `pytest packages/parrot-formdesigner/tests/formdesigner/test_audio_postprocess_models.py -q`
- `pytest packages/parrot-formdesigner/tests/formdesigner/test_audio_events.py -q`
- `pytest packages/parrot-formdesigner/tests/formdesigner/test_audio_models.py -q`
- `pytest packages/parrot-formdesigner/tests/formdesigner/test_voice_schema_models.py -q`

---

## Test Specification

See the CREATE block above.

---

## Agent Instructions

1. Work in the feature worktree: `python -m scripts.sdd.ensure_worktree --slug audio-form-voice-postprocessors --feature-id FEAT-653`.
2. Read the spec; this task has no dependencies.
3. Verify the Codebase Contract before writing code.
4. Set this task `in-progress` in the index and commit only the index.
5. Implement from the blueprint; complete every `FILL IN`; never change a fixed name or path.
6. Run the Validation Commands with `PYTHONPATH=packages/parrot-formdesigner/src`.
7. Commit only the listed files; close with `scripts/sdd/close_task.sh TASK-4248 audio-form-voice-postprocessors verified`; fill the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
