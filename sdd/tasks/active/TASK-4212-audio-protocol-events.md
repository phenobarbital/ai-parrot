# TASK-4212: Protocol v2 events: discriminated InboundEvent/Outbound unions, legacy v1 inbound, I/O request models

**Feature**: FEAT-649 — Audio Form Interaction Workflow
**Spec**: `sdd/specs/audio-form-interaction-workflow.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4211
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2 (events part), G1/G2, S6. `audio/events.py` is the frozen protocol v2
vocabulary between the pure engine (`AudioFormSession.handle(event) -> list[Outbound]`,
TASK-4225/4226) and the WebSocket adapter (TASK-4227). It has three families:
client inbound messages (v1 names preserved + review messages), adapter-internal inbound
events (I/O results fed back into the engine, `type` starts with `_`), and outbound items
(wire messages the adapter encodes + I/O requests the adapter performs).
The docs task (TASK-4235) asserts every `type` literal defined here appears in the docs.

---

## Scope

- Create `audio/events.py` with: `Phase` re-export; client inbound models; adapter-internal
  inbound events; `InboundEvent` / `ClientInbound` discriminated unions; wire message models;
  I/O request models; `Outbound` union; `parse_inbound()`; `is_io_request()`; `UnknownMessageType`.
- v2 client inbound models use `extra="forbid"`; v1 parsing (`protocol_version` < 2) drops
  unknown keys before validation (today's handler ignores them, `api/audio_ws.py:349-394`).
- Write `test_events_discriminated_union_and_forbid` and `test_legacy_inbound_ignores_unknown_keys`.

**NOT in scope**: engine logic (TASK-4225/4226); WS encoding/decoding and binary frames
(TASK-4227); documentation (TASK-4235). Do not modify `audio/models.py` or `audio/__init__.py`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/audio/events.py` | CREATE | Protocol v2 event/outbound models + parser |
| `packages/parrot-formdesigner/tests/formdesigner/test_audio_events.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.

### Verified Imports
```python
import typing
from typing import Annotated, Any, Literal, Union
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter
from .models import NarrationPlan, OptionMatch, Phase, ReviewItemData, UiCue   # created by TASK-4211 (audio/models.py)
from ..core.voice import HandsFreeConfig                                       # created by TASK-4209 (core/voice.py)
from ..core.llm_validation import PlausibilityReport, PlausibilityVerdict      # created by TASK-4209 (core/llm_validation.py)
```

### Existing Signatures to Use
```python
# api/audio_ws.py — v1 inbound message types (dispatcher dict, lines 368-379)
"start_session", "answer_text", "answer_selection", "answer_payload", "confirm_answer",
"skip_question", "go_back", "repeat_question", "end_session", "ping"
# v1 inbound payload keys actually read:
#   start_session: form_uid, locale (:449-450) + tts_backend, tts_voice, tts_mime_format, auto_advance,
#                  enumerate_options, stt_confirm_threshold (_build_session_config :413-421)
#   answer_text: field_id, value (:549-550) ; answer_selection: field_id, value | values (:575-597)
#   answer_payload: field_id, value (:626-629) ; confirm_answer: field_id, confirmed (:659, :669)
#   go_back: to_index (:882)
# api/audio_ws.py — v1 outbound shapes (keys preserved for v1 clients)
{"type": "session_started", "session_id", "total_questions", "title"}                     # :525
{"type": "question", "index", "field_id", "label", "required", "field_type", "voice_mode",
 "render_mode", "sensitive", "description"?, "audio"? (base64), "options"?, "fallback_html"?}  # :1216-1231
{"type": "transcription", "field_id", "text", "confidence"}                               # :784
{"type": "confirm_request", "field_id", "transcript", "confidence"}                       # :812
{"type": "answer_rejected", "field_id", "error"}                                          # :859
{"type": "answer_accepted", "field_id", "source", "value"? (omitted when sensitive)}       # :1059-1065
{"type": "session_ended", "session_id"}  # :934   {"type": "pong"}  # :947
{"type": "form_complete", "submission_id", "answers"}  # :1158   {"type": "error", "code", "message"}  # :1465
```

### Does NOT Exist
- ~~`audio/events.py`~~ — created here.
- Messages ~~`audio_segment`, `plan_updated`, `section_enter`, `question_skipped`, `answer_cleared`, `review_start/item/prompt/confirm/edit`, `plausibility_result`, `command_ack`, `session_resumed`, `validation_errors`~~ — new in this task.
- ~~`PlanDelta`~~ (TASK-4217), ~~`SubmitOutcome`~~ (TASK-4222), ~~`AudioSnapshot`~~ (TASK-4219) — do NOT import them; the events carry them as `dict[str, Any]` (decision below).
- ~~`Phase` defined in events.py~~ — it lives in `audio/models.py`; only re-export it.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/parrot-formdesigner/src/parrot_formdesigner/audio/events.py", "action": "CREATE"},
    {"path": "packages/parrot-formdesigner/tests/formdesigner/test_audio_events.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/api/audio_ws.py#AudioFormWSHandler"
  ]
}
```

