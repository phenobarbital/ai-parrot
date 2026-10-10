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
from ..core.voice_answer import wrap_voice
from .commands import VoiceCommand, classify_command
from .events import (
    AnswerAccepted, AnswerCleared, AnswerPayload, AnswerRejected, AnswerSelection, AnswerText, AudioReceived,
    BlobStored, CommandAck, ConfirmAnswer, ConfirmRequest, DeleteBlob, EndSession, Error, FormComplete, GoBack,
    InboundEvent, IOFailed, Outbound, Ping, PlanReady, PlanUpdated, Pong, Question, QuestionSkipped, RepeatQuestion,
    Replan, SectionEnter, SessionEnded, SessionStarted, SkipQuestion, StartSession, StoreBlob, Submit, SubmitDone,
    Synthesize, Transcribe, Transcription, TranscriptReady, ValidationErrors,
)
from .models import AudioAnswer, AudioFormManifest, AudioQuestion, AudioSessionState, OptionMatch, Phase
from .narration.engine import Narrator
from .narration.lexicon import Lexicon
from .option_matcher import match_option
from .planner import PlanDelta, QuestionPlanner

_SENSITIVE_MASK = "[hidden]"
_ANSWERING_PHASES = (Phase.ASKING, Phase.CONFIRMING)


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
        self._last_audio: tuple[str, bytes, str | None] | None = None   # (field_id, bytes, mime) — never snapshotted
        self._skipped: set[str] = set()          # optional fields the user skipped (not snapshotted in part 1)
        self._synthesized: set[str] = set()      # field_ids whose narration has already been requested
        self._started_emitted = False
        self._last_section: str | None = None
        self._handlers: dict[str, Callable[[Any], list[Outbound]]] = {
            "start_session": self.on_start, "_plan_ready": self.on_plan_ready, "_audio": self.on_audio_frame,
            "_transcript": self.on_transcript, "answer_text": self.on_text, "answer_selection": self.on_selection,
            "answer_payload": self.on_payload, "confirm_answer": self.on_confirm, "skip_question": self.on_skip,
            "go_back": self.on_back, "repeat_question": self.on_repeat, "end_session": self.on_end,
            "ping": self.on_ping, "_blob_stored": self.on_blob_stored, "_io_failed": self.on_io_failed,
            "_submit_done": self.on_submit_done,
        }

    def handle(self, event: InboundEvent) -> list[Outbound]:
        """Dispatch one event; mutate state; return wire messages + I/O requests. Never awaits."""
        handler = self._handlers.get(event.type)
        if handler is None:
            return [Error(code="UNKNOWN_EVENT", message=f"Unhandled event type: {event.type}")]
        if self.state.phase in (Phase.IDLE,) and event.type not in ("start_session", "ping"):
            return [Error(code="SESSION_NOT_STARTED", message="Call start_session first")]
        self.logger.debug("engine: phase=%s event=%s cursor=%s", self.state.phase, event.type, self.state.cursor)
        return handler(event)

    # ---- start / plan --------------------------------------------------
    def on_start(self, ev: StartSession) -> list[Outbound]:
        """Record locale/protocol, enter PLANNING and request the first re-plan."""
        if self.state.phase != Phase.IDLE:
            return [Error(code="ALREADY_STARTED", message="Session already started")]
        self.state.locale = ev.locale
        self.state.protocol_version = ev.protocol_version
        self.state.phase = Phase.PLANNING
        return [Replan()]

    def on_plan_ready(self, ev: PlanReady) -> list[Outbound]:
        """Adopt the new plan; emit plan deltas; ask the cursor question, or finish."""
        if self.state.phase in (Phase.ABORTED, Phase.COMPLETE, Phase.SUBMITTING):
            return []
        delta = PlanDelta.model_validate(ev.delta)
        out: list[Outbound] = self._delta_messages(delta)
        first = not self._started_emitted
        self.state.plan = list(ev.plan)
        cursor = self.planner.next_cursor(self.state.plan, self._answered_or_skipped())
        self.state.cursor = cursor
        if first:
            self._started_emitted = True
            v2 = self.state.protocol_version >= 2
            out.insert(0, SessionStarted(
                session_id=self.state.session_id, total_questions=len(self.state.plan), title=self.manifest.title,
                protocol_version=self.state.protocol_version,
                hands_free=self.cfg.hands_free if v2 else None,
                max_recording_seconds=self.cfg.max_recording_seconds if v2 else None,
                prefetch_count=len(self.state.plan) if v2 else None,
            ))
            out.insert(1, self._synthesize_request(self.state.plan, include_system=True))
            self._synthesized.update(self.state.plan)
        if cursor is None:
            return out + self._on_plan_exhausted()
        if cursor not in self.state.history:
            self.state.history.append(cursor)
        self.state.phase = Phase.ASKING
        return out + self._ask(cursor)

    def _answered_or_skipped(self) -> dict[str, Any]:
        """Membership map used by the planner to find the first unanswered field."""
        merged: dict[str, Any] = dict(self.state.answers)
        for fid in self._skipped:
            merged.setdefault(fid, None)
        return merged

    def _delta_messages(self, delta: Any) -> list[Outbound]:
        """PlanUpdated / AnswerCleared(+DeleteBlob) for one PlanDelta; auto-accept computed values."""
        out: list[Outbound] = []
        order_changed = self._started_emitted and list(delta.order) != list(self.state.plan)
        if delta.hidden or delta.cleared or delta.required_changed or delta.hidden_by_cap or order_changed:
            out.append(PlanUpdated(order=list(delta.order), hidden=list(delta.hidden), cleared=list(delta.cleared),
                                   required_changed=dict(delta.required_changed),
                                   hidden_by_cap=list(delta.hidden_by_cap)))
        for fid in delta.cleared:
            answer = self.state.answers.pop(fid, None)
            self._skipped.discard(fid)
            if fid in self.state.history:
                self.state.history.remove(fid)
            if answer is None:
                continue
            out.append(AnswerCleared(field_id=fid))
            if answer.blob_ref:
                out.append(DeleteBlob(blob_ref=answer.blob_ref))
        for fid, value in delta.computed.items():
            field = self._fields.get(fid)
            if field is None:
                continue
            prev = self.state.answers.get(fid)
            if prev is not None and prev.value == value:
                continue
            version = (prev.version + 1) if prev is not None else 1
            self.state.answers[fid] = AudioAnswer(field_id=fid, field_uid=field.field_uid, value=value,
                                                  source="text", version=version)
        return out

    def _synthesize_request(self, field_ids: list[str], *, include_system: bool) -> Synthesize:
        """One Synthesize for the narration segments of ``field_ids`` (+ sys:* phrases on first plan)."""
        texts: dict[str, str] = dict(self.narrator.system_phrases()) if include_system else {}
        for fid in field_ids:
            q = self._questions.get(fid)
            if q is None:
                continue
            plan = self.narrator.plan_question(q, self.cfg, field_voice_meta(self._fields[fid], logger=self.logger))
            texts.update(plan.segments)
        return Synthesize(keys=list(texts), texts=texts)

    def _ask(self, field_id: str) -> list[Outbound]:
        """Question for ``field_id``, preceded by SectionEnter / a lazy Synthesize when needed."""
        out: list[Outbound] = []
        q = self._questions[field_id]
        section = q.section_uid
        if section is not None and section != self._last_section:
            self._last_section = section
            out.append(SectionEnter(section_uid=section, title=q.section_title))
        if field_id not in self._synthesized:
            self._synthesized.add(field_id)
            out.append(self._synthesize_request([field_id], include_system=False))
        out.append(self._question(field_id))
        return out

    def _question(self, field_id: str) -> Question:
        """Build the Question wire message for ``field_id`` (v1 fields kept for protocol_version 1)."""
        q = self._questions[field_id]
        field = self._fields[field_id]
        index = self.state.plan.index(field_id) if field_id in self.state.plan else q.index
        self.state.current_index = index
        v2 = self.state.protocol_version >= 2
        meta = field_voice_meta(field, logger=self.logger)
        return Question(
            index=index, field_id=field_id, label=q.label, required=self.planner.effective_required(field_id),
            field_type=q.field_type, voice_mode=getattr(q.voice_mode, "value", q.voice_mode), render_mode=q.render_mode, sensitive=q.sensitive,
            description=q.description, options=q.options, fallback_html=q.fallback_html, section_uid=q.section_uid,
            hint=q.hint if v2 else None,
            ui_cue=(meta.ui_cue or q.ui_cue) if v2 else None,
            answer_modes=(list(q.answer_modes) or None) if v2 else None,
            narration=self.narrator.plan_question(q, self.cfg, meta) if v2 else None,
        )

    # ---- answers -------------------------------------------------------
    def _guard(self, field_id: str) -> list[Outbound] | None:
        """Error list when an answer for ``field_id`` is not acceptable right now, else None."""
        cursor = self.state.cursor
        if cursor is None:
            return [Error(code="SESSION_COMPLETE", message="No question is awaiting an answer")]
        if self.state.phase not in _ANSWERING_PHASES:
            return [Error(code="WRONG_PHASE", message=f"Cannot answer while {self.state.phase.value}")]
        if field_id != cursor:
            return [Error(code="WRONG_FIELD", message=f"Expected an answer for '{cursor}', got '{field_id}'")]
        return None

    def on_audio_frame(self, ev: AudioReceived) -> list[Outbound]:
        """Stash the recording (never snapshotted) and request transcription for the cursor field."""
        if self.state.cursor is None:
            return [Error(code="SESSION_COMPLETE", message="All questions answered")]
        if self.state.phase not in _ANSWERING_PHASES:
            return [Error(code="WRONG_PHASE", message=f"Cannot answer while {self.state.phase.value}")]
        self._last_audio = (self.state.cursor, ev.audio, ev.mime)
        return [Transcribe(field_id=self.state.cursor, audio=ev.audio, mime=ev.mime)]

    def on_transcript(self, ev: TranscriptReady) -> list[Outbound]:
        """Commands → option match → STT confidence gate → accept / confirm / reject."""
        bad = self._guard(ev.field_id)
        if bad is not None:
            return bad
        field = self._fields[ev.field_id]
        q = self._questions[ev.field_id]
        meta = field_voice_meta(field, logger=self.logger)
        sensitive = is_sensitive(field)
        shown = _SENSITIVE_MASK if sensitive else ev.text
        out: list[Outbound] = [Transcription(field_id=ev.field_id, text=shown, confidence=ev.confidence)]
        evidence = AudioAnswer(
            field_id=ev.field_id, value=None, source="speech", confidence=ev.confidence,
            raw_transcript=None if sensitive else ev.text, audio_mime=ev.audio_mime,
            audio_bytes_len=ev.audio_bytes_len, duration_ms=ev.duration_ms, stt_language=ev.language,
        )
        outcome = None
        is_option = bool(q.options) or field.field_type == FieldType.BOOLEAN
        if is_option:
            outcome = match_option(
                ev.text, q.options or [], field_type=field.field_type, lexicon=self.lexicon,
                threshold=meta.match_threshold if meta.match_threshold is not None else self.cfg.option_match_threshold,
                confirm_floor=self.cfg.stt_confirm_threshold, stt_confidence=ev.confidence,
                multi=field.field_type == FieldType.MULTI_SELECT,
            )
        exact = (outcome is not None and outcome.status == "accepted" and outcome.match is not None
                 and outcome.match.method == "exact")
        if not exact and self._commands_enabled(field):
            cmd = classify_command(ev.text, lexicon=self.lexicon, phase=self.state.phase)
            if cmd is not None:
                return out + self._apply_command(cmd)

        confirm_pref = meta.confirm
        if outcome is not None:
            multi = field.field_type == FieldType.MULTI_SELECT
            if outcome.status == "no_match":
                return out + [AnswerRejected(field_id=ev.field_id, error=self.narrator.render("no_match"),
                                             code="NO_MATCH")]
            value: Any = [m.value for m in outcome.matches] if multi else outcome.match.value  # type: ignore[union-attr]
            if outcome.status == "confirm" or confirm_pref == "always":
                alternatives = outcome.alternatives or (outcome.matches if multi else [])
                return out + self._request_confirm(evidence, value, ev.text, outcome.match, alternatives)
            return out + self._accept(ev.field_id, value, source="speech", confidence=ev.confidence, raw=evidence.raw_transcript,
                                      matched=outcome.match, evidence=evidence)

        # Free-form answer
        if not ev.text.strip():
            return out + [AnswerRejected(field_id=ev.field_id, error="Empty transcript", code="EMPTY")]
        confidence = 1.0 if ev.confidence is None else ev.confidence
        low = confidence < self.cfg.stt_confirm_threshold
        if confirm_pref == "always" or (low and confirm_pref != "never"):
            return out + self._request_confirm(evidence, ev.text, ev.text, None, [])
        return out + self._accept(ev.field_id, ev.text, source="speech", confidence=ev.confidence,
                                  raw=evidence.raw_transcript, evidence=evidence)

    def _request_confirm(self, evidence: AudioAnswer, value: Any, transcript: str, matched: OptionMatch | None,
                         alternatives: list[OptionMatch]) -> list[Outbound]:
        """Park the answer in ``state.pending`` and ask the client to confirm it."""
        sensitive = is_sensitive(self._fields[evidence.field_id])
        self.state.pending = evidence.model_copy(update={"value": value, "matched": matched})
        self.state.phase = Phase.CONFIRMING
        return [ConfirmRequest(
            field_id=evidence.field_id, transcript=_SENSITIVE_MASK if sensitive else transcript,
            confidence=evidence.confidence, matched=matched, alternatives=alternatives or None,
        )]

    def _accept(self, field_id: str, value: Any, *, source: str, confidence: float | None = None,
                raw: str | None = None, matched: OptionMatch | None = None,
                evidence: AudioAnswer | None = None) -> list[Outbound]:
        """Single acceptance funnel: bump version, store, ack, StoreBlob for speech, then Replan."""
        prev = self.state.answers.get(field_id)
        version = (prev.version + 1) if prev is not None else 1
        extra: dict[str, Any] = {}
        if evidence is not None:
            extra = {"audio_mime": evidence.audio_mime, "audio_bytes_len": evidence.audio_bytes_len,
                     "duration_ms": evidence.duration_ms, "stt_language": evidence.stt_language}
        answer = AudioAnswer(field_id=field_id, field_uid=self._fields[field_id].field_uid, value=value,
                             source=source, confidence=confidence, raw_transcript=raw, matched=matched,
                             version=version, **extra)
        self.state.answers[field_id] = answer
        self._skipped.discard(field_id)
        self.state.pending = None
        self.state.phase = Phase.ACCEPTING
        out: list[Outbound] = [AnswerAccepted(field_id=field_id, source=source, value=self._echo(field_id, value),
                                              matched=matched)]
        if (source == "speech" and self.cfg.store_recordings and self._last_audio
                and self._last_audio[0] == field_id):
            _, audio, mime = self._last_audio
            out.append(StoreBlob(field_id=field_id, audio=audio, mime=mime or "audio/webm", version=version))
        self._last_audio = None
        return out + [Replan()]

    def _is_empty(self, value: Any) -> bool:
        return value is None or (isinstance(value, str) and not value.strip()) or (
            isinstance(value, (list, dict)) and not value)

    def on_text(self, ev: AnswerText) -> list[Outbound]:
        """Typed answer for the cursor field."""
        bad = self._guard(ev.field_id)
        if bad is not None:
            return bad
        if self.planner.effective_required(ev.field_id) and not ev.value.strip():
            return [AnswerRejected(field_id=ev.field_id, error="This field is required", code="REQUIRED")]
        return self._accept(ev.field_id, ev.value, source="text")

    def on_selection(self, ev: AnswerSelection) -> list[Outbound]:
        """Selection answer (single or multi) validated against the enabled option values."""
        bad = self._guard(ev.field_id)
        if bad is not None:
            return bad
        q = self._questions[ev.field_id]
        field = self._fields[ev.field_id]
        allowed = [o.get("value") for o in (q.options or []) if not o.get("disabled", False)]
        multi = ev.values is not None or field.field_type == FieldType.MULTI_SELECT
        if multi:
            if ev.values is not None:
                values = list(ev.values)
            elif isinstance(ev.value, list):
                values = list(ev.value)
            else:
                values = [] if ev.value is None else [ev.value]
            if self.planner.effective_required(ev.field_id) and not values:
                return [AnswerRejected(field_id=ev.field_id, error="Select at least one option", code="REQUIRED")]
            if allowed and any(v not in allowed for v in values):
                return [Error(code="INVALID_OPTION", message="One or more selected values are not valid options")]
            return self._accept(ev.field_id, values, source="selection")
        if allowed and ev.value not in allowed:
            return [Error(code="INVALID_OPTION", message=f"'{ev.value}' is not a valid option")]
        return self._accept(ev.field_id, ev.value, source="selection")

    def on_payload(self, ev: AnswerPayload) -> list[Outbound]:
        """Payload answer (VISUAL_FALLBACK / structured fields) for the cursor field."""
        bad = self._guard(ev.field_id)
        if bad is not None:
            return bad
        if self.planner.effective_required(ev.field_id) and self._is_empty(ev.value):
            return [AnswerRejected(field_id=ev.field_id, error="This field is required", code="REQUIRED")]
        return self._accept(ev.field_id, ev.value, source="text")

    def on_confirm(self, ev: ConfirmAnswer) -> list[Outbound]:
        """Confirm or discard the pending low-confidence answer."""
        pending = self.state.pending
        if pending is None:
            return [Error(code="NO_PENDING_ANSWER", message="No answer is awaiting confirmation")]
        if ev.field_id and ev.field_id != pending.field_id:
            return [Error(code="FIELD_MISMATCH",
                          message=f"confirm_answer for '{ev.field_id}' but the pending answer is for "
                                  f"'{pending.field_id}'")]
        self.state.pending = None
        if ev.confirmed:
            return self._accept(pending.field_id, pending.value, source="speech", confidence=pending.confidence,
                                raw=pending.raw_transcript, matched=pending.matched, evidence=pending)
        self._last_audio = None
        self.state.phase = Phase.ASKING
        return [self._question(pending.field_id)]

    def on_blob_stored(self, ev: BlobStored) -> list[Outbound]:
        """Attach the stored recording reference to the (still current) answer version."""
        answer = self.state.answers.get(ev.field_id)
        if answer is None or answer.version != ev.version:
            # Stale blob: the answer was cleared or re-answered meanwhile — delete the orphan.
            return [DeleteBlob(blob_ref=ev.blob_ref)]
        answer.blob_ref = ev.blob_ref
        return []

    # ---- navigation / commands / submit -------------------------------
    def on_skip(self, ev: SkipQuestion) -> list[Outbound]:
        """Skip the cursor question unless it is required."""
        cursor = self.state.cursor
        if cursor is None or self.state.phase not in _ANSWERING_PHASES:
            return [Error(code="WRONG_PHASE", message="Nothing to skip")]
        if ev.field_id is not None and ev.field_id != cursor:
            return [Error(code="WRONG_FIELD", message=f"Expected '{cursor}', got '{ev.field_id}'")]
        if self.planner.effective_required(cursor):
            return [AnswerRejected(field_id=cursor, error="This field is required and cannot be skipped",
                                   code="REQUIRED")]
        self._skipped.add(cursor)
        self.state.pending = None
        self._last_audio = None
        self.state.phase = Phase.ACCEPTING
        return [QuestionSkipped(field_id=cursor, reason="user"), Replan()]

    def on_back(self, ev: GoBack) -> list[Outbound]:
        """Move the cursor to a previous question (explicit target or the latest visited one)."""
        if self.state.phase not in _ANSWERING_PHASES:
            return [Error(code="WRONG_PHASE", message="Cannot go back now")]
        target = ev.to_field_id
        if target is None and ev.to_index is not None:
            if not 0 <= ev.to_index < len(self.state.plan):
                return [Error(code="INVALID_INDEX", message=f"Index {ev.to_index} out of range")]
            target = self.state.plan[ev.to_index]
        if target is not None and target not in self.state.plan:
            return [Error(code="INVALID_FIELD", message=f"'{target}' is not in the plan")]
        dest = self.planner.previous(self.state.plan, self.state.history, target)
        if dest is None:
            return [Error(code="NO_PREVIOUS", message="There is no previous question")]
        if dest in self.state.history:
            del self.state.history[self.state.history.index(dest) + 1:]
        else:
            self.state.history.append(dest)
        self.state.cursor = dest
        self.state.pending = None
        self._last_audio = None
        self.state.phase = Phase.ASKING
        return self._ask(dest)

    def on_repeat(self, ev: RepeatQuestion) -> list[Outbound]:
        """Re-send the cursor question; no state change."""
        cursor = self.state.cursor
        if cursor is None or self.state.phase not in _ANSWERING_PHASES:
            return [Error(code="WRONG_PHASE", message="Nothing to repeat")]
        return [self._question(cursor)]

    def on_end(self, ev: EndSession) -> list[Outbound]:
        """End the session; delete nothing here (TASK-4226 owns recording cleanup on abandon)."""
        self.state.phase = Phase.ABORTED
        return [SessionEnded(session_id=self.state.session_id)]

    def on_ping(self, ev: Ping) -> list[Outbound]:
        """Keep-alive."""
        return [Pong()]

    def on_io_failed(self, ev: IOFailed) -> list[Outbound]:
        """Map a failed I/O request onto a client-visible error (recording I/O failures are non-fatal)."""
        self.logger.warning("engine: io failed request=%s code=%s phase=%s", ev.request, ev.code, self.state.phase)
        if ev.request in ("_store_blob", "_delete_blob"):
            return []
        out: list[Outbound] = [Error(code=ev.code, message=ev.detail or f"{ev.request} failed")]
        if ev.request == "_submit" and self.state.phase == Phase.SUBMITTING:
            last = self.state.plan[-1] if self.state.plan else None
            if last is not None:
                self.state.cursor = last
                self.state.phase = Phase.ASKING
                out.extend(self._ask(last))
        elif ev.request == "_transcribe":
            self._last_audio = None
        return out

    def _commands_enabled(self, field: FormField) -> bool:
        """cfg.commands and per-field meta.voice.commands must both be "on" (AC14)."""
        return self.cfg.commands == "on" and field_voice_meta(field, logger=self.logger).commands == "on"

    def _apply_command(self, cmd: VoiceCommand) -> list[Outbound]:
        """CommandAck + the v1 effect of the command."""
        cursor = self.state.cursor
        ack = CommandAck(command=cmd.value, field_id=cursor)
        if cmd is VoiceCommand.REPEAT:
            return [ack] + self.on_repeat(RepeatQuestion(type="repeat_question"))
        if cmd is VoiceCommand.BACK:
            return [ack] + self.on_back(GoBack(type="go_back"))
        if cmd is VoiceCommand.SKIP:
            return [ack] + self.on_skip(SkipQuestion(type="skip_question"))
        if cmd is VoiceCommand.NEXT:
            if cursor is not None and self.planner.effective_required(cursor):
                return [ack, AnswerRejected(field_id=cursor, error="This field is required and cannot be skipped",
                                            code="REQUIRED")]
            return [ack] + self.on_skip(SkipQuestion(type="skip_question"))
        if cmd is VoiceCommand.HELP:
            return [ack] + self.on_repeat(RepeatQuestion(type="repeat_question"))
        if cmd is VoiceCommand.STOP:
            return [ack] + self.on_end(EndSession(type="end_session"))
        if cmd in (VoiceCommand.YES, VoiceCommand.NO):
            return [ack] + self.on_confirm(ConfirmAnswer(type="confirm_answer", field_id=cursor or "",
                                                         confirmed=cmd is VoiceCommand.YES))
        return [Error(code="COMMAND_NOT_AVAILABLE", message=f"Command '{cmd.value}' is not available here")]

    def _on_plan_exhausted(self) -> list[Outbound]:
        """Plan has no cursor left. Part 1: submit directly (v1 / review == "never"). TASK-4226 adds the REVIEW branch."""
        self.state.phase = Phase.SUBMITTING
        return [Submit(data=self._submission_data(), context=self._submission_context())]

    def on_submit_done(self, ev: SubmitDone) -> list[Outbound]:
        """FormComplete on success; ValidationErrors + re-ask first failing field otherwise.

        ``ev.outcome`` is either a dumped ``SubmitOutcome`` (success: ``submission_id`` / ``stored_in``) or a dict
        carrying ``errors`` (``{field_id: [messages]}``) for a deterministic validation rejection.
        """
        outcome = ev.outcome or {}
        errors = outcome.get("errors")
        if not errors:
            self.state.completed = True
            self.state.phase = Phase.COMPLETE
            return [FormComplete(
                submission_id=str(outcome.get("submission_id") or self.state.submission_id),
                stored_in=outcome.get("stored_in"),
                answers={fid: self._echo(fid, a.value) for fid, a in self.state.answers.items()
                         if fid in self._fields and a.value is not None},
                plausibility_summary=None,
            )]
        normalised: dict[str, list[str]] = {
            str(k): [str(m) for m in (v if isinstance(v, list) else [v])] for k, v in dict(errors).items()
        }
        first = next((fid for fid in self.state.plan if fid in normalised), None)
        if first is None:
            first = next((fid for fid in normalised if fid in self._fields), None)
        out: list[Outbound] = [ValidationErrors(errors=normalised, first_field_id=first)]
        if first is None:
            first = self.state.plan[-1] if self.state.plan else None
        if first is not None:
            self.state.cursor = first
            self.state.phase = Phase.ASKING
            if first in self.state.history:
                del self.state.history[self.state.history.index(first) + 1:]
            else:
                self.state.history.append(first)
            out.extend(self._ask(first))
        return out

    def _submission_data(self) -> dict[str, Any]:
        """Scalars per answered field, with speech answers re-folded into voice evidence envelopes."""
        scalars = {fid: a.value for fid, a in self.state.answers.items()
                   if fid in self._fields and a.value is not None}
        return wrap_voice(scalars, {fid: a for fid, a in self.state.answers.items() if fid in scalars})

    def _submission_context(self) -> dict[str, Any]:
        """Context handed to the submission pipeline."""
        return {"channel": "audio", "session_id": self.state.session_id, "locale": self.state.locale,
                "submission_id": self.state.submission_id}

    def _echo(self, field_id: str, value: Any) -> Any:
        """Value echoed back to the client — masked for sensitive fields (S8)."""
        return _SENSITIVE_MASK if is_sensitive(self._fields[field_id]) else value
