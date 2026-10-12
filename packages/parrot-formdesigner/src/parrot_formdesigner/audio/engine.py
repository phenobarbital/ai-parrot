"""Pure audio form session engine (FEAT-649, spec §3 Module 10).

``AudioFormSession.handle(event) -> list[Outbound]`` is a synchronous state
machine: it never awaits and performs no I/O. I/O is requested through
``Outbound`` request models that the WebSocket adapter performs and answers
with ``*_Done`` / ``PlanReady`` / ``IOFailed`` events.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable
from zoneinfo import ZoneInfo

from ..core.llm_validation import LLMValidationConfig, PlausibilityReport, llm_validation_enabled
from ..core.schema import FormField, FormSchema
from ..core.types import FieldType
from ..core.voice import FieldVoiceMeta, VoiceFormConfig, field_voice_meta, is_sensitive
from ..core.voice_answer import wrap_voice
from .commands import VoiceCommand, classify_command
from .events import (
    AnswerAccepted,
    AnswerCleared,
    AnswerPayload,
    AnswerRejected,
    AnswerSelection,
    AnswerText,
    AudioReceived,
    BlobStored,
    CommandAck,
    ConfirmAnswer,
    ConfirmRequest,
    DeleteBlob,
    EndSession,
    Error,
    FormComplete,
    GoBack,
    InboundEvent,
    IOFailed,
    Outbound,
    Ping,
    PlanReady,
    PlanUpdated,
    PlausibilityDone,
    PlausibilityResult,
    Pong,
    Question,
    QuestionSkipped,
    RepeatQuestion,
    RefineValue,
    Replan,
    ReviewConfirm,
    ReviewEdit,
    ReviewItem,
    ReviewPrompt,
    ReviewStart,
    RunPlausibility,
    SaveSnapshot,
    SectionEnter,
    SessionEnded,
    SessionResumed,
    SessionStarted,
    SkipQuestion,
    StartSession,
    StoreBlob,
    Submit,
    SubmitDone,
    Synthesize,
    Transcribe,
    Transcription,
    TranscriptReady,
    ValueRefined,
    ValidationErrors,
)
from .models import (
    AudioAnswer,
    AudioFormManifest,
    AudioQuestion,
    AudioSessionState,
    OptionMatch,
    Phase,
    ReviewItemData,
)
from .narration.engine import Narrator
from .narration.lexicon import Lexicon, normalize
from .option_matcher import match_option, match_review_item
from .planner import PlanDelta, QuestionPlanner
from .normalize import REFINABLE_TYPES, NormalizeContext, NormalizeResult, normalize_spoken, validate_typed
from .session_store import AudioSnapshot

_SENSITIVE_MASK = "[hidden]"
_ANSWERING_PHASES = (Phase.ASKING, Phase.CONFIRMING)
_SKIPPED_META_KEY = "_skipped"  # answer_meta entry carrying the skipped field ids (snapshot only)
_REVIEW_FIELD = "_review"  # Transcribe.field_id used for spoken review turns


@dataclass
class _PendingRefine:
    """An answer parked while the LLM post-processor runs (never snapshotted)."""

    evidence: AudioAnswer
    rules: NormalizeResult
    rules_by: str | None
    request_id: str


class EngineError(Exception):
    """Programming error inside the engine (never raised for client input)."""

    def __init__(self, code: str, message: str = "") -> None:
        super().__init__(message or code)
        self.code = code


class AudioFormSession:
    """Pure audio form state machine — see module docstring."""

    def __init__(
        self,
        *,
        form: FormSchema,
        manifest: AudioFormManifest,
        cfg: VoiceFormConfig,
        narrator: Narrator,
        lexicon: Lexicon,
        state: AudioSessionState,
        llm_cfg: LLMValidationConfig | None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.form = form
        self.manifest = manifest
        self.cfg = cfg
        self.narrator = narrator
        self.lexicon = lexicon
        self.state = state
        self.llm_cfg = llm_cfg
        self._clock: Callable[[], datetime] = clock or (lambda: datetime.now(timezone.utc))
        self._llm = llm_cfg or LLMValidationConfig()  # effective config: field-level opt-in works without a form block
        self.planner = QuestionPlanner(form, manifest, cfg)  # adapter awaits planner.replan() on Replan
        self.logger = logging.getLogger(__name__)
        self._questions: dict[str, AudioQuestion] = {q.field_id: q for q in manifest.questions}
        self._fields: dict[str, FormField] = {f.field_id: f for f in form.iter_fields_recursive()}
        self._last_audio: tuple[str, bytes, str | None] | None = None  # (field_id, bytes, mime) — never snapshotted
        self._skipped: set[str] = set()  # optional fields the user skipped (persisted via answer_meta)
        self._pl_requested: set[str] | None = None  # fields of the in-flight plausibility batch
        self._pl_unchecked: set[str] = set()  # fields whose last plausibility batch was blocked (on_error=block)
        self._stop_prev_phase: Phase | None = None  # set while a spoken STOP awaits yes/no confirmation
        self._resume_snap: AudioSnapshot | None = None
        self._refining: _PendingRefine | None = None
        self._refine_warned: set[str] = set()
        self._synthesized: set[str] = set()  # field_ids whose narration has already been requested
        self._started_emitted = False
        self._last_section: str | None = None
        self._handlers: dict[str, Callable[[Any], list[Outbound]]] = {
            "start_session": self.on_start,
            "_plan_ready": self.on_plan_ready,
            "_audio": self.on_audio_frame,
            "_transcript": self.on_transcript,
            "answer_text": self.on_text,
            "answer_selection": self.on_selection,
            "answer_payload": self.on_payload,
            "confirm_answer": self.on_confirm,
            "skip_question": self.on_skip,
            "go_back": self.on_back,
            "repeat_question": self.on_repeat,
            "end_session": self.on_end,
            "ping": self.on_ping,
            "_blob_stored": self.on_blob_stored,
            "_io_failed": self.on_io_failed,
            "_submit_done": self.on_submit_done,
            "review_confirm": self.on_review_confirm,
            "review_edit": self.on_review_edit,
            "_plausibility_done": self.on_plausibility_done,
            "_value_refined": self.on_value_refined,
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
        if ev.resume_session_id:
            return self._resume(ev)
        self.state.locale = ev.locale
        self.state.timezone = ev.timezone
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
        if self.state.return_to_review and self._review_enabled() and self.state.phase == Phase.ACCEPTING:
            edited = self.state.cursor
            if cursor is None:
                # Edited answer accepted and nothing new to ask: delta plausibility for the changed field only.
                fields = self._plausibility_fields({edited} if edited else set())
                self.state.cursor = None
                if fields:
                    self._pl_requested = set(fields)
                    self.state.phase = Phase.PLAUSIBILITY
                    return out + [RunPlausibility(fields=fields), self._save()]
                return out + self._start_review(report=self.state.plausibility)
            # The edit revealed new unanswered fields: ask them before returning to the review.
        self.state.cursor = cursor
        if first:
            self._started_emitted = True
            v2 = self.state.protocol_version >= 2
            out.insert(
                0,
                SessionStarted(
                    session_id=self.state.session_id,
                    total_questions=len(self.state.plan),
                    title=self.manifest.title,
                    protocol_version=self.state.protocol_version,
                    hands_free=self.cfg.hands_free if v2 else None,
                    max_recording_seconds=self.cfg.max_recording_seconds if v2 else None,
                    prefetch_count=len(self.state.plan) if v2 else None,
                ),
            )
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
            out.append(
                PlanUpdated(
                    order=list(delta.order),
                    hidden=list(delta.hidden),
                    cleared=list(delta.cleared),
                    required_changed=dict(delta.required_changed),
                    hidden_by_cap=list(delta.hidden_by_cap),
                )
            )
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
            self.state.answers[fid] = AudioAnswer(
                field_id=fid, field_uid=field.field_uid, value=value, source="text", version=version
            )
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
            index=index,
            field_id=field_id,
            label=q.label,
            required=self.planner.effective_required(field_id),
            field_type=q.field_type,
            voice_mode=getattr(q.voice_mode, "value", q.voice_mode),
            render_mode=q.render_mode,
            sensitive=q.sensitive,
            description=q.description,
            options=q.options,
            fallback_html=q.fallback_html,
            section_uid=q.section_uid,
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
        if self.state.phase == Phase.REVIEW or self._stop_prev_phase is not None:
            # A pending STOP confirmation is answered independently of the question cursor (it may be None).
            self._last_audio = None
            field_id = _REVIEW_FIELD if self._stop_prev_phase is None else (self.state.cursor or _REVIEW_FIELD)
            return [Transcribe(field_id=field_id, audio=ev.audio, mime=ev.mime)]
        if self.state.cursor is None:
            return [Error(code="SESSION_COMPLETE", message="All questions answered")]
        if self.state.phase not in _ANSWERING_PHASES:
            return [Error(code="WRONG_PHASE", message=f"Cannot answer while {self.state.phase.value}")]
        self._last_audio = (self.state.cursor, ev.audio, ev.mime)
        return [Transcribe(field_id=self.state.cursor, audio=ev.audio, mime=ev.mime)]

    def on_transcript(self, ev: TranscriptReady) -> list[Outbound]:
        """Commands → option match → STT confidence gate → accept / confirm / reject."""
        if self._stop_prev_phase is not None:
            cmd = classify_command(ev.text, lexicon=self.lexicon, phase=Phase.CONFIRMING)
            if cmd in (VoiceCommand.YES, VoiceCommand.NO):
                return [CommandAck(command=cmd.value)] + self.on_confirm(
                    ConfirmAnswer(
                        type="confirm_answer", field_id=self.state.cursor or "", confirmed=cmd is VoiceCommand.YES
                    )
                )
            return [ConfirmRequest(field_id=self.state.cursor or "", transcript="stop", purpose="stop")]
        if self.state.phase == Phase.REVIEW:
            return self.on_review_prompt_answer(ev)
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
            field_id=ev.field_id,
            value=None,
            source="speech",
            confidence=ev.confidence,
            raw_transcript=None if sensitive else ev.text,
            audio_mime=ev.audio_mime,
            audio_bytes_len=ev.audio_bytes_len,
            duration_ms=ev.duration_ms,
            stt_language=ev.language,
        )
        outcome = None
        is_option = bool(q.options) or field.field_type == FieldType.BOOLEAN
        if is_option:
            outcome = match_option(
                ev.text,
                q.options or [],
                field_type=field.field_type,
                lexicon=self.lexicon,
                threshold=meta.match_threshold if meta.match_threshold is not None else self.cfg.option_match_threshold,
                confirm_floor=self.cfg.stt_confirm_threshold,
                stt_confidence=ev.confidence,
                multi=field.field_type == FieldType.MULTI_SELECT,
            )
        exact = (
            outcome is not None
            and outcome.status == "accepted"
            and outcome.match is not None
            and outcome.match.method == "exact"
        )
        if not exact and self._commands_enabled(field):
            cmd = classify_command(ev.text, lexicon=self.lexicon, phase=self.state.phase)
            if cmd is not None:
                return out + self._apply_command(cmd)

        confirm_pref = meta.confirm
        if outcome is not None:
            multi = field.field_type == FieldType.MULTI_SELECT
            if outcome.status == "no_match":
                return out + [
                    AnswerRejected(field_id=ev.field_id, error=self.narrator.render("no_match"), code="NO_MATCH")
                ]
            value: Any = [m.value for m in outcome.matches] if multi else outcome.match.value  # type: ignore[union-attr]
            if outcome.status == "confirm" or confirm_pref == "always":
                alternatives = outcome.alternatives or (outcome.matches if multi else [])
                return out + self._request_confirm(evidence, value, ev.text, outcome.match, alternatives)
            return out + self._accept(
                ev.field_id,
                value,
                source="speech",
                confidence=ev.confidence,
                raw=evidence.raw_transcript,
                matched=outcome.match,
                evidence=evidence,
            )

        # Free-form answer — FEAT-653 typed post-processors, then the decision matrix
        if not ev.text.strip():
            return out + [AnswerRejected(field_id=ev.field_id, error="Empty transcript", code="EMPTY")]
        result = normalize_spoken(field.field_type, ev.text, ctx=self._normalize_ctx()) if meta.normalize else None
        candidate = result if result is not None else NormalizeResult.accepted(ev.text)
        refined_by = "rules" if result is not None else None
        if self._llm_refine_enabled(field, meta):
            request_id = uuid.uuid4().hex
            self._refining = _PendingRefine(
                evidence=evidence, rules=candidate, rules_by=refined_by, request_id=request_id
            )
            return out + [
                RefineValue(
                    field_id=ev.field_id,
                    request_id=request_id,
                    transcript=ev.text,
                    candidate=candidate.value,
                    field_type=field.field_type.value,
                    label=q.label,
                    today=self._normalize_ctx().now.date().isoformat(),
                )
            ]
        return out + self._gate(evidence, candidate, refined_by=refined_by, llm_confidence=None)

    def _request_confirm(
        self,
        evidence: AudioAnswer,
        value: Any,
        transcript: str,
        matched: OptionMatch | None,
        alternatives: list[OptionMatch],
        *,
        refined_by: str | None = None,
        llm_confidence: float | None = None,
    ) -> list[Outbound]:
        """Park the answer in ``state.pending`` and ask the client to confirm it."""
        sensitive = is_sensitive(self._fields[evidence.field_id])
        self.state.pending = evidence.model_copy(
            update={"value": value, "matched": matched, "normalized_by": refined_by, "llm_confidence": llm_confidence}
        )
        self.state.phase = Phase.CONFIRMING
        return [
            ConfirmRequest(
                field_id=evidence.field_id,
                transcript=_SENSITIVE_MASK if sensitive else transcript,
                confidence=evidence.confidence,
                matched=matched,
                alternatives=alternatives or None,
                value=None if (sensitive or refined_by is None) else value,
                refined_by=refined_by,
            )
        ]

    def _gate(
        self,
        evidence: AudioAnswer,
        candidate: NormalizeResult,
        *,
        refined_by: str | None,
        llm_confidence: float | None,
    ) -> list[Outbound]:
        """Single reject/confirm/accept decision: the §2 decision matrix, nothing else."""
        field = self._fields[evidence.field_id]
        meta = field_voice_meta(field, logger=self.logger)
        sensitive = is_sensitive(field)
        transcript = evidence.raw_transcript or ""
        if candidate.status == "rejected":
            is_email = field.field_type == FieldType.EMAIL
            return [
                AnswerRejected(
                    field_id=evidence.field_id,
                    error=self.narrator.render("invalid_email" if is_email else "invalid_value"),
                    code="INVALID_EMAIL" if is_email else "INVALID_VALUE",
                    value=None if sensitive else candidate.value,
                )
            ]
        if candidate.status == "confirm":
            return self._request_confirm(
                evidence, candidate.value, transcript, None, [], refined_by=refined_by, llm_confidence=llm_confidence
            )
        confidence = 1.0 if evidence.confidence is None else evidence.confidence
        stt_low = confidence < self.cfg.stt_confirm_threshold and meta.confirm != "never"
        llm_low = refined_by == "llm" and (llm_confidence or 0.0) < self.cfg.llm_refine_threshold
        if meta.confirm == "always" or stt_low or llm_low:
            return self._request_confirm(
                evidence, candidate.value, transcript, None, [], refined_by=refined_by, llm_confidence=llm_confidence
            )
        return self._accept(
            evidence.field_id,
            candidate.value,
            source="speech",
            confidence=evidence.confidence,
            raw=evidence.raw_transcript,
            evidence=evidence,
            normalized_by=refined_by,
            llm_confidence=llm_confidence,
        )

    def _accept(
        self,
        field_id: str,
        value: Any,
        *,
        source: str,
        confidence: float | None = None,
        raw: str | None = None,
        matched: OptionMatch | None = None,
        evidence: AudioAnswer | None = None,
        normalized_by: str | None = None,
        llm_confidence: float | None = None,
    ) -> list[Outbound]:
        """Single acceptance funnel: bump version, store, ack, StoreBlob for speech, then Replan."""
        prev = self.state.answers.get(field_id)
        version = (prev.version + 1) if prev is not None else 1
        extra: dict[str, Any] = {}
        if evidence is not None:
            extra = {
                "audio_mime": evidence.audio_mime,
                "audio_bytes_len": evidence.audio_bytes_len,
                "duration_ms": evidence.duration_ms,
                "stt_language": evidence.stt_language,
            }
        answer = AudioAnswer(
            field_id=field_id,
            field_uid=self._fields[field_id].field_uid,
            value=value,
            source=source,
            confidence=confidence,
            raw_transcript=raw,
            normalized_by=normalized_by,
            llm_confidence=llm_confidence,
            matched=matched,
            version=version,
            **extra,
        )
        self.state.answers[field_id] = answer
        self._skipped.discard(field_id)
        self.state.pending = None
        self.state.phase = Phase.ACCEPTING
        out: list[Outbound] = [
            AnswerAccepted(field_id=field_id, source=source, value=self._echo(field_id, value), matched=matched)
        ]
        if (
            source == "speech"
            and self.cfg.store_recordings
            and self._last_audio
            and self._last_audio[0] == field_id
            and not is_sensitive(self._fields[field_id])
        ):
            _, audio, mime = self._last_audio
            out.append(StoreBlob(field_id=field_id, audio=audio, mime=mime or "audio/webm", version=version))
        self._last_audio = None
        return out + [self._save(), Replan()]

    def _llm_refine_enabled(self, field: FormField, meta: FieldVoiceMeta) -> bool:
        """meta.llm_refine if not None else cfg.llm_refine_values; False for sensitive fields and for any type
        outside REFINABLE_TYPES = {EMAIL, PHONE, NUMBER, INTEGER, DATE, TIME, DATETIME}."""
        wanted = meta.llm_refine if meta.llm_refine is not None else self.cfg.llm_refine_values
        if not wanted or is_sensitive(field):
            return False
        if field.field_type not in REFINABLE_TYPES:
            if meta.llm_refine and field.field_id not in self._refine_warned:
                self._refine_warned.add(field.field_id)
                self.logger.warning(
                    "llm_refine ignored for field %s: type %s is not refinable", field.field_id, field.field_type.value
                )
            return False
        return True

    def on_value_refined(self, ev: ValueRefined) -> list[Outbound]:
        """Drop when stale (no in-flight refine, field or request_id mismatch); else re-normalize and _gate."""
        pending = self._refining
        if pending is None or ev.request_id != pending.request_id or ev.field_id != pending.evidence.field_id:
            return []
        self._refining = None
        if self.state.cursor != ev.field_id:
            return []
        field = self._fields[ev.field_id]
        if ev.status == "ok" and ev.value is not None:
            renorm = normalize_spoken(field.field_type, ev.value, ctx=self._normalize_ctx())
            if renorm is not None and renorm.status != "rejected":
                return self._gate(
                    pending.evidence,
                    renorm,
                    refined_by="llm",
                    llm_confidence=ev.confidence if ev.confidence is not None else 0.0,
                )
        return self._gate(pending.evidence, pending.rules, refined_by=pending.rules_by, llm_confidence=None)

    def _normalize_ctx(self) -> NormalizeContext:
        """now = clock() in ZoneInfo(state.timezone) when valid, else UTC with timezone_known=False."""
        now = self._clock()
        tz_name = self.state.timezone
        if tz_name:
            try:
                return NormalizeContext(
                    lexicon=self.lexicon, now=now.astimezone(ZoneInfo(tz_name)), timezone_known=True
                )
            except Exception:  # noqa: BLE001 — invalid/unknown zone: degrade, never fail the turn
                self.logger.debug("invalid session timezone %r; using UTC", tz_name)
        return NormalizeContext(lexicon=self.lexicon, now=now.astimezone(timezone.utc), timezone_known=False)

    def _is_empty(self, value: Any) -> bool:
        return (
            value is None
            or (isinstance(value, str) and not value.strip())
            or (isinstance(value, (list, dict)) and not value)
        )

    def on_text(self, ev: AnswerText) -> list[Outbound]:
        """Typed answer for the cursor field."""
        bad = self._guard(ev.field_id)
        if bad is not None:
            return bad
        if self.planner.effective_required(ev.field_id) and not ev.value.strip():
            return [AnswerRejected(field_id=ev.field_id, error="This field is required", code="REQUIRED")]
        code = validate_typed(self._fields[ev.field_id].field_type, ev.value)
        if code is not None:
            return [AnswerRejected(field_id=ev.field_id, error=self.narrator.render("invalid_email"), code=code)]
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
        if self._stop_prev_phase is not None:
            prev, self._stop_prev_phase = self._stop_prev_phase, None
            if ev.confirmed:
                return self.on_end(EndSession(type="end_session"))
            self.state.phase = prev
            if prev is Phase.REVIEW:
                return [ReviewPrompt(text=self.narrator.render("review_all_correct"))]
            cursor = self.state.cursor
            return [self._question(cursor)] if cursor is not None else []
        pending = self.state.pending
        if pending is None:
            return [Error(code="NO_PENDING_ANSWER", message="No answer is awaiting confirmation")]
        if ev.field_id and ev.field_id != pending.field_id:
            return [
                Error(
                    code="FIELD_MISMATCH",
                    message=f"confirm_answer for '{ev.field_id}' but the pending answer is for "
                    f"'{pending.field_id}'",
                )
            ]
        self.state.pending = None
        if ev.confirmed:
            return self._accept(
                pending.field_id,
                pending.value,
                source="speech",
                confidence=pending.confidence,
                raw=pending.raw_transcript,
                matched=pending.matched,
                evidence=pending,
                normalized_by=pending.normalized_by,
                llm_confidence=pending.llm_confidence,
            )
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
            return [
                AnswerRejected(field_id=cursor, error="This field is required and cannot be skipped", code="REQUIRED")
            ]
        self._skipped.add(cursor)
        self.state.pending = None
        self._last_audio = None
        self.state.phase = Phase.ACCEPTING
        return [QuestionSkipped(field_id=cursor, reason="user"), self._save(), Replan()]

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
            del self.state.history[self.state.history.index(dest) + 1 :]
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
        """End the session immediately and delete every stored recording (S8)."""
        self._stop_prev_phase = None
        self.state.pending = None
        out: list[Outbound] = []
        for answer in self.state.answers.values():
            if answer.blob_ref:
                out.append(DeleteBlob(blob_ref=answer.blob_ref))
                answer.blob_ref = None
        self.state.phase = Phase.ABORTED
        return out + [SessionEnded(session_id=self.state.session_id)]

    def _request_stop_confirm(self) -> list[Outbound]:
        """A spoken STOP is easy to mis-hear: ask yes/no (reusing the confirm turn) before ending."""
        self._stop_prev_phase = self.state.phase
        self.state.phase = Phase.CONFIRMING
        return [ConfirmRequest(field_id=self.state.cursor or "", transcript="stop", purpose="stop")]

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
                return [
                    ack,
                    AnswerRejected(
                        field_id=cursor, error="This field is required and cannot be skipped", code="REQUIRED"
                    ),
                ]
            return [ack] + self.on_skip(SkipQuestion(type="skip_question"))
        if cmd is VoiceCommand.HELP:
            return [ack] + self.on_repeat(RepeatQuestion(type="repeat_question"))
        if cmd is VoiceCommand.STOP:
            return [ack] + self._request_stop_confirm()
        if cmd in (VoiceCommand.YES, VoiceCommand.NO):
            return [ack] + self.on_confirm(
                ConfirmAnswer(type="confirm_answer", field_id=cursor or "", confirmed=cmd is VoiceCommand.YES)
            )
        return [Error(code="COMMAND_NOT_AVAILABLE", message=f"Command '{cmd.value}' is not available here")]

    def _review_enabled(self) -> bool:
        """True when the session goes through PLAUSIBILITY/REVIEW before submitting (v2 and review != never)."""
        return self.state.protocol_version >= 2 and self.cfg.review != "never"

    def _on_plan_exhausted(self) -> list[Outbound]:
        """No cursor left: v1/never → submit; otherwise PLAUSIBILITY (if enabled) then REVIEW.

        ``cfg.review == "ask"`` behaves like ``"always"`` here: the review prompt itself is the question the user
        answers with "yes/send" (submit) or "change N" (edit), so no separate yes/no turn is added.
        """
        fields = self._plausibility_fields(set(self.state.answers))
        if not self._review_enabled():
            if fields:
                # AC11: review "never" / v1 still run the check before the Submit.
                self.state.cursor = None
                self._pl_requested = set(fields)
                self.state.phase = Phase.PLAUSIBILITY
                return [RunPlausibility(fields=fields), self._save()]
            return self._submit()
        self.state.cursor = None
        if fields:
            self._pl_requested = set(fields)
            self.state.phase = Phase.PLAUSIBILITY
            return [RunPlausibility(fields=fields), self._save()]
        return self._start_review(report=None)

    def _plausibility_fields(self, candidates: set[str]) -> set[str]:
        """Answered, LLM-enabled (field-level opt-in included), non-sensitive fields (S8: sensitive never sent)."""
        return {
            fid
            for fid in candidates
            if fid in self._fields
            and fid in self.state.answers
            and llm_validation_enabled(self.form, self._fields[fid])
            and not is_sensitive(self._fields[fid])
        }

    def on_plausibility_done(self, ev: PlausibilityDone) -> list[Outbound]:
        """Merge the (full or delta) report; flag low confidence once per answer version; (re)enter REVIEW."""
        if self.state.phase != Phase.PLAUSIBILITY:
            return [Error(code="WRONG_PHASE", message="No plausibility check is pending")]
        report: PlausibilityReport = ev.report
        requested, self._pl_requested = self._pl_requested, None
        if report.status == "blocked":
            self._pl_unchecked |= requested or set()
            if not self._review_enabled():
                if self._llm.on_error != "block":
                    return self._submit()
                # No review to retry from: re-ask the last question; plan exhaustion re-runs the check.
                out = [Error(code="PLAUSIBILITY_UNAVAILABLE", message=report.reason or "plausibility unavailable")]
                last = self.state.plan[-1] if self.state.plan else None
                if last is None:
                    return out
                self.state.cursor = last
                self.state.phase = Phase.ASKING
                return out + self._ask(last)
            # Retryable and never stored: stay in REVIEW; review_confirm re-runs the check (AC13).
            out = [Error(code="PLAUSIBILITY_UNAVAILABLE", message=report.reason or "plausibility unavailable")]
            return out + self._start_review(report=None)
        self._pl_unchecked -= requested or set()
        current = self.state.plausibility
        if current is None:
            merged = report.model_copy(update={"items": {}})
        else:
            merged = current.model_copy(
                update={
                    "status": report.status,
                    "reason": report.reason,
                    "model": report.model,
                    "threshold": report.threshold,
                    "latency_ms": report.latency_ms,
                    "items": dict(current.items),
                }
            )
        for fid in requested or set():
            merged.items.pop(fid, None)
        for fid in list(merged.items):
            if fid not in self.state.answers:
                merged.items.pop(fid)
        threshold = self._llm.threshold
        for fid, verdict in report.items.items():
            answer = self.state.answers.get(fid)
            if answer is None or fid not in self._fields or is_sensitive(self._fields[fid]):
                continue
            merged.items[fid] = verdict
            if (not verdict.plausible or verdict.confidence < threshold) and fid not in self._flagged_now():
                if self.state.flagged.get(fid) != answer.version:
                    self.state.flagged[fid] = answer.version
        self.state.plausibility = merged
        if not self._review_enabled():
            return self._submit()
        return self._start_review(report=report)

    def _flagged_now(self) -> set[str]:
        """Fields whose current answer version is already flagged (never flagged twice)."""
        return {
            fid
            for fid, ver in self.state.flagged.items()
            if fid in self.state.answers and self.state.answers[fid].version == ver
        }

    def _review_items(self) -> list[ReviewItemData]:
        """Review rows for the visible plan (positions kept, ``skip_in_review`` fields omitted)."""
        items: list[ReviewItemData] = []
        for pos, fid in enumerate(self.state.plan, start=1):
            if fid not in self._fields or field_voice_meta(self._fields[fid], logger=self.logger).skip_in_review:
                continue
            items.append(self._review_item(pos, fid))
        return items

    def _start_review(self, *, report: PlausibilityReport | None) -> list[Outbound]:
        """Build ReviewItemData for the visible plan; emit PlausibilityResult?, ReviewStart, items, ReviewPrompt."""
        self.state.phase = Phase.REVIEW
        self.state.return_to_review = False
        self.state.cursor = None
        self.state.review_cursor = 0
        items = self._review_items()
        out: list[Outbound] = []
        if report is not None:
            out.append(PlausibilityResult(status=report.status, items=report.items, reason=report.reason))
        out.append(ReviewStart(items=items))
        out.extend(ReviewItem(item=it) for it in items)
        plan = self.narrator.plan_review(items, self.cfg)
        segments = dict(plan.segments)
        text_parts = [plan.text]
        for it in items:
            if it.flagged and not it.skipped and not it.sensitive:
                flag = self.narrator.render("plausibility_flag", label=it.label)
                segments[f"review:flag:{it.position}"] = flag
                text_parts.append(flag)
        closing = self.narrator.render("review_all_correct")
        segments["review:close"] = closing
        text_parts.append(closing)
        out.append(Synthesize(keys=list(segments), texts=segments))
        out.append(ReviewPrompt(text=" ".join(text_parts)))
        return out + [self._save()]

    def _review_item(self, position: int, field_id: str) -> ReviewItemData:
        """One review row; sensitive answers read "[hidden]" (S8)."""
        ans = self.state.answers.get(field_id)
        field = self._fields[field_id]
        sensitive = is_sensitive(field)
        text = _SENSITIVE_MASK if sensitive else ("" if ans is None else self._display(field, ans.value))
        flagged = ans is not None and field_id in self._flagged_now()
        return ReviewItemData(
            position=position,
            field_id=field_id,
            label=self._questions[field_id].label,
            answer_text=text,
            skipped=ans is None,
            flagged=flagged,
            sensitive=sensitive,
        )

    def _display(self, field: FormField, value: Any) -> str:
        """Human-readable answer: option labels, yes/no for booleans, lists joined with the locale conjunction."""
        q = self._questions.get(field.field_id)
        labels = {str(o.get("value")): str(o.get("label", o.get("value"))) for o in ((q.options if q else None) or [])}

        def one(v: Any) -> str:
            if isinstance(v, bool) and str(v) not in labels:
                words = self.lexicon.yes if v else self.lexicon.no
                return words[0] if words else ("yes" if v else "no")
            return labels.get(str(v), str(v))

        if isinstance(value, (list, tuple)):
            parts = [one(v) for v in value]
            if len(parts) > 1:
                conj = self.lexicon.conjunctions[0] if self.lexicon.conjunctions else "and"
                return f"{', '.join(parts[:-1])} {conj} {parts[-1]}"
            return parts[0] if parts else ""
        return one(value)

    def on_review_confirm(self, ev: ReviewConfirm) -> list[Outbound]:
        """Confirmed → SUBMITTING + Submit (low confidence never blocks); not confirmed → re-read the review."""
        if self.state.phase != Phase.REVIEW:
            return [Error(code="WRONG_PHASE", message="Nothing to review right now")]
        if not ev.confirmed:
            return self._start_review(report=None)
        if self._llm.on_error == "block":
            # AC13: a blocked (or never-run, e.g. after a resume) check must pass before anything is stored.
            fields = self._plausibility_fields(set(self.state.answers))
            pending = (self._pl_unchecked & fields) or (fields if self.state.plausibility is None else set())
            if pending:
                self._pl_requested = set(pending)
                self.state.phase = Phase.PLAUSIBILITY
                return [RunPlausibility(fields=pending), self._save()]
        # The snapshot goes BEFORE the Submit: FormComplete deletes it, so a later save would lose its CAS.
        submit = self._submit()
        return [self._save(), *submit]

    def _submit(self) -> list[Outbound]:
        """SUBMITTING + Submit carrying the plausibility report (low confidence never blocks)."""
        self.state.phase = Phase.SUBMITTING
        context = self._submission_context()
        if self.state.plausibility is not None:
            context["llm_validation"] = self.state.plausibility.model_dump(mode="json")
        return [Submit(data=self._submission_data(), context=context)]

    def on_review_edit(self, ev: ReviewEdit) -> list[Outbound]:
        """Re-ask one field from the review; its acceptance returns to the review via a delta plausibility batch."""
        if self.state.phase != Phase.REVIEW:
            return [Error(code="WRONG_PHASE", message="Nothing to review right now")]
        if ev.field_id not in self.state.plan or ev.field_id not in self._fields:
            return [Error(code="WRONG_FIELD", message=f"'{ev.field_id}' is not part of the review")]
        self.state.return_to_review = True
        self.state.phase = Phase.REVIEW_EDITING
        self.state.cursor = ev.field_id
        self.state.pending = None
        self._last_audio = None
        if ev.field_id in self.state.history:
            del self.state.history[self.state.history.index(ev.field_id) + 1 :]
        else:
            self.state.history.append(ev.field_id)
        self.state.phase = Phase.ASKING
        return self._ask(ev.field_id) + [self._save()]

    def on_review_prompt_answer(self, ev: TranscriptReady) -> list[Outbound]:
        """Spoken turn during REVIEW: confirm phrases → submit; "change N"/label → edit; else re-read."""
        norm = normalize(ev.text, self.lexicon)
        confirm = {normalize(p, self.lexicon) for p in self.lexicon.review_confirm}
        if norm and norm in confirm:
            return self.on_review_confirm(ReviewConfirm(type="review_confirm", confirmed=True))
        items = self._review_items()
        position = match_review_item(ev.text, items, self.lexicon)
        if position is not None:
            target = next((it for it in items if it.position == position), None)
            if target is not None:
                return self.on_review_edit(ReviewEdit(type="review_edit", field_id=target.field_id))
        cmd = classify_command(ev.text, lexicon=self.lexicon, phase=Phase.REVIEW)
        if cmd in (VoiceCommand.SEND, VoiceCommand.YES):
            return [CommandAck(command=cmd.value)] + self.on_review_confirm(
                ReviewConfirm(type="review_confirm", confirmed=True)
            )
        if cmd is VoiceCommand.STOP:
            return [CommandAck(command=cmd.value)] + self._request_stop_confirm()
        if cmd is not None:
            return [CommandAck(command=cmd.value), ReviewPrompt(text=self.narrator.render("review_all_correct"))]
        return [ReviewPrompt(text=self.narrator.render("review_all_correct"))]

    # ---- snapshot / resume ---------------------------------------------
    def _save(self) -> SaveSnapshot:
        """SaveSnapshot request for the current state (sensitive values are never included)."""
        return SaveSnapshot(snapshot=self.snapshot().model_dump(mode="json"))

    def snapshot(self) -> AudioSnapshot:
        """Serializable state for AudioSessionStore (no audio bytes, no trusted plausibility).

        Sensitive answers keep only their evidence shell (value and transcript dropped, S8), so a resumed session
        re-asks them. The skipped optional fields travel under ``answer_meta["_skipped"]``. ``revision`` is owned
        by the store (compare-and-set) and left at 0.
        """
        meta: dict[str, dict[str, Any]] = {}
        blobs: dict[str, str] = {}
        for fid, ans in self.state.answers.items():
            dump = ans.model_dump(mode="json")
            if fid in self._fields and is_sensitive(self._fields[fid]):
                dump["value"] = None
                dump["raw_transcript"] = None
            meta[fid] = dump
            if ans.blob_ref:
                blobs[fid] = ans.blob_ref
        meta[_SKIPPED_META_KEY] = {"fields": sorted(self._skipped)}
        return AudioSnapshot(
            form_version=self.form.version,
            phase=self.state.phase,
            cursor=self.state.cursor,
            history=list(self.state.history),
            review_cursor=self.state.review_cursor,
            return_to_review=self.state.return_to_review,
            locale=self.state.locale,
            config=self.cfg,
            blob_refs=blobs,
            answer_meta=meta,
            plausibility=None,
            flagged=dict(self.state.flagged),
            submission_id=self.state.submission_id,
            user_id=self.state.user_id,
            tenant=self.state.tenant,
        )

    @classmethod
    def from_snapshot(cls, snap: AudioSnapshot, **deps: Any) -> "AudioFormSession":
        """Rebuild a session shell from a snapshot; the caller then feeds ``StartSession(resume_session_id=…)``.

        ``deps`` are the regular constructor arguments (``state`` carries the *current* caller identity). The
        saved data is validated and applied by ``on_start`` so identity checks see both sides.
        """
        session = cls(**deps)
        session._resume_snap = snap
        return session

    def _check_resume(
        self, ev: StartSession, snap_user: str, snap_tenant: str | None, snap_form_version: str
    ) -> list[Outbound]:
        """RESUME_FORBIDDEN on user/tenant mismatch; RESUME_STALE on form changes; [] when resumable."""
        if snap_user != self.state.user_id or snap_tenant != self.state.tenant:
            return [Error(code="RESUME_FORBIDDEN", message="Session cannot be resumed")]
        if snap_form_version != self.form.version:
            return [Error(code="RESUME_STALE", message="The form changed since this session was saved")]
        return []

    def _valid_saved_answer(self, fid: str, ans: AudioAnswer) -> bool:
        """Whether a saved answer still fits the current form (known field, uid, value, option)."""
        field = self._fields.get(fid)
        if field is None or ans.value is None:
            return False
        if ans.field_uid is not None and field.field_uid is not None and ans.field_uid != field.field_uid:
            return False
        q = self._questions.get(fid)
        options = [o.get("value") for o in (q.options or [])] if q is not None else []
        if options and field.field_type != FieldType.BOOLEAN:
            values = ans.value if isinstance(ans.value, list) else [ans.value]
            return all(v in options for v in values)
        return True

    def _resume(self, ev: StartSession) -> list[Outbound]:
        """Validate and apply the saved snapshot, then re-plan (always) and announce ``SessionResumed``."""
        snap = self._resume_snap
        if snap is None:
            return [Error(code="RESUME_FORBIDDEN", message="Session cannot be resumed")]
        bad = self._check_resume(ev, snap.user_id, snap.tenant, snap.form_version)
        if bad:
            return bad
        out: list[Outbound] = []
        skipped = set((snap.answer_meta.get(_SKIPPED_META_KEY) or {}).get("fields", []))
        answers: dict[str, AudioAnswer] = {}
        for fid, raw in snap.answer_meta.items():
            if fid == _SKIPPED_META_KEY:
                continue
            blob = snap.blob_refs.get(fid)
            try:
                ans = AudioAnswer.model_validate({**raw, "blob_ref": raw.get("blob_ref") or blob})
            except ValueError:
                ans = None
            if ans is None or not self._valid_saved_answer(fid, ans):
                self.logger.info("engine: resume dropped stale answer field=%s", fid)
                if blob:
                    out.append(DeleteBlob(blob_ref=blob))
                if fid in self._fields:
                    out.append(AnswerCleared(field_id=fid))
                continue
            answers[fid] = ans
        self.state.session_id = ev.resume_session_id or self.state.session_id
        self.state.answers = answers
        self._skipped = {f for f in skipped if f in self._fields and f not in answers}
        self.state.history = [f for f in snap.history if f in answers or f in self._skipped]
        self.state.flagged = {f: v for f, v in snap.flagged.items() if f in answers and answers[f].version == v}
        self.state.review_cursor = snap.review_cursor
        self.state.return_to_review = False
        self.state.submission_id = snap.submission_id
        self.state.locale = ev.locale
        self.state.timezone = ev.timezone
        self.state.protocol_version = ev.protocol_version
        self.state.pending = None
        self._refining = None
        self.state.plausibility = None
        self.state.cursor = None
        self.state.plan = []
        self._last_audio = None
        self._resume_snap = None
        self.state.phase = Phase.PLANNING
        return [
            SessionResumed(
                session_id=self.state.session_id, phase=snap.phase, cursor=snap.cursor, answered=list(answers)
            ),
            *out,
            Replan(),
        ]

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
            return [
                FormComplete(
                    submission_id=str(outcome.get("submission_id") or self.state.submission_id),
                    stored_in=outcome.get("stored_in"),
                    answers={
                        fid: self._echo(fid, a.value)
                        for fid, a in self.state.answers.items()
                        if fid in self._fields and a.value is not None
                    },
                    plausibility_summary=None,
                )
            ]
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
            self.state.return_to_review = self._review_enabled()
            self.state.phase = Phase.ASKING
            if first in self.state.history:
                del self.state.history[self.state.history.index(first) + 1 :]
            else:
                self.state.history.append(first)
            out.extend(self._ask(first))
        return out

    def _submission_data(self) -> dict[str, Any]:
        """Scalars per answered field, with speech answers re-folded into voice evidence envelopes."""
        scalars = {fid: a.value for fid, a in self.state.answers.items() if fid in self._fields and a.value is not None}
        # S8: a sensitive spoken answer is submitted as the plain scalar — never wrapped, never recorded.
        return wrap_voice(
            scalars,
            {fid: a for fid, a in self.state.answers.items() if fid in scalars and not is_sensitive(self._fields[fid])},
        )

    def _submission_context(self) -> dict[str, Any]:
        """Context handed to the submission pipeline."""
        return {
            "channel": "audio",
            "session_id": self.state.session_id,
            "locale": self.state.locale,
            "submission_id": self.state.submission_id,
        }

    def _echo(self, field_id: str, value: Any) -> Any:
        """Value echoed back to the client — masked for sensitive fields (S8)."""
        return _SENSITIVE_MASK if is_sensitive(self._fields[field_id]) else value
