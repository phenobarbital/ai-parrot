"""FEAT-649 TASK-4226 — review, delta plausibility, resume, sensitive policy."""
from __future__ import annotations

import asyncio
import logging

import pytest

from parrot_formdesigner.audio.engine import AudioFormSession
from parrot_formdesigner.audio.events import (
    AnswerText, AudioReceived, Error, FormComplete, PlanReady, PlausibilityDone, Replan, ReviewConfirm, ReviewEdit,
    ReviewPrompt, ReviewStart, RunPlausibility, SaveSnapshot, SessionResumed, StartSession, Submit, SubmitDone,
    TranscriptReady, Transcribe,
)
from parrot_formdesigner.audio.models import AudioFormManifest, AudioSessionState, Phase
from parrot_formdesigner.audio.narration.engine import Narrator
from parrot_formdesigner.audio.narration.lexicon import load_lexicon
from parrot_formdesigner.core.llm_validation import LLMValidationConfig, PlausibilityReport, PlausibilityVerdict
from parrot_formdesigner.core.options import FieldOption
from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.core.voice import VoiceFormConfig
from parrot_formdesigner.renderers.audio import AudioFormRenderer
from parrot_formdesigner.services.rule_evaluator import RuleResolution


def _form() -> FormSchema:
    fields = [
        FormField(field_id="name", field_type=FieldType.TEXT, label="Name", required=True),
        FormField(field_id="color", field_type=FieldType.SELECT, label="Color", required=False,
                  options=[FieldOption(value="r", label="Rojo"), FieldOption(value="g", label="Verde")]),
        FormField(field_id="agree", field_type=FieldType.BOOLEAN, label="Agree", required=False),
        FormField(field_id="pw", field_type=FieldType.PASSWORD, label="Password", required=False),
    ]
    return FormSchema(form_id="f", title="F", sections=[FormSection(section_id="s1", title="S", fields=fields)],
                      llm_validation=LLMValidationConfig(enabled=True))


def _make(form: FormSchema | None = None, *, user: str = "u", tenant: str | None = None, protocol: int = 2,
          snap=None, cfg: VoiceFormConfig | None = None) -> AudioFormSession:
    form = form or _form()
    questions = AudioFormRenderer().split_into_questions(form, locale="es")
    manifest = AudioFormManifest(form_uid=str(form.form_uid), title="F", total_questions=len(questions),
                                 questions=questions, ws_endpoint="/ws", locale="es")
    state = AudioSessionState(session_id="sess", form_uid=str(form.form_uid), user_id=user, tenant=tenant,
                              manifest=manifest)
    deps = dict(form=form, manifest=manifest, cfg=cfg or VoiceFormConfig(max_questions=None),
                narrator=Narrator("es"), lexicon=load_lexicon("es"), state=state, llm_cfg=form.llm_validation)
    if snap is not None:
        return AudioFormSession.from_snapshot(snap, **deps)
    return AudioFormSession(**deps)


def _start(s: AudioFormSession, *, resume: str | None = None, protocol: int = 2) -> list:
    return s.handle(StartSession(type="start_session", form_uid=s.state.form_uid, locale="es",
                                 protocol_version=protocol, resume_session_id=resume))


def _plan_ready(s: AudioFormSession) -> PlanReady:
    plan, delta = asyncio.run(s.planner.replan(s.state.answers, locale="es", resolution=RuleResolution()))
    return PlanReady(type="_plan_ready", plan=plan, delta=delta.model_dump())


def _advance(s: AudioFormSession) -> list:
    return s.handle(_plan_ready(s))


def _answer_all(s: AudioFormSession) -> list:
    """Answer every question by text; returns the outbound list of the last PlanReady."""
    _start(s)
    out = _advance(s)
    answers = {"name": "Ana", "color": "r", "agree": "yes", "pw": "s3cret"}
    for _ in range(10):
        q = next((o for o in out if getattr(o, "type", "") == "question"), None)
        if q is None:
            return out
        s.handle(AnswerText(type="answer_text", field_id=q.field_id, value=answers[q.field_id]))
        out = _advance(s)
    raise AssertionError("did not terminate")


@pytest.fixture
def v2_session() -> AudioFormSession:
    return _make()


def _report(items: dict[str, float], status: str = "ok", plausible: bool = True) -> PlausibilityReport:
    return PlausibilityReport(
        status=status, threshold=0.7,
        items={k: PlausibilityVerdict(plausible=plausible, confidence=v, reason="r") for k, v in items.items()})


def _types(out: list) -> list[str]:
    return [o.type for o in out]


