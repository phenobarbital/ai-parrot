# TASK-4225: AudioFormSession engine part 1: dispatch, start/plan, question turns, answers, confirm, skip/back/repeat, commands

**Feature**: FEAT-649 — Audio Form Interaction Workflow
**Spec**: `sdd/specs/audio-form-interaction-workflow.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-4212, TASK-4214, TASK-4215, TASK-4216, TASK-4217
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 10 — the pure, transport-agnostic audio session engine
(`audio/engine.py`, goal G1). `AudioFormSession.handle(event) -> list[Outbound]`
owns the phase state machine and **never awaits**: every piece of I/O
(re-plan, synthesis, transcription, blob store/delete, snapshot, plausibility,
submit) is expressed as an `Outbound` I/O request that the WebSocket adapter
(TASK-4227) performs and answers with a `*_Done` / `PlanReady` / `IOFailed`
event.

The engine is split in two tasks so the hot path can land first:

- **This task (part 1)** — constructor, dispatch, `CONNECTED → PLANNING →
  ASKING(cursor) → ACCEPTING → [CONFIRMING] → re-plan → …`, every answer kind
  (transcript, text, selection, payload), the low-confidence confirm gate,
  skip / back / repeat, hands-free commands, end/ping, and the
  plan-exhausted → `Submit` → `on_submit_done` tail.
- **TASK-4226 (part 2)** — PLAUSIBILITY / REVIEW / REVIEW_EDITING, the delta
  plausibility after `review_edit`, `return_to_review`, `snapshot()` /
  `from_snapshot()` resume and the sensitive-masking review invariants. It
  edits the same file and replaces the body of `_on_plan_exhausted()`.

In part 1, `_on_plan_exhausted()` always submits directly. That is the
**correct, final** behaviour for v1 clients (`protocol_version == 1`) and for
`cfg.review == "never"`. The existing FEAT-224/236 integration test
`test_full_text_session_completes` expects `answer_accepted` immediately
followed by `form_complete`. TASK-4226 adds the REVIEW branch for v2 clients only.

---

## Scope

- Create `audio/engine.py` with `EngineError` and `AudioFormSession`.
- Implement `handle()` as a pure dispatcher on `(state.phase, event.type)`.
  It never raises for client errors: it emits `Error(code, message)`, e.g.
  `SESSION_NOT_STARTED`, `WRONG_FIELD`, `NO_PENDING_ANSWER`,
  `FIELD_MISMATCH`, `INVALID_OPTION`, `UNKNOWN_EVENT`.
- Implement these phase handlers: `on_start`, `on_plan_ready`,
  `on_audio_frame`, `on_transcript`, `on_text`, `on_selection`,
  `on_payload`, `on_confirm`, `on_skip`, `on_back`, `on_repeat`,
  `on_end`, `on_ping`, `on_blob_stored`, `on_io_failed`,
  `on_submit_done`, plus the overridable hook `_on_plan_exhausted()`.
- Every accepted answer emits `AnswerAccepted` followed by `Replan`. The
  cursor advances only on `PlanReady`, never by `index += 1`.
- Answers for a field other than the current cursor are rejected with
  `WRONG_FIELD`. A re-answer of the same field bumps `AudioAnswer.version` (S6).
- Spoken answers on option fields store the matched option **value**, never
  the raw transcript (AC6). MULTI_SELECT is stored as a `list` (AC6, G5).
- Hands-free commands are classified via `classify_command()` **after** an
  exact option match is ruled out (exact option beats command, AC14). They are
  disabled when `cfg.commands == "off"` or the field's
  `FieldVoiceMeta.commands == "off"`. Each command emits `CommandAck(command)`
  plus the v1 effect.
- Write `test_audio_engine_turns.py`, including the **no-await AST test** (AC2).

**NOT in scope**: review / plausibility phases, `review_confirm` / `review_edit`,
`snapshot()` / `from_snapshot()` (TASK-4226); any I/O, aiohttp or
`ws.send_json` (TASK-4227); option matching / command / narration / planning
algorithms themselves (TASK-4215 / 4216 / 4214 / 4217 — call them, never
re-implement); `api/audio_ws.py`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/audio/engine.py` | CREATE | Pure state machine, part 1 |
| `packages/parrot-formdesigner/tests/formdesigner/test_audio_engine_turns.py` | CREATE | Scripted-event tests + no-await AST test |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_formdesigner.core.schema import FormField, FormSchema                       # core/schema.py:65, :401
from parrot_formdesigner.core.types import FieldType                                     # core/types.py:16 (NUMBER :21, INTEGER :22, BOOLEAN :23, SELECT :27, MULTI_SELECT :28, NPS :47, LIKERT :48, RANKING :49)
from parrot_formdesigner.audio.models import (                                           # audio/models.py
    AudioAnswer, AudioFormManifest, AudioQuestion, AudioSessionState, VoiceMode,         # :153, :128, :72, :179, :18
)
```

#### Provided by dependency tasks (do NOT exist yet — verify names in the landed files first)
```python
# TASK-4209 (core/voice.py, core/llm_validation.py)
from parrot_formdesigner.core.voice import FieldVoiceMeta, VoiceFormConfig, field_voice_meta, is_sensitive
from parrot_formdesigner.core.llm_validation import LLMValidationConfig
# TASK-4211 (audio/models.py) — Phase lives here (plan _decisions), re-exported by audio/events.py
from parrot_formdesigner.audio.models import Phase, OptionMatch
# TASK-4212 (audio/events.py) — protocol v2 unions + adapter-internal events + I/O requests
from parrot_formdesigner.audio.events import (
    InboundEvent, Outbound,
    StartSession, AnswerText, AnswerSelection, AnswerPayload, ConfirmAnswer, SkipQuestion, GoBack,
    RepeatQuestion, EndSession, Ping, TranscriptReady, BlobStored, SubmitDone, IOFailed,
    SessionStarted, Question, Transcription, ConfirmRequest, AnswerAccepted, AnswerRejected, CommandAck,
    PlanUpdated, SectionEnter, QuestionSkipped, AnswerCleared, ValidationErrors, FormComplete,
    SessionEnded, Error, Pong,
    Synthesize, Transcribe, StoreBlob, DeleteBlob, Submit,
    Replan, PlanReady,       # spec §3 M5 note: engine emits Replan, receives PlanReady
    AudioFrame,              # adapter wraps a binary WS frame as an event (spec M2 "adapter wraps binary frames")
)
# TASK-4213 (audio/narration/lexicon.py)
from parrot_formdesigner.audio.narration.lexicon import Lexicon, normalize
# TASK-4214 (audio/narration/engine.py)
from parrot_formdesigner.audio.narration.engine import Narrator
# TASK-4215 (audio/option_matcher.py)
from parrot_formdesigner.audio.option_matcher import MatchOutcome, match_option
# TASK-4216 (audio/commands.py)
from parrot_formdesigner.audio.commands import VoiceCommand, classify_command
# TASK-4217 (audio/planner.py)
from parrot_formdesigner.audio.planner import PlanDelta, QuestionPlanner
```
**Dependency-name check (mandatory first step)**: `grep -n '^class ' audio/events.py`.
The spec fixes the wire `type` literals but not every adapter-internal class
name: `Replan`, `PlanReady`, `AudioFrame`, `BlobStored`, `SubmitDone` and
`IOFailed`. If TASK-4212 named one of them differently, use the landed
name, keep the semantics described here, and record the mapping in the
Completion Note. Never add a model to `events.py` from this task. If a needed
event is missing, stop and report.

### Existing Signatures to Use
```python
# audio/models.py:153 (TASK-4211 widens value to Any and adds version, matched, blob_ref, …)
class AudioAnswer(BaseModel):
    field_id: str; field_uid: Optional[uuid.UUID] = None; value: str
    source: Literal["text", "speech", "selection"] = "text"; confidence: Optional[float] = None; raw_transcript: Optional[str] = None