---

## Implementation Notes

### Key Decisions (binding)
- **Payloads of types owned by later tasks are plain dicts**: `PlanReady.delta` (a dumped `PlanDelta`),
  `SubmitDone.outcome` (a dumped `SubmitOutcome`), `SaveSnapshot.snapshot` (a dumped `AudioSnapshot`).
  This keeps `events.py` dependency-free of TASK-4217/4219/4222; consumers call `Model.model_validate(...)`.
- **Engine ⇄ planner**: the planner's `replan` is async, so the engine emits `Replan` (I/O request) and
  receives `PlanReady` (spec §3 M5 note).
- **Binary frames**: the adapter wraps a received audio frame as `AudioReceived`; the engine answers with
  `Transcribe` and keeps the bytes for a later `StoreBlob`.
- **Adapter-internal events** (`type` starting with `_`) are never parseable from the wire:
  `parse_inbound()` only accepts `ClientInbound` types → `UnknownMessageType` otherwise.
- **v1 vs v2**: `parse_inbound(data, protocol_version=1)` drops keys not in the model before validating
  (S6); `protocol_version >= 2` validates strictly (`extra="forbid"`).
- `GoBack` carries both `to_field_id` (v2) and `to_index` (v1).
- `AnswerRejected` keeps v1 `error` and adds `code`.
- Wire models serialise with `to_wire()` = `model_dump(mode="json", exclude_none=True)` so absent
  optional keys are omitted exactly like the v1 handler.

### Key Constraints
- Every `type` literal is unique across all unions (test).
- No I/O, no logging needed; pure Pydantic.

---

## Implementation Blueprint

### Steps (in order)
1. Write the client inbound block — *why*: v1 names must parse first; the v1 compat test depends on it.
2. Write the adapter-internal events and the `InboundEvent` union.
3. Write wire messages, I/O requests and the `Outbound` union.
4. Write `parse_inbound` / `is_io_request`, then the tests.

