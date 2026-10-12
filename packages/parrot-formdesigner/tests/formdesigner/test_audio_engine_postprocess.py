"""FEAT-653 TASK-4251 — engine: typed post-processors, decision matrix, provenance, timezone."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from parrot_formdesigner.audio.engine import AudioFormSession
from parrot_formdesigner.audio.events import (
    AnswerAccepted,
    AnswerRejected,
    AnswerText,
    ConfirmAnswer,
    ConfirmRequest,
    PlanReady,
    StartSession,
    TranscriptReady,
)
from parrot_formdesigner.audio.models import AudioFormManifest, AudioSessionState
from parrot_formdesigner.audio.narration.engine import Narrator
from parrot_formdesigner.audio.narration.lexicon import load_lexicon
from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.core.voice import VoiceFormConfig
from parrot_formdesigner.renderers.audio import AudioFormRenderer
from parrot_formdesigner.services.rule_evaluator import RuleResolution

NOW = datetime(2026, 10, 12, 15, 0, tzinfo=timezone.utc)  # Monday


def _deps(form: FormSchema, locale: str, cfg: VoiceFormConfig | None) -> dict:
    questions = AudioFormRenderer().split_into_questions(form, locale=locale)
    manifest = AudioFormManifest(
        form_uid=str(form.form_uid),
        title="F",
        total_questions=len(questions),
        questions=questions,
        ws_endpoint="/ws",
        locale=locale,
    )
    state = AudioSessionState(session_id="sess", form_uid=str(form.form_uid), user_id="u", manifest=manifest)
    return dict(
        form=form,
        manifest=manifest,
        cfg=cfg or VoiceFormConfig(max_questions=None),
        narrator=Narrator(locale),
        lexicon=load_lexicon(locale),
        state=state,
        llm_cfg=None,
        clock=lambda: NOW,
    )


def _form(fields: list[FormField]) -> FormSchema:
    return FormSchema(form_id="f", title="F", sections=[FormSection(section_id="s1", title="S", fields=fields)])


def _plan(s: AudioFormSession, locale: str) -> None:
    plan, delta = asyncio.run(s.planner.replan(s.state.answers, locale=locale, resolution=RuleResolution()))
    s.handle(PlanReady(type="_plan_ready", plan=plan, delta=delta.model_dump()))


def _start_ev(s: AudioFormSession, locale: str, tz: str | None, resume: str | None = None) -> StartSession:
    return StartSession(
        type="start_session",
        form_uid=s.state.form_uid,
        locale=locale,
        protocol_version=2,
        timezone=tz,
        resume_session_id=resume,
    )


def _build(
    fields: list[FormField], *, tz: str | None = "America/New_York", locale: str = "en", cfg=None
) -> AudioFormSession:
    s = AudioFormSession(**_deps(_form(fields), locale, cfg))
    s.handle(_start_ev(s, locale, tz))
    _plan(s, locale)
    return s


def _tr(field_id: str, text: str, confidence: float | None = 0.95) -> TranscriptReady:
    return TranscriptReady(
        type="_transcript",
        field_id=field_id,
        text=text,
        confidence=confidence,
        audio_mime="audio/webm",
        audio_bytes_len=3,
    )


def _f(fid: str, ft: FieldType, **kw) -> FormField:
    return FormField(field_id=fid, field_type=ft, label=fid.title(), required=True, **kw)


class TestFreeFormNormalization:
    def test_phone_stored_canonical_with_provenance(self) -> None:
        s = _build([_f("phone", FieldType.PHONE)])
        out = s.handle(_tr("phone", "0,4,12,523,573"))
        acc = next(o for o in out if isinstance(o, AnswerAccepted))
        assert acc.value == "0412523573"
        ans = s.state.answers["phone"]
        assert ans.raw_transcript == "0,4,12,523,573" and ans.normalized_by == "rules"

    def test_text_field_unchanged(self) -> None:
        s = _build([_f("name", FieldType.TEXT)])
        out = s.handle(_tr("name", "en Manuel"))
        assert next(o for o in out if isinstance(o, AnswerAccepted)).value == "en Manuel"
        assert s.state.answers["name"].normalized_by is None

    def test_normalize_off_keeps_raw_text(self) -> None:
        s = _build([_f("phone", FieldType.PHONE, meta={"voice": {"normalize": False}})])
        out = s.handle(_tr("phone", "0,4,12,523,573"))
        assert next(o for o in out if isinstance(o, AnswerAccepted)).value == "0,4,12,523,573"
        assert s.state.answers["phone"].normalized_by is None


class TestDecisionMatrix:
    def test_rejected_email_reasks_with_candidate(self) -> None:
        s = _build([_f("email", FieldType.EMAIL)])
        out = s.handle(_tr("email", "john at gmail"))
        rej = next(o for o in out if isinstance(o, AnswerRejected))
        assert rej.code == "INVALID_EMAIL" and rej.value == "john@gmail"
        assert "email" not in s.state.answers and s.state.cursor == "email" and s.state.pending is None

    def test_rejected_other_type_is_invalid_value(self) -> None:
        s = _build([_f("n", FieldType.NUMBER)])
        rej = next(o for o in s.handle(_tr("n", "hello there")) if isinstance(o, AnswerRejected))
        assert rej.code == "INVALID_VALUE" and "n" not in s.state.answers

    def test_confirm_status_confirms_even_with_never(self) -> None:
        s = _build([_f("t", FieldType.TIME, meta={"voice": {"confirm": "never"}})])
        out = s.handle(_tr("t", "three thirty"))
        cr = next(o for o in out if isinstance(o, ConfirmRequest))
        assert cr.value == "03:30" and cr.refined_by == "rules"

    def test_confirm_always_confirms_accepted_value(self) -> None:
        s = _build([_f("n", FieldType.NUMBER, meta={"voice": {"confirm": "always"}})])
        cr = next(o for o in s.handle(_tr("n", "twenty five")) if isinstance(o, ConfirmRequest))
        assert cr.value == 25

    def test_low_stt_confirms_accepted_value(self) -> None:
        s = _build([_f("n", FieldType.NUMBER)])
        out = s.handle(_tr("n", "twenty five", confidence=0.2))
        assert next(o for o in out if isinstance(o, ConfirmRequest)).value == 25

    def test_low_stt_with_never_accepts(self) -> None:
        s = _build([_f("n", FieldType.NUMBER, meta={"voice": {"confirm": "never"}})])
        out = s.handle(_tr("n", "twenty five", confidence=0.2))
        assert next(o for o in out if isinstance(o, AnswerAccepted)).value == 25

    def test_provenance_survives_confirm(self) -> None:
        s = _build([_f("n", FieldType.NUMBER)])
        s.handle(_tr("n", "twenty five", confidence=0.2))
        s.handle(ConfirmAnswer(type="confirm_answer", field_id="n", confirmed=True))
        assert s.state.answers["n"].value == 25 and s.state.answers["n"].normalized_by == "rules"

    def test_relative_date_without_timezone_confirms(self) -> None:
        s = _build([_f("d", FieldType.DATE)], tz=None)
        out = s.handle(_tr("d", "tomorrow"))
        assert next(o for o in out if isinstance(o, ConfirmRequest)).value == "2026-10-13"

    def test_relative_date_with_timezone_accepts(self) -> None:
        s = _build([_f("d", FieldType.DATE)])
        out = s.handle(_tr("d", "tomorrow"))
        assert next(o for o in out if isinstance(o, AnswerAccepted)).value == "2026-10-13"

    def test_raw_text_confirmation_keeps_legacy_wire_shape(self) -> None:
        s = _build([_f("name", FieldType.TEXT)])
        cr = next(o for o in s.handle(_tr("name", "Ana", confidence=0.1)) if isinstance(o, ConfirmRequest))
        assert cr.value is None and cr.refined_by is None


class TestSensitive:
    def test_sensitive_rejection_and_confirm_omit_value(self) -> None:
        s = _build([_f("ssn", FieldType.PHONE, meta={"voice": {"sensitive": True}})])
        rej = next(o for o in s.handle(_tr("ssn", "12")) if isinstance(o, AnswerRejected))
        assert rej.value is None
        s2 = _build([_f("ssn", FieldType.PHONE, meta={"voice": {"sensitive": True}})])
        cr = next(
            o for o in s2.handle(_tr("ssn", "five five five oh one two three", 0.1)) if isinstance(o, ConfirmRequest)
        )
        assert cr.value is None and cr.transcript == "[hidden]"


class TestTypedAndResume:
    def test_typed_email_rejected_typed_phone_kept(self) -> None:
        s = _build([_f("email", FieldType.EMAIL), _f("phone", FieldType.PHONE)])
        out = s.handle(AnswerText(type="answer_text", field_id="email", value="john at gmail"))
        assert next(o for o in out if isinstance(o, AnswerRejected)).code == "INVALID_EMAIL"
        s.handle(AnswerText(type="answer_text", field_id="email", value="john@gmail.com"))
        _plan(s, "en")
        s.handle(AnswerText(type="answer_text", field_id="phone", value="0,4,12"))
        assert s.state.answers["phone"].value == "0,4,12" and s.state.answers["phone"].normalized_by is None

    def test_timezone_recorded_and_resume_takes_new_value(self) -> None:
        fields = [_f("d", FieldType.DATE), _f("p", FieldType.PHONE)]
        s = _build(fields, tz="America/New_York")
        assert s.state.timezone == "America/New_York"
        s.handle(_tr("d", "tomorrow"))
        _plan(s, "en")
        s.handle(_tr("p", "five five five oh one two three"))
        snap = s.snapshot()
        assert snap.answer_meta["p"]["normalized_by"] == "rules"
        r = AudioFormSession.from_snapshot(snap, **_deps(s.form, "en", None))
        r.handle(_start_ev(r, "en", "Europe/Madrid", resume="sess"))
        assert r.state.timezone == "Europe/Madrid"
        assert r.state.answers["p"].normalized_by == "rules"

    def test_submission_envelope_carries_provenance(self) -> None:
        s = _build([_f("phone", FieldType.PHONE)])
        s.handle(_tr("phone", "five five five oh one two three"))
        assert s._submission_data()["phone"]["normalized_by"] == "rules"