# audio/models.py:179 (TASK-4211 adds phase, cursor, history, plan, return_to_review, review_cursor, resolution, tenant,
#                     locale, submission_id, protocol_version, plausibility, flagged)
class AudioSessionState(BaseModel):
    session_id: str; form_uid: str; user_id: str; current_index: int = 0
    answers: dict[str, AudioAnswer]; manifest: Optional[AudioFormManifest] = None; completed: bool = False
    config: Optional[AudioSessionConfig] = None; pending: Optional[AudioAnswer] = None
# audio/models.py:72 — AudioQuestion: index, field_id, field_uid, field_type: str, label, description, required, options: list[dict] | None,
#                      voice_mode: VoiceMode, render_mode, sensitive (TASK-4211 adds hint, prompt, narration, ui_cue, answer_modes, voice_meta, llm_validation)
# audio/models.py:128 — AudioFormManifest: form_uid, title, total_questions, questions: list[AudioQuestion], ws_endpoint, locale
# Current v1 behaviour this engine must reproduce (api/audio_ws.py):
#   answer_selection multi → validated against question.options values (:582-596) — now stored as list, not ",".join (:595)
#   confirm_answer {field_id, confirmed}: NO_PENDING_ANSWER (:654), FIELD_MISMATCH (:661), false → re-send same question (:681)
#   skip on required → answer_rejected (:859); go_back (:868); repeat (:901); end_session → session_ended (:934); ping → pong (:947)
#   sensitive transcript masked "[hidden]" in transcription / ack (_SENSITIVE_MASK :63)
```

### Does NOT Exist
- ~~`audio/engine.py`~~, ~~`AudioFormSession`~~, ~~`EngineError`~~ — created here.
- ~~`AudioSessionState.phase` / `.cursor` / `.plan`~~ until TASK-4211 lands.
- ~~`RuleEvaluator` call inside the engine~~ — the planner's `replan` is async; the engine only emits `Replan`.
- ~~`asyncio`, `aiohttp`, `ws.send_json`~~ in `audio/engine.py` — forbidden (AC2).
- ~~review / plausibility handlers~~ in this task — TASK-4226.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/parrot-formdesigner/src/parrot_formdesigner/audio/engine.py", "action": "CREATE"},
    {"path": "packages/parrot-formdesigner/tests/formdesigner/test_audio_engine_turns.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py#FormSchema",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py#FormField",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/core/types.py#FieldType",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/audio/models.py#AudioAnswer",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/audio/models.py#AudioFormManifest",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/audio/models.py#AudioQuestion",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/audio/models.py#AudioSessionState",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/audio/models.py#VoiceMode"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- **No `await`, no `async def`, no `asyncio` import** in `audio/engine.py`. The AST test enforces it.
- `handle()` mutates `self.state` and returns a list. Order matters: the
  adapter performs the outbound items in list order.
- **Prefetch ordering (AC3)**: the first `on_plan_ready` returns
  `[SessionStarted, Synthesize(sys + every planned question), Question(first)]`.
  For a v2 client the adapter turns `Synthesize` into `audio_segment` frames
  before it sends the `question`.
- **v1 compatibility**: when `state.protocol_version == 1` the outbound
  wire models must carry the v1 fields (`total_questions`, `title`,
  `index`, `voice_mode`, …). The adapter attaches base64 `audio` itself. The
  engine never builds base64.
- Narration text always comes from `Narrator` (G4). The engine never
  formats sentences itself.
- `is_sensitive(field)` answers show `"[hidden]"` in `Transcription`,
  `ConfirmRequest` and `AnswerAccepted` echo text, and must never appear in a
  log line.
- Use `logging.getLogger(__name__)` as `self.logger`. Log the phase, event
  type and field id. Never log answer values.

### References in Codebase
- `api/audio_ws.py:539-937` — the v1 handlers whose observable behaviour is reproduced.
- Spec §3 M10 skeleton and invariants; §2 Overview state machine.

---

## Implementation Blueprint

### Steps (in order)
1. Run the dependency-name check above — *why*: some adapter-internal event
   class names are not fixed by the spec.
2. Write the module skeleton and the dispatch table (block 1) — *why*: one
   table makes the "never raises for client errors" rule easy to audit.
3. Implement `on_start` / `on_plan_ready` (block 2) — *why*: every other
   handler depends on `state.cursor`, and only `PlanReady` sets it.
4. Implement the answer path (block 3) — *why*: there is exactly one
   acceptance funnel (`_accept`), so `Replan`, the version bump and
   `StoreBlob` can never be forgotten by a single answer kind.
5. Implement navigation, commands and the submit tail (block 4).
6. Write the tests, AST test first — *why*: it guards AC2 for TASK-4226 too.

### `packages/parrot-formdesigner/src/parrot_formdesigner/audio/engine.py` (CREATE) — block 1: skeleton + dispatch
```python
"""Pure audio form session engine (FEAT-649, spec §3 Module 10).

``AudioFormSession.handle(event) -> list[Outbound]`` is a synchronous state
machine: it never awaits and performs no I/O. I/O is requested through
``Outbound`` request models that the WebSocket adapter performs and answers
with ``*_Done`` / ``PlanReady`` / ``IOFailed`` events.
"""
from __future__ import annotations