### `packages/parrot-formdesigner/src/parrot_formdesigner/audio/events.py` (CREATE — part 1: client inbound)
```python
"""Audio form protocol v2 events (FEAT-649).

Client inbound messages, adapter-internal events, wire messages and I/O
requests exchanged between ``AudioFormSession`` (engine) and the WS adapter.
"""

from __future__ import annotations

import typing
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from ..core.llm_validation import PlausibilityReport, PlausibilityVerdict
from ..core.voice import HandsFreeConfig
from .models import NarrationPlan, OptionMatch, Phase, ReviewItemData, UiCue

__all__ = ["Phase"]  # FILL IN: extend with every public class/function defined below — bounded by test_events (imports)


class UnknownMessageType(ValueError):
    """Raised by parse_inbound for an unknown or internal message type."""


class _Inbound(BaseModel):
    model_config = ConfigDict(extra="forbid")


class StartSession(_Inbound):
    type: Literal["start_session"]
    form_uid: str
    locale: str = "en"
    protocol_version: int = 1
    prefetch: bool = True
    resume_session_id: str | None = None
    stt_confirm_threshold: float | None = None
    # v1 session-config keys (api/audio_ws.py:413-421)
    tts_backend: Literal["supertonic", "google"] | None = None
    tts_voice: str | None = None
    tts_mime_format: str | None = None
    auto_advance: bool | None = None
    enumerate_options: bool | None = None


class AnswerText(_Inbound):
    type: Literal["answer_text"]
    field_id: str
    value: str = ""


class AnswerSelection(_Inbound):
    type: Literal["answer_selection"]
    field_id: str
    value: Any = None
    values: list[Any] | None = None


class AnswerPayload(_Inbound):
    type: Literal["answer_payload"]
    field_id: str
    value: Any = None


class ConfirmAnswer(_Inbound):
    type: Literal["confirm_answer"]
    field_id: str = ""
    confirmed: bool = False


class SkipQuestion(_Inbound):
    type: Literal["skip_question"]
    field_id: str | None = None


class GoBack(_Inbound):
    type: Literal["go_back"]
    to_field_id: str | None = None
    to_index: int | None = None  # v1


class RepeatQuestion(_Inbound):
    type: Literal["repeat_question"]


class EndSession(_Inbound):
    type: Literal["end_session"]


class Ping(_Inbound):
    type: Literal["ping"]


class ReviewConfirm(_Inbound):
    type: Literal["review_confirm"]
    confirmed: bool


class ReviewEdit(_Inbound):
    type: Literal["review_edit"]
    field_id: str
```

### `audio/events.py` (CREATE — part 2: adapter-internal events + inbound unions)
```python
class AudioReceived(_Inbound):
    type: Literal["_audio"]
    audio: bytes
    mime: str | None = None


class TranscriptReady(_Inbound):
    type: Literal["_transcript"]
    field_id: str
    text: str
    language: str | None = None
    confidence: float | None = None
    audio_mime: str
    audio_bytes_len: int
    duration_ms: int | None = None


class PlanReady(_Inbound):
    type: Literal["_plan_ready"]
    plan: list[str]
    delta: dict[str, Any]  # dumped audio.planner.PlanDelta (TASK-4217)


class BlobStored(_Inbound):
    type: Literal["_blob_stored"]
    field_id: str
    blob_ref: str
    version: int


class SnapshotSaved(_Inbound):
    type: Literal["_snapshot_saved"]
    revision: int


class PlausibilityDone(_Inbound):
    type: Literal["_plausibility_done"]
    report: PlausibilityReport


class SubmitDone(_Inbound):
    type: Literal["_submit_done"]
    outcome: dict[str, Any]  # dumped services.submission_pipeline.SubmitOutcome (TASK-4222)


class IOFailed(_Inbound):
    type: Literal["_io_failed"]
    request: str  # the failed I/O request's type literal
    code: str
    detail: str | None = None


_CLIENT_TYPES = (StartSession, AnswerText, AnswerSelection, AnswerPayload, ConfirmAnswer, SkipQuestion,
                 GoBack, RepeatQuestion, EndSession, Ping, ReviewConfirm, ReviewEdit)
ClientInbound = Annotated[Union[_CLIENT_TYPES], Field(discriminator="type")]  # FILL IN: spell the Union members explicitly if the tuple form fails type-checking — bounded by pydantic v2 discriminated unions
InboundEvent = Annotated[
    Union[StartSession, AnswerText, AnswerSelection, AnswerPayload, ConfirmAnswer, SkipQuestion, GoBack,
          RepeatQuestion, EndSession, Ping, ReviewConfirm, ReviewEdit, AudioReceived, TranscriptReady,
          PlanReady, BlobStored, SnapshotSaved, PlausibilityDone, SubmitDone, IOFailed],
    Field(discriminator="type"),
]
_CLIENT_BY_TYPE: dict[str, type[_Inbound]] = {typing.get_args(m.model_fields["type"].annotation)[0]: m for m in _CLIENT_TYPES}
_CLIENT_ADAPTER: TypeAdapter = TypeAdapter(ClientInbound)
```