class TestReviewAndResume:
    def test_plan_exhausted_v2_runs_plausibility_then_review(self, v2_session):
        out = _answer_all(v2_session)
        run = next(o for o in out if isinstance(o, RunPlausibility))
        assert v2_session.state.phase == Phase.PLAUSIBILITY
        assert run.fields == {"name", "color", "agree"}
        out = v2_session.handle(PlausibilityDone(type="_plausibility_done", report=_report({"name": 0.9})))
        assert v2_session.state.phase == Phase.REVIEW
        assert any(isinstance(o, ReviewStart) for o in out)
        assert any(isinstance(o, ReviewPrompt) for o in out)
        assert not any(isinstance(o, Submit) for o in out)

    def test_plan_exhausted_v1_submits_directly(self):
        s = _make()
        _start(s, protocol=1)
        out = _advance(s)
        for fid, val in (("name", "Ana"), ("color", "r"), ("agree", "yes"), ("pw", "x")):
            s.handle(AnswerText(type="answer_text", field_id=fid, value=val))
            out = _advance(s)
        # AC11: the check runs before the Submit, even without a review step.
        assert any(isinstance(o, RunPlausibility) for o in out)
        assert not any(isinstance(o, Submit) for o in out)
        out = s.handle(PlausibilityDone(type="_plausibility_done", report=_report({"name": 0.9})))
        assert any(isinstance(o, Submit) for o in out)

    def test_review_never_submits_directly(self):
        s = _make(cfg=VoiceFormConfig(max_questions=None, review="never"))
        out = _answer_all(s)
        assert any(isinstance(o, RunPlausibility) for o in out)
        out = s.handle(PlausibilityDone(type="_plausibility_done", report=_report({"name": 0.9})))
        assert any(isinstance(o, Submit) for o in out)

    def test_review_never_without_llm_submits_directly(self):
        form = _form()
        form.llm_validation = None
        s = _make(form, cfg=VoiceFormConfig(max_questions=None, review="never"))
        out = _answer_all(s)
        assert any(isinstance(o, Submit) for o in out)
        assert not any(isinstance(o, RunPlausibility) for o in out)

    def test_field_level_opt_in_runs_check_without_form_block(self):
        """Ledger b2df7f6dec56: a field-level llm_validation=True is eligible although the form has no block."""
        form = _form()
        form.llm_validation = None
        next(f for f in form.iter_fields_recursive() if f.field_id == "name").llm_validation = True
        s = _make(form, cfg=VoiceFormConfig(max_questions=None, review="never"))
        out = _answer_all(s)
        run = next(o for o in out if isinstance(o, RunPlausibility))
        assert set(run.fields) == {"name"}

    def test_block_mode_confirm_after_block_reruns_check_not_submit(self):
        """Ledger b2df7f6dec56 / AC13: a blocked report never leads to Submit."""
        form = _form()
        form.llm_validation = LLMValidationConfig(enabled=True, on_error="block")
        s = _make(form)
        _answer_all(s)
        blocked = PlausibilityReport(status="blocked", reason="down", threshold=0.7)
        out = s.handle(PlausibilityDone(type="_plausibility_done", report=blocked))
        assert any(getattr(o, "code", "") == "PLAUSIBILITY_UNAVAILABLE" for o in out)
        out = s.handle(ReviewConfirm(type="review_confirm", confirmed=True))
        assert not any(isinstance(o, Submit) for o in out)
        assert any(isinstance(o, RunPlausibility) for o in out)
        out = s.handle(PlausibilityDone(type="_plausibility_done", report=blocked))
        assert any(getattr(o, "code", "") == "PLAUSIBILITY_UNAVAILABLE" for o in out)
        assert not any(isinstance(o, Submit) for o in out)
        out = s.handle(ReviewConfirm(type="review_confirm", confirmed=True))
        s.handle(PlausibilityDone(type="_plausibility_done", report=_report({"name": 0.9})))
        out = s.handle(ReviewConfirm(type="review_confirm", confirmed=True))
        assert any(isinstance(o, Submit) for o in out)

    def test_engine_review_flag_and_edit_delta(self, v2_session):
        s = v2_session
        _answer_all(s)
        out = s.handle(PlausibilityDone(type="_plausibility_done", report=_report({"name": 0.2, "color": 0.9})))
        assert s.state.flagged == {"name": 1}
        start = next(o for o in out if isinstance(o, ReviewStart))
        assert [i.flagged for i in start.items if i.field_id == "name"] == [True]
        out = s.handle(ReviewEdit(type="review_edit", field_id="name"))
        assert s.state.phase == Phase.ASKING and s.state.cursor == "name"
        s.handle(AnswerText(type="answer_text", field_id="name", value="Bea"))
        out = _advance(s)
        run = next(o for o in out if isinstance(o, RunPlausibility))
        assert run.fields == {"name"}
        # Same low confidence again: new version -> flagged once for the new version only.
        out = s.handle(PlausibilityDone(type="_plausibility_done", report=_report({"name": 0.1})))
        assert s.state.phase == Phase.REVIEW
        assert s.state.flagged == {"name": 2}
        # The untouched field keeps its verdict from the first batch (delta merge).
        assert "color" in s.state.plausibility.items
        # A kept (unedited) answer is never re-flagged: re-running the same version changes nothing.
        s.state.phase = Phase.PLAUSIBILITY
        s.handle(PlausibilityDone(type="_plausibility_done", report=_report({"name": 0.1})))
        assert s.state.flagged == {"name": 2}

    def test_engine_review_voice_or_button_and_sensitive_hidden(self, v2_session):
        s = v2_session
        out = _answer_all(s)
        run = next(o for o in out if isinstance(o, RunPlausibility))
        assert "pw" not in run.fields
        out = s.handle(PlausibilityDone(type="_plausibility_done", report=_report({"name": 0.9})))
        start = next(o for o in out if isinstance(o, ReviewStart))
        pw = next(i for i in start.items if i.field_id == "pw")
        assert pw.answer_text == "[hidden]" and pw.sensitive and pw.position == 4
        assert "s3cret" not in repr(out)
        for phrase in ("sí", "ok", "enviar"):
            s.state.phase = Phase.REVIEW
            out = s.handle(TranscriptReady(type="_transcript", field_id="_review", text=phrase, confidence=0.9,
                                           audio_mime="audio/webm", audio_bytes_len=1))
            assert any(isinstance(o, Submit) for o in out), phrase
        s.state.phase = Phase.REVIEW
        out = s.handle(ReviewConfirm(type="review_confirm", confirmed=True))
        assert any(isinstance(o, Submit) for o in out)

    def test_review_audio_is_transcribed(self, v2_session):
        s = v2_session
        _answer_all(s)
        s.handle(PlausibilityDone(type="_plausibility_done", report=_report({})))
        out = s.handle(AudioReceived(type="_audio", audio=b"x", mime="audio/webm"))
        assert isinstance(out[0], Transcribe)

    def test_cambiar_la_n_reasks_and_returns_to_review(self, v2_session):
        s = v2_session
        _answer_all(s)
        s.handle(PlausibilityDone(type="_plausibility_done", report=_report({})))
        out = s.handle(TranscriptReady(type="_transcript", field_id="_review", text="cambiar la 2",
                                       confidence=0.9, audio_mime="audio/webm", audio_bytes_len=1))
        assert s.state.cursor == "color" and s.state.phase == Phase.ASKING
        assert any(o.type == "question" for o in out)
        s.handle(AnswerText(type="answer_text", field_id="color", value="g"))
        out = _advance(s)
        assert any(isinstance(o, RunPlausibility) and o.fields == {"color"} for o in out)
        s.handle(PlausibilityDone(type="_plausibility_done", report=_report({"color": 0.9})))
        assert s.state.phase == Phase.REVIEW

    def test_review_edit_unknown_field(self, v2_session):
        s = v2_session
        _answer_all(s)
        s.handle(PlausibilityDone(type="_plausibility_done", report=_report({})))
        out = s.handle(ReviewEdit(type="review_edit", field_id="nope"))
        assert isinstance(out[0], Error) and out[0].code == "WRONG_FIELD"

    def test_plausibility_blocked_errors_and_never_submits(self, v2_session):
        s = v2_session
        _answer_all(s)
        out = s.handle(PlausibilityDone(type="_plausibility_done",
                                        report=_report({}, status="blocked")))
        assert any(isinstance(o, Error) and o.code == "PLAUSIBILITY_UNAVAILABLE" for o in out)
        assert not any(isinstance(o, Submit) for o in out)
        assert s.state.plausibility is None and s.state.phase == Phase.REVIEW

    def test_plausibility_skipped_unflagged_review(self, v2_session):
        s = v2_session
        _answer_all(s)
        out = s.handle(PlausibilityDone(type="_plausibility_done", report=_report({}, status="skipped")))
        assert s.state.flagged == {}
        assert s.state.phase == Phase.REVIEW
        assert any(isinstance(o, ReviewStart) for o in out)

    def test_validation_errors_return_to_review(self, v2_session):
        s = v2_session
        _answer_all(s)
        s.handle(PlausibilityDone(type="_plausibility_done", report=_report({})))
        s.handle(ReviewConfirm(type="review_confirm", confirmed=True))
        out = s.handle(SubmitDone(type="_submit_done", outcome={"errors": {"name": ["bad"]}}))
        assert s.state.return_to_review and s.state.cursor == "name"
        s.handle(AnswerText(type="answer_text", field_id="name", value="Ok"))
        out = _advance(s)
        assert any(isinstance(o, RunPlausibility) and o.fields == {"name"} for o in out)

    def test_engine_resume_replans_and_rejects(self, v2_session):
        s = v2_session
        _start(s)
        _advance(s)
        s.handle(AnswerText(type="answer_text", field_id="name", value="Ana"))
        snap = s.snapshot()
        assert snap.answer_meta["name"]["value"] == "Ana"
        # happy path
        r = _make(s.form, snap=snap)
        out = _start(r, resume="sess")
        assert any(isinstance(o, Replan) for o in out)
        resumed = next(o for o in out if isinstance(o, SessionResumed))
        assert resumed.answered == ["name"]
        assert r.state.session_id == "sess" and r.state.pending is None
        out = _advance(r)
        assert next(o for o in out if o.type == "question").field_id == "color"
        # wrong user / tenant -> identical forbidden error
        for kw in ({"user": "other"}, {"tenant": "t2"}):
            bad = _start(_make(s.form, snap=snap, **kw), resume="sess")
            assert len(bad) == 1 and bad[0].code == "RESUME_FORBIDDEN"
        # changed form version
        form = s.form.model_copy(update={"version": "2.0"})
        stale = _start(_make(form, snap=snap), resume="sess")
        assert stale[0].code == "RESUME_STALE"

    def test_resume_drops_invalid_option_and_unknown_field(self, v2_session):
        s = v2_session
        _answer_all(s)
        snap = s.snapshot()
        snap.answer_meta["color"]["value"] = "zzz"
        snap.answer_meta["ghost"] = dict(snap.answer_meta["name"], field_id="ghost")
        r = _make(s.form, snap=snap)
        out = _start(r, resume="sess")
        assert "color" not in r.state.answers and "ghost" not in r.state.answers
        assert "name" in r.state.answers
        assert any(isinstance(o, Replan) for o in out)

    def test_snapshot_has_no_audio_and_no_trusted_plausibility(self, v2_session):
        s = v2_session
        _answer_all(s)
        s.handle(PlausibilityDone(type="_plausibility_done", report=_report({"name": 0.1})))
        s._last_audio = ("name", b"RAWAUDIO", "audio/webm")
        snap = s.snapshot()
        dumped = snap.model_dump_json()
        assert "RAWAUDIO" not in dumped and snap.plausibility is None
        assert snap.flagged == {"name": 1}
        # resume discards flags of changed versions and the report
        r = _make(s.form, snap=snap)
        _start(r, resume="sess")
        assert r.state.plausibility is None and r.state.phase == Phase.PLANNING

    def test_skipped_fields_survive_resume(self, v2_session):
        s = v2_session
        _start(s)
        _advance(s)
        s.handle(AnswerText(type="answer_text", field_id="name", value="Ana"))
        _advance(s)
        from parrot_formdesigner.audio.events import SkipQuestion
        s.handle(SkipQuestion(type="skip_question"))
        r = _make(s.form, snap=s.snapshot())
        _start(r, resume="sess")
        assert r._skipped == {"color"}
        out = _advance(r)
        assert next(o for o in out if o.type == "question").field_id == "agree"

    def test_sensitive_policy_everywhere(self, v2_session, caplog):
        s = v2_session
        caplog.set_level(logging.DEBUG)
        out = _answer_all(s)
        run = next(o for o in out if isinstance(o, RunPlausibility))
        assert "pw" not in run.fields
        out = s.handle(PlausibilityDone(type="_plausibility_done", report=_report({"name": 0.9})))
        everything = repr(out)
        snaps = [o for o in out if isinstance(o, SaveSnapshot)]
        assert snaps and "s3cret" not in repr(snaps)
        out = s.handle(ReviewConfirm(type="review_confirm", confirmed=True))
        submit = next(o for o in out if isinstance(o, Submit))
        assert "pw" in submit.data  # the real value goes to the pipeline, nowhere else
        done = s.handle(SubmitDone(type="_submit_done", outcome={"submission_id": "x", "stored_in": "db"}))
        complete = next(o for o in done if isinstance(o, FormComplete))
        assert complete.answers["pw"] == "[hidden]"
        assert "s3cret" not in everything + repr(done) + repr(s.snapshot().model_dump())
        assert "s3cret" not in caplog.text