import logging
from typing import Any, Callable

from ..core.llm_validation import LLMValidationConfig
from ..core.schema import FormField, FormSchema
from ..core.types import FieldType
from ..core.voice import VoiceFormConfig, field_voice_meta, is_sensitive
from .commands import VoiceCommand, classify_command
from .events import (  # names verified against the landed audio/events.py (TASK-4212)
    AnswerAccepted, AnswerPayload, AnswerRejected, AnswerSelection, AnswerText, AudioFrame, BlobStored,
    CommandAck, ConfirmAnswer, ConfirmRequest, EndSession, Error, FormComplete, GoBack, InboundEvent,
    IOFailed, Outbound, Ping, PlanReady, PlanUpdated, Pong, Question, QuestionSkipped, RepeatQuestion,
    Replan, SectionEnter, SessionEnded, SessionStarted, SkipQuestion, StartSession, StoreBlob, Submit,
    SubmitDone, Synthesize, Transcribe, Transcription, TranscriptReady, ValidationErrors, AnswerCleared,
    DeleteBlob,
)
from .models import AudioAnswer, AudioFormManifest, AudioQuestion, AudioSessionState, OptionMatch, Phase
from .narration.engine import Narrator
from .narration.lexicon import Lexicon
from .option_matcher import match_option
from .planner import QuestionPlanner