### `audio/events.py` (CREATE — part 3: wire messages)
```python
class _Wire(BaseModel):
    def to_wire(self) -> dict[str, Any]:
        """JSON-ready dict; absent optionals omitted (v1 handler parity)."""
        return self.model_dump(mode="json", exclude_none=True)


class SessionStarted(_Wire):
    type: Literal["session_started"] = "session_started"
    session_id: str
    total_questions: int
    title: str
    protocol_version: int = 1
    hands_free: HandsFreeConfig | None = None
    max_recording_seconds: int | None = None
    prefetch_count: int | None = None


class AudioSegment(_Wire):  # header; the adapter sends the bytes as the next binary frame
    type: Literal["audio_segment"] = "audio_segment"
    key: str
    mime: str
    kind: str  # "question" | "hint" | "options" | "system" | "review"
    text: str


class Question(_Wire):
    type: Literal["question"] = "question"
    index: int
    field_id: str
    label: str
    required: bool
    field_type: str
    voice_mode: str
    render_mode: str
    sensitive: bool
    description: str | None = None
    audio: str | None = None  # base64 — only v1 or prefetch=False
    options: list[dict[str, Any]] | None = None
    fallback_html: str | None = None
    hint: str | None = None
    section_uid: str | None = None
    ui_cue: UiCue | None = None
    answer_modes: list[str] | None = None
    narration: NarrationPlan | None = None


class Transcription(_Wire):
    type: Literal["transcription"] = "transcription"
    field_id: str
    text: str
    confidence: float | None = None


class ConfirmRequest(_Wire):
    type: Literal["confirm_request"] = "confirm_request"
    field_id: str
    transcript: str
    confidence: float | None = None
    matched: OptionMatch | None = None
    alternatives: list[OptionMatch] | None = None


class AnswerAccepted(_Wire):
    type: Literal["answer_accepted"] = "answer_accepted"
    field_id: str
    source: str
    value: Any = None  # omitted for sensitive fields
    matched: OptionMatch | None = None
    blob_ref: str | None = None


class AnswerRejected(_Wire):
    type: Literal["answer_rejected"] = "answer_rejected"
    field_id: str
    error: str
    code: str | None = None


class CommandAck(_Wire):
    type: Literal["command_ack"] = "command_ack"
    command: str
    field_id: str | None = None
```

### `audio/events.py` (CREATE — part 4: remaining wire messages)
```python
class PlanUpdated(_Wire):
    type: Literal["plan_updated"] = "plan_updated"
    order: list[str]
    hidden: list[str] = Field(default_factory=list)
    cleared: list[str] = Field(default_factory=list)
    required_changed: dict[str, bool] = Field(default_factory=dict)
    hidden_by_cap: list[str] = Field(default_factory=list)


class SectionEnter(_Wire):
    type: Literal["section_enter"] = "section_enter"
    section_uid: str
    title: str | None = None


class QuestionSkipped(_Wire):
    type: Literal["question_skipped"] = "question_skipped"
    field_id: str
    reason: str


class AnswerCleared(_Wire):
    type: Literal["answer_cleared"] = "answer_cleared"
    field_id: str


class ReviewStart(_Wire):
    type: Literal["review_start"] = "review_start"
    items: list[ReviewItemData]


class ReviewItem(_Wire):
    type: Literal["review_item"] = "review_item"
    item: ReviewItemData


class ReviewPrompt(_Wire):
    type: Literal["review_prompt"] = "review_prompt"
    text: str | None = None


class PlausibilityResult(_Wire):
    type: Literal["plausibility_result"] = "plausibility_result"
    status: Literal["ok", "skipped", "blocked"]
    items: dict[str, PlausibilityVerdict] = Field(default_factory=dict)
    reason: str | None = None


class ValidationErrors(_Wire):
    type: Literal["validation_errors"] = "validation_errors"
    errors: dict[str, list[str]]
    first_field_id: str | None = None


class SessionResumed(_Wire):
    type: Literal["session_resumed"] = "session_resumed"
    session_id: str
    phase: Phase
    cursor: str | None = None
    answered: list[str] = Field(default_factory=list)


class FormComplete(_Wire):
    type: Literal["form_complete"] = "form_complete"
    submission_id: str
    answers: dict[str, Any] = Field(default_factory=dict)  # v1; sensitive values masked (S8)
    stored_in: str | None = None
    plausibility_summary: dict[str, Any] | None = None


class SessionEnded(_Wire):
    type: Literal["session_ended"] = "session_ended"
    session_id: str


class Error(_Wire):
    type: Literal["error"] = "error"
    code: str
    message: str


class Pong(_Wire):
    type: Literal["pong"] = "pong"
```