_SENSITIVE_MASK = "[hidden]"
_OPTION_TYPES = frozenset({FieldType.SELECT, FieldType.MULTI_SELECT, FieldType.BOOLEAN,
                           FieldType.LIKERT, FieldType.NPS, FieldType.RANKING})


class EngineError(Exception):
    """Programming error inside the engine (never raised for client input)."""

    def __init__(self, code: str, message: str = "") -> None:
        super().__init__(message or code)
        self.code = code


class AudioFormSession:
    """Pure audio form state machine — see module docstring."""

    def __init__(self, *, form: FormSchema, manifest: AudioFormManifest, cfg: VoiceFormConfig, narrator: Narrator,
                 lexicon: Lexicon, state: AudioSessionState, llm_cfg: LLMValidationConfig | None) -> None:
        self.form = form
        self.manifest = manifest
        self.cfg = cfg
        self.narrator = narrator
        self.lexicon = lexicon
        self.state = state
        self.llm_cfg = llm_cfg
        self.planner = QuestionPlanner(form, manifest, cfg)   # adapter awaits planner.replan() on Replan
        self.logger = logging.getLogger(__name__)
        self._questions: dict[str, AudioQuestion] = {q.field_id: q for q in manifest.questions}
        self._fields: dict[str, FormField] = {f.field_id: f for f in form.iter_fields_recursive()}
        self._last_audio: tuple[str, bytes, str] | None = None   # (field_id, bytes, mime) — never snapshotted
        self._handlers: dict[str, Callable[[Any], list[Outbound]]] = {
            "start_session": self.on_start, "_plan_ready": self.on_plan_ready, "_audio_frame": self.on_audio_frame,
            "_transcript": self.on_transcript, "answer_text": self.on_text, "answer_selection": self.on_selection,
            "answer_payload": self.on_payload, "confirm_answer": self.on_confirm, "skip_question": self.on_skip,
            "go_back": self.on_back, "repeat_question": self.on_repeat, "end_session": self.on_end,
            "ping": self.on_ping, "_blob_stored": self.on_blob_stored, "_io_failed": self.on_io_failed,
            "_submit_done": self.on_submit_done,
        }
        # FILL IN: the "_plan_ready" / "_audio_frame" / "_blob_stored" / "_io_failed" / "_submit_done" keys must equal
        #          the `type` literals TASK-4212 gave those models — bounded by the dependency-name check.

    def handle(self, event: InboundEvent) -> list[Outbound]:
        """Dispatch one event; mutate state; return wire messages + I/O requests. Never awaits."""
        handler = self._handlers.get(event.type)
        if handler is None:
            return [Error(code="UNKNOWN_EVENT", message=f"Unhandled event type: {event.type}")]
        if self.state.phase in (Phase.IDLE,) and event.type not in ("start_session", "ping"):
            return [Error(code="SESSION_NOT_STARTED", message="Call start_session first")]
        self.logger.debug("engine: phase=%s event=%s cursor=%s", self.state.phase, event.type, self.state.cursor)
        return handler(event)
```
**Why this shape**: the dispatch table is keyed by the wire/internal `type`
literal (the `InboundEvent` discriminator). TASK-4226 adds keys
(`review_confirm`, `review_edit`, `_plausibility_done`) to `self._handlers`
in `__init__` and never touches `handle()`. `planner` is public because the
adapter must `await self.planner.replan(...)` when it sees `Replan`. That
keeps the engine free of awaits.

### block 2: start + plan
```python
    # ---- start / plan --------------------------------------------------
    def on_start(self, ev: StartSession) -> list[Outbound]:
        """Record locale/protocol, enter PLANNING and request the first re-plan."""
        self.state.locale = ev.locale
        self.state.protocol_version = ev.protocol_version
        self.state.phase = Phase.PLANNING
        return [Replan()]

    def on_plan_ready(self, ev: PlanReady) -> list[Outbound]:
        """Adopt the new plan; emit plan deltas; ask the cursor question, or finish."""
        first = not self.state.plan
        self.state.plan = list(ev.order)
        out: list[Outbound] = []
        out.extend(self._delta_messages(ev.delta))
        cursor = self.planner.next_cursor(self.state.plan, self.state.answers)
        self.state.cursor = cursor
        if first:
            out.insert(0, SessionStarted(session_id=self.state.session_id, total_questions=len(self.state.plan),
                                         title=self.manifest.title))
            out.insert(1, self._synthesize_request(self.state.plan, include_system=True))
        if cursor is None:
            return out + self._on_plan_exhausted()
        self.state.phase = Phase.ASKING
        return out + [self._question(cursor)]

    def _delta_messages(self, delta: Any) -> list[Outbound]:
        """PlanUpdated / SectionEnter / QuestionSkipped / AnswerCleared(+DeleteBlob) for one PlanDelta."""
        # FILL IN: emit PlanUpdated(order, hidden, cleared, required_changed, hidden_by_cap) only when something changed;
        #          for every id in delta.cleared pop state.answers[id] and emit AnswerCleared + DeleteBlob(blob_ref) when it had
        #          a blob_ref; SectionEnter when delta.entered_section; auto-accept delta.computed as AudioAnswer(source="text")
        #          — bounded by AC7 (cascade_clear clears answers AND deletes blobs) and spec M5 PlanDelta fields.
        raise EngineError("UNIMPLEMENTED_DELTA")

    def _synthesize_request(self, field_ids: list[str], *, include_system: bool) -> Synthesize:
        """One Synthesize for the narration segments of ``field_ids`` (+ sys:* phrases on first plan)."""
        texts: dict[str, str] = dict(self.narrator.system_phrases()) if include_system else {}
        for fid in field_ids:
            q = self._questions.get(fid)
            if q is None or is_sensitive(self._fields[fid]):
                continue
            plan = self.narrator.plan_question(q, self.cfg, field_voice_meta(self._fields[fid], logger=self.logger))
            texts.update(plan.segments)
        return Synthesize(keys=list(texts), texts=texts)

    def _question(self, field_id: str) -> Question:
        """Build the Question wire message for ``field_id`` (v1 fields kept for protocol_version 1)."""
        # FILL IN: map AudioQuestion → Question (index derived from plan position, keep state.current_index in sync for v1,
        #          narration plan, hint, ui_cue, answer_modes, options incl. disabled, required = planner.effective_required)
        #          — bounded by AC3/AC4/AC5 and the Question fields TASK-4212 defined.
        raise EngineError("UNIMPLEMENTED_QUESTION")