### `audio/events.py` (CREATE — part 5: I/O requests, unions, helpers)
```python
class _IORequest(BaseModel):
    """Marker base: the adapter performs these and feeds a *Done / IOFailed event back."""


class Synthesize(_IORequest):
    type: Literal["_synthesize"] = "_synthesize"
    keys: list[str]
    texts: dict[str, str]


class Transcribe(_IORequest):
    type: Literal["_transcribe"] = "_transcribe"
    field_id: str
    audio: bytes
    mime: str | None = None


class StoreBlob(_IORequest):
    type: Literal["_store_blob"] = "_store_blob"
    field_id: str
    audio: bytes
    mime: str
    version: int


class DeleteBlob(_IORequest):
    type: Literal["_delete_blob"] = "_delete_blob"
    blob_ref: str


class SaveSnapshot(_IORequest):
    type: Literal["_save_snapshot"] = "_save_snapshot"
    snapshot: dict[str, Any]  # dumped audio.session_store.AudioSnapshot (TASK-4219)


class RunPlausibility(_IORequest):
    type: Literal["_run_plausibility"] = "_run_plausibility"
    fields: set[str] | None = None  # None = every eligible field; never contains sensitive ones (S8)


class Submit(_IORequest):
    type: Literal["_submit"] = "_submit"
    data: dict[str, Any]
    context: dict[str, Any] | None = None


class Replan(_IORequest):
    type: Literal["_replan"] = "_replan"


WireMessage = Union[SessionStarted, AudioSegment, Question, Transcription, ConfirmRequest, AnswerAccepted,
                    AnswerRejected, CommandAck, PlanUpdated, SectionEnter, QuestionSkipped, AnswerCleared,
                    ReviewStart, ReviewItem, ReviewPrompt, PlausibilityResult, ValidationErrors,
                    SessionResumed, FormComplete, SessionEnded, Error, Pong]
IORequest = Union[Synthesize, Transcribe, StoreBlob, DeleteBlob, SaveSnapshot, RunPlausibility, Submit, Replan]
Outbound = Union[WireMessage, IORequest]


def is_io_request(item: object) -> bool:
    """True when ``item`` is an I/O request the adapter must perform."""
    return isinstance(item, _IORequest)


def parse_inbound(data: dict[str, Any], *, protocol_version: int = 1) -> BaseModel:
    """Parse one client JSON message.

    v1 (protocol_version < 2): unknown keys are dropped before validation (S6).
    v2: strict (``extra="forbid"``). Internal ``_*`` types are never accepted.

    Raises:
        UnknownMessageType: unknown or internal ``type``.
        pydantic.ValidationError: malformed payload.
    """
    msg_type = data.get("type")
    model = _CLIENT_BY_TYPE.get(msg_type) if isinstance(msg_type, str) else None
    if model is None:
        raise UnknownMessageType(f"Unknown message type: {msg_type!r}")
    if protocol_version >= 2:
        return _CLIENT_ADAPTER.validate_python(data)
    # FILL IN: keep only keys in model.model_fields, then model.model_validate(filtered) — bounded by S6 / test_legacy_inbound_ignores_unknown_keys
    raise NotImplementedError
```
**Why this shape**: names, keys and the `extra` policies are frozen by spec §3 M2 and the handoff;
`kind` on `AudioSegment` stays a `str` so later kinds do not break v2 clients.

### FILL IN checklist
- [ ] `__all__` completed with every public name
- [ ] `ClientInbound` union spelled out explicitly if the tuple form is rejected by pydantic/ruff
- [ ] `parse_inbound` v1 branch — key filtering; bounded by S6
- [ ] test bodies marked `FILL IN`

---

## Acceptance Criteria