```
**Why**: `SessionStarted` and the prefetch `Synthesize` are only inserted on
the first plan, which gives AC3 its ordering. Questions that appear after a
later re-plan are synthesised lazily: `_question()` must prepend a
`Synthesize` for that single field when its keys were not part of the first
batch (spec M6 / S7). The two `raise EngineError` lines are placeholders
that the FILL IN replaces. **None may remain in the committed file.**

### block 3: answer funnel
```python
    # ---- answers -------------------------------------------------------
    def on_audio_frame(self, ev: AudioFrame) -> list[Outbound]:
        """Stash the recording (never snapshotted) and request transcription for the cursor field."""
        if self.state.cursor is None:
            return [Error(code="SESSION_COMPLETE", message="All questions answered")]
        self._last_audio = (self.state.cursor, ev.audio, ev.mime)
        return [Transcribe(field_id=self.state.cursor, audio=ev.audio)]

    def on_transcript(self, ev: TranscriptReady) -> list[Outbound]:
        """Commands → option match → STT confidence gate → accept / confirm / reject."""
        if ev.field_id != self.state.cursor:
            return [Error(code="WRONG_FIELD", message=f"Answer for '{ev.field_id}' but cursor is '{self.state.cursor}'")]
        field = self._fields[ev.field_id]
        q = self._questions[ev.field_id]
        shown = _SENSITIVE_MASK if is_sensitive(field) else ev.text
        out: list[Outbound] = [Transcription(field_id=ev.field_id, text=shown, confidence=ev.confidence)]
        outcome = None
        if q.options:
            outcome = match_option(ev.text, q.options, field_type=field.field_type, lexicon=self.lexicon,
                                   threshold=self.cfg.option_match_threshold, confirm_floor=self.cfg.stt_confirm_threshold,
                                   stt_confidence=ev.confidence, multi=field.field_type == FieldType.MULTI_SELECT)
        exact = outcome is not None and outcome.status == "accepted" and outcome.match is not None \
            and outcome.match.method == "exact"
        if not exact and self._commands_enabled(field):
            cmd = classify_command(ev.text, lexicon=self.lexicon, phase=self.state.phase)
            if cmd is not None:
                return out + self._apply_command(cmd)
        # FILL IN: option field → accepted: value = match.value (MULTI_SELECT: [m.value for m in outcome.matches]) via
        #          self._accept(..., source="speech", matched=outcome.match); confirm → state.pending + phase CONFIRMING +
        #          ConfirmRequest (with alternatives); no_match → AnswerRejected(code="NO_MATCH") + narrator "no_match".
        #          Free field → confidence (None ⇒ 1.0) < cfg.stt_confirm_threshold → ConfirmRequest, else _accept.
        #          — bounded by AC6 (value never raw transcript), AC14, spec M4 thresholds.
        return out

    def _accept(self, field_id: str, value: Any, *, source: str, confidence: float | None = None,
                raw: str | None = None, matched: OptionMatch | None = None) -> list[Outbound]:
        """Single acceptance funnel: bump version, store, ack, StoreBlob for speech, then Replan."""
        prev = self.state.answers.get(field_id)
        version = (prev.version + 1) if prev is not None else 1
        self.state.answers[field_id] = AudioAnswer(field_id=field_id, field_uid=self._fields[field_id].field_uid,
                                                   value=value, source=source, confidence=confidence,
                                                   raw_transcript=raw, matched=matched, version=version)
        self.state.pending = None
        self.state.history.append(field_id)
        self.state.phase = Phase.ACCEPTING
        out: list[Outbound] = [AnswerAccepted(field_id=field_id, value=self._echo(field_id, value), matched=matched)]
        if source == "speech" and self.cfg.store_recordings and self._last_audio and self._last_audio[0] == field_id:
            _, audio, mime = self._last_audio
            out.append(StoreBlob(field_id=field_id, audio=audio, mime=mime))
        self._last_audio = None
        return out + [Replan()]

    def on_text(self, ev: AnswerText) -> list[Outbound]: ...        # FILL IN: cursor check → _accept(source="text")
    def on_selection(self, ev: AnswerSelection) -> list[Outbound]: ...  # FILL IN: v1 validation (:582-596), list for multi
    def on_payload(self, ev: AnswerPayload) -> list[Outbound]: ...  # FILL IN: cursor check → _accept(source="text")
    def on_confirm(self, ev: ConfirmAnswer) -> list[Outbound]: ...  # FILL IN: v1 :637-689 semantics on state.pending
    def on_blob_stored(self, ev: BlobStored) -> list[Outbound]: ... # FILL IN: set answers[field].blob_ref; return []
```
**Why**: `_accept` is the one place that bumps `version` (S6), sets
`history` (needed by `on_back`) and emits `Replan` (AC7 "after each accepted
answer"). The `...` bodies are FILL IN markers. Each must become a full
implementation that ends by calling `_accept` or returning
`[Error|AnswerRejected]`. `self._echo()` masks sensitive values with
`"[hidden]"`, matching `test_sensitive_value_not_echoed_in_ack`.

### block 4: navigation, commands, submit tail
```python
    # ---- navigation / commands / submit -------------------------------
    def on_skip(self, ev: SkipQuestion) -> list[Outbound]: ...      # FILL IN: required (planner.effective_required) → AnswerRejected; else QuestionSkipped + Replan
    def on_back(self, ev: GoBack) -> list[Outbound]: ...            # FILL IN: planner.previous(plan, history, ev.to_field_id) → cursor + Question
    def on_repeat(self, ev: RepeatQuestion) -> list[Outbound]: ...  # FILL IN: re-send _question(cursor); no state change
    def on_end(self, ev: EndSession) -> list[Outbound]:
        """End the session; delete nothing here (TASK-4226 owns recording cleanup on abandon)."""
        self.state.phase = Phase.ABORTED
        return [SessionEnded(session_id=self.state.session_id)]

    def on_ping(self, ev: Ping) -> list[Outbound]:
        """Keep-alive."""
        return [Pong()]

    def on_io_failed(self, ev: IOFailed) -> list[Outbound]: ...     # FILL IN: map ev.code → Error; Submit failure → back to ASKING
    def _commands_enabled(self, field: FormField) -> bool:
        """cfg.commands and per-field meta.voice.commands must both be "on" (AC14)."""
        return self.cfg.commands == "on" and field_voice_meta(field, logger=self.logger).commands == "on"

    def _apply_command(self, cmd: VoiceCommand) -> list[Outbound]: ...
        # FILL IN: CommandAck(command=cmd.value) + v1 effect: REPEAT→on_repeat, BACK→on_back, SKIP→on_skip, NEXT→on_skip when
        #          optional, HELP→narrator "command_ack_help" + hint, STOP→on_end, YES/NO→on_confirm in CONFIRMING;
        #          SEND/CHANGE only in REVIEW (TASK-4226) → Error("COMMAND_NOT_AVAILABLE") here — bounded by AC14.

    def _on_plan_exhausted(self) -> list[Outbound]:
        """Plan has no cursor left. Part 1: submit directly (v1 / review == "never"). TASK-4226 adds the REVIEW branch."""
        self.state.phase = Phase.SUBMITTING
        return [Submit(data=self._submission_data(), context=self._submission_context())]

    def on_submit_done(self, ev: SubmitDone) -> list[Outbound]:
        """FormComplete on success; ValidationErrors + re-ask first failing field otherwise."""
        # FILL IN: success → state.completed=True, phase COMPLETE, FormComplete(submission_id, stored_in, answers masked
        #          with is_sensitive, plausibility_summary=None); validation failure → ValidationErrors(errors, first_field_id),
        #          cursor=first_field_id, phase ASKING, _question(first) — bounded by AC9 (failures never stored).
        raise EngineError("UNIMPLEMENTED_SUBMIT_DONE")

    def _submission_data(self) -> dict[str, Any]: ...   # FILL IN: {field_id: AudioAnswer} evidence → scalars + evidence for wrap_voice (pipeline rewraps)
    def _submission_context(self) -> dict[str, Any]: ...  # FILL IN: {"channel": "audio", "session_id", "stt_backend"?, "locale"}
    def _echo(self, field_id: str, value: Any) -> Any:
        """Value echoed back to the client — masked for sensitive fields (S8)."""
        return _SENSITIVE_MASK if is_sensitive(self._fields[field_id]) else value
```
**Why**: `_on_plan_exhausted` is a named hook, so TASK-4226 can replace its
body. The v1 path (submit immediately) stays correct for `protocol_version ==
1` and for `review == "never"` (`Submit` is only emitted from REVIEW or when
review is `"never"`, spec M10 invariant. v1 parity is the documented
exception). How `_submission_data` passes evidence to `wrap_voice` depends on
the `Submit` model fields from TASK-4212. Follow them.

### `packages/parrot-formdesigner/tests/formdesigner/test_audio_engine_turns.py` (CREATE)
```python
"""FEAT-649 TASK-4225 — AudioFormSession part 1 (pure engine)."""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

import parrot_formdesigner.audio.engine as engine_mod


def test_engine_has_no_await() -> None:
    """AC2: audio/engine.py contains no Await / AsyncFunctionDef / async for|with."""
    tree = ast.parse(Path(engine_mod.__file__).read_text())
    banned = (ast.Await, ast.AsyncFunctionDef, ast.AsyncFor, ast.AsyncWith)
    offenders = [type(n).__name__ for n in ast.walk(tree) if isinstance(n, banned)]
    assert offenders == []
    assert "asyncio" not in Path(engine_mod.__file__).read_text()


@pytest.fixture
def session():  # FILL IN: build AudioFormSession over a 3-field form (TEXT, SELECT with 4 options incl. "Saltar", BOOLEAN)
    ...         #          with a stub planner result (feed PlanReady by hand) — bounded by spec §4 fixtures.