- [ ] Every `type` literal across inbound events, wire messages and I/O requests is unique.
- [ ] v2: `parse_inbound({"type": "answer_text", "field_id": "a", "value": "x", "extra": 1}, protocol_version=2)` raises `ValidationError`.
- [ ] v1: the same message with `protocol_version=1` parses and drops `extra`.
- [ ] Every v1 message name (`start_session`, `answer_text`, `answer_selection`, `answer_payload`, `confirm_answer`, `skip_question`, `go_back`, `repeat_question`, `end_session`, `ping`) parses in both modes with its v1 payload keys.
- [ ] `parse_inbound({"type": "_transcript", ...})` raises `UnknownMessageType`.
- [ ] `Question(...).to_wire()` omits `audio`/`description`/`options` when `None` (v1 parity).
- [ ] `from parrot_formdesigner.audio.events import Phase` works and is `audio.models.Phase`.
- [ ] `ruff check` clean.

---

## Validation Commands

- `pytest packages/parrot-formdesigner/tests/formdesigner/test_audio_events.py -q`

---

## Test Specification

```python
# packages/parrot-formdesigner/tests/formdesigner/test_audio_events.py
import typing

import pytest
from pydantic import ValidationError

from parrot_formdesigner.audio import events as ev
from parrot_formdesigner.audio.models import Phase as ModelsPhase


def _all_type_literals() -> list[str]:
    models = []
    for union in (ev.InboundEvent, ev.WireMessage, ev.IORequest):
        args = typing.get_args(union)
        members = typing.get_args(args[0]) if typing.get_origin(union) is typing.Annotated else args
        models.extend(members)
    return [typing.get_args(m.model_fields["type"].annotation)[0] for m in models]


class TestEventsDiscriminatedUnionAndForbid:
    def test_type_literals_unique(self):
        literals = _all_type_literals()
        assert len(literals) == len(set(literals))

    def test_v2_rejects_unknown_key(self):
        with pytest.raises(ValidationError):
            ev.parse_inbound({"type": "answer_text", "field_id": "a", "value": "x", "extra": 1}, protocol_version=2)

    def test_internal_types_not_parseable(self):
        with pytest.raises(ev.UnknownMessageType):
            ev.parse_inbound({"type": "_transcript", "field_id": "a", "text": "x", "audio_mime": "a", "audio_bytes_len": 1})

    def test_v1_message_names_parse(self):
        samples = [
            {"type": "start_session", "form_uid": "u", "locale": "es", "tts_backend": "google"},
            {"type": "answer_text", "field_id": "a", "value": "x"},
            {"type": "answer_selection", "field_id": "a", "values": ["x", "y"]},
            {"type": "answer_payload", "field_id": "a", "value": {"k": 1}},
            {"type": "confirm_answer", "field_id": "a", "confirmed": True},
            {"type": "skip_question"}, {"type": "go_back", "to_index": 0}, {"type": "repeat_question"},
            {"type": "end_session"}, {"type": "ping"},
        ]
        for sample in samples:
            for version in (1, 2):
                assert ev.parse_inbound(sample, protocol_version=version).type == sample["type"]

    def test_question_to_wire_omits_none(self):
        q = ev.Question(index=0, field_id="a", label="A", required=True, field_type="text",
                        voice_mode="voice", render_mode="voice", sensitive=False)
        wire = q.to_wire()
        assert wire["type"] == "question" and "audio" not in wire and "options" not in wire

    def test_phase_reexport(self):
        assert ev.Phase is ModelsPhase

    def test_io_request_marker(self):
        assert ev.is_io_request(ev.Replan()) and not ev.is_io_request(ev.Pong())


class TestLegacyInboundIgnoresUnknownKeys:
    def test_v1_start_session_extra_keys_accepted(self):
        msg = ev.parse_inbound({"type": "start_session", "form_uid": "u", "client": "old-app", "foo": 1}, protocol_version=1)
        assert msg.form_uid == "u"

    def test_v2_start_session_extra_keys_rejected(self):
        # FILL IN: same payload with protocol_version=2 raises ValidationError
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
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4212 audio-form-interaction-workflow verified`
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