```
**Why**: the AST test reads the source file, so it also covers code that
TASK-4226 adds later.

### FILL IN checklist
- [ ] `__init__` — handler-table keys equal the TASK-4212 `type` literals; bounded by the dependency-name check
- [ ] `_delta_messages` — clears + `DeleteBlob`, `SectionEnter`, computed auto-accept; bounded by AC7
- [ ] `_question` — v1 fields kept; lazy `Synthesize` for late-visible fields; dynamic `required`; bounded by AC3/AC5/S7
- [ ] `on_transcript` — accept/confirm/no_match; MULTI_SELECT list; bounded by AC6/AC14
- [ ] `on_text` / `on_selection` / `on_payload` / `on_confirm` — v1 semantics (`api/audio_ws.py:539-689`); bounded by AC1
- [ ] `on_skip` / `on_back` / `on_repeat` / `_apply_command` / `on_io_failed`; bounded by AC14 and the v1 effects
- [ ] `on_submit_done`, `_submission_data`, `_submission_context`; bounded by AC8/AC9
- [ ] no `raise EngineError("UNIMPLEMENTED_…")` and no `...` body left in the committed file

---

## Acceptance Criteria

- [ ] `test_engine_has_no_await` passes (AC2).
- [ ] Scripted event lists reproduce the v1 flows: text answer → `answer_accepted` + `Replan`; `PlanReady` → next `question`; last answer → `Submit` → `SubmitDone` → `form_complete`.
- [ ] `test_engine_turn_flow_voice_select_fallback` covers the three voice modes (VOICE, PROMPT_SELECT, VISUAL_FALLBACK).
- [ ] A spoken option answer stores the option **value**. MULTI_SELECT stores a `list`. A tie yields `ConfirmRequest`. Disabled options are never accepted (AC6).
- [ ] An answer for a non-cursor field yields `Error(code="WRONG_FIELD")`. A re-answer bumps `version` (S6).
- [ ] An exact option match labelled like a command ("Saltar") is accepted as the option. With `meta.voice.commands: "off"` no command fires (AC14).
- [ ] Sensitive answers are echoed as `"[hidden]"` and are absent from log records (caplog).
- [ ] `ruff check` passes on both files. `audio/engine.py` imports nothing from `aiohttp`, `asyncio` or `parrot.*`.

---

## Validation Commands

- `pytest packages/parrot-formdesigner/tests/formdesigner/test_audio_engine_turns.py -q`

---

## Test Specification

```python
class TestEngineTurns:
    def test_start_emits_replan_then_plan_ready_emits_started_prefetch_question(self, session): ...
    def test_text_answer_accepts_and_replans(self, session): ...
    def test_wrong_field_rejected_and_reanswer_bumps_version(self, session): ...
    def test_engine_turn_flow_voice_select_fallback(self, session): ...
    def test_select_by_ordinal_stores_value_not_transcript(self, session): ...
    def test_multi_select_by_voice_is_list(self, session): ...
    def test_low_confidence_confirm_then_confirm_true_accepts(self, session): ...
    def test_confirm_false_resends_same_question(self, session): ...
    def test_exact_option_beats_command_and_commands_off(self, session): ...
    def test_repeat_back_skip_commands_ack_and_effect(self, session): ...
    def test_skip_required_rejected(self, session): ...
    def test_plan_exhausted_submits_and_submit_done_completes(self, session): ...
    def test_validation_errors_reask_first_field(self, session): ...
    def test_sensitive_masked_in_transcription_and_ack(self, session, caplog): ...
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug audio-form-interaction-workflow --feature-id FEAT-649`)
2. **Read the spec** at the path listed above (§2 Overview, §3 M2/M4/M5/M10, §5 AC2/AC3/AC6/AC7/AC14)
3. **Check dependencies** — every `Depends-on` task must be `"done"` in `sdd/tasks/index/audio-form-interaction-workflow.json`
4. **Verify the Codebase Contract** — run the dependency-name check; confirm every TASK-4211/4212 field the blueprint reads
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** — start from the blueprint blocks, complete every `# FILL IN:` marker, never change a fixed signature or path
7. **Verify** — run the Validation Commands with `PYTHONPATH=packages/parrot-formdesigner/src`
8. **Commit the code** — stage only the two files listed
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4225 audio-form-interaction-workflow verified`
10. **Fill in the Completion Note** below (including any event-name mapping), then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
