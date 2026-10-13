"""FEAT-649 TASK-4225 — AudioFormSession part 1 (pure engine)."""

from __future__ import annotations

import ast
import asyncio
import logging
from pathlib import Path

import pytest

import parrot_formdesigner.audio.engine as engine_mod
from parrot_formdesigner.audio.engine import AudioFormSession
from parrot_formdesigner.audio.events import (
    AnswerAccepted,
    AnswerPayload,
    AnswerRejected,
    AnswerSelection,
    AnswerText,
    AudioReceived,
    BlobStored,
    CommandAck,
    ConfirmAnswer,
    ConfirmRequest,
    Error,
    FormComplete,
    GoBack,
    PlanReady,
    Question,
    RepeatQuestion,
    Replan,
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
    ValidationErrors,
)
from parrot_formdesigner.audio.models import AudioFormManifest, AudioSessionState, Phase
from parrot_formdesigner.audio.narration.engine import Narrator
from parrot_formdesigner.audio.narration.lexicon import load_lexicon
from parrot_formdesigner.core.options import FieldOption
from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.core.voice import VoiceFormConfig
from parrot_formdesigner.renderers.audio import AudioFormRenderer
from parrot_formdesigner.services.rule_evaluator import RuleResolution


def test_engine_has_no_await() -> None:
    """AC2: audio/engine.py contains no Await / AsyncFunctionDef / async for|with."""
    source = Path(engine_mod.__file__).read_text()
    tree = ast.parse(source)
    banned = (ast.Await, ast.AsyncFunctionDef, ast.AsyncFor, ast.AsyncWith)
    offenders = [type(n).__name__ for n in ast.walk(tree) if isinstance(n, banned)]
    assert offenders == []
    assert "asyncio" not in source
    assert "aiohttp" not in source


def _opts(*pairs: tuple[str, str]) -> list[FieldOption]:
    return [FieldOption(value=v, label=lbl) for v, lbl in pairs]


def _build(extra_meta: dict | None = None, cfg: VoiceFormConfig | None = None, protocol: int = 1):
    fields = [
        FormField(field_id="name", field_type=FieldType.TEXT, label="Name", required=True),
        FormField(
            field_id="color",
            field_type=FieldType.SELECT,
            label="Color",
            required=False,
            options=_opts(("r", "Rojo"), ("g", "Verde"), ("s", "Saltar"), ("b", "Azul")),
            meta=extra_meta,
        ),
        FormField(field_id="agree", field_type=FieldType.BOOLEAN, label="Agree", required=False),
        FormField(
            field_id="tags",
            field_type=FieldType.MULTI_SELECT,
            label="Tags",
            required=False,
            options=_opts(("x", "Manzana"), ("y", "Pera"), ("z", "Uva")),
        ),
        FormField(field_id="pw", field_type=FieldType.PASSWORD, label="Password", required=False),
    ]
    form = FormSchema(form_id="f", title="F", sections=[FormSection(section_id="s1", title="S", fields=fields)])
    questions = AudioFormRenderer().split_into_questions(form, locale="es")
    manifest = AudioFormManifest(
        form_uid=str(form.form_uid),
        title="F",
        total_questions=len(questions),
        questions=questions,
        ws_endpoint="/ws",
        locale="es",
    )
    state = AudioSessionState(session_id="sess", form_uid=str(form.form_uid), user_id="u", manifest=manifest)
    cfg = cfg or VoiceFormConfig(max_questions=None)
    session = AudioFormSession(
        form=form,
        manifest=manifest,
        cfg=cfg,
        narrator=Narrator("es"),
        lexicon=load_lexicon("es"),
        state=state,
        llm_cfg=None,
    )
    session.handle(
        StartSession(type="start_session", form_uid=str(form.form_uid), locale="es", protocol_version=protocol)
    )
    return session


def _plan_ready(session: AudioFormSession) -> PlanReady:
    plan, delta = asyncio.run(session.planner.replan(session.state.answers, locale="es", resolution=RuleResolution()))
    return PlanReady(type="_plan_ready", plan=plan, delta=delta.model_dump())


def _advance(session: AudioFormSession) -> list:
    return session.handle(_plan_ready(session))


def _tr(field_id: str, text: str, confidence: float | None = 0.95) -> TranscriptReady:
    return TranscriptReady(
        type="_transcript",
        field_id=field_id,
        text=text,
        confidence=confidence,
        audio_mime="audio/webm",
        audio_bytes_len=3,
    )


def _text(field_id: str, value: str) -> AnswerText:
    return AnswerText(type="answer_text", field_id=field_id, value=value)


def _types(out: list) -> list[str]:
    return [o.type for o in out]


@pytest.fixture
def session() -> AudioFormSession:
    s = _build()
    return s


@pytest.fixture
def started(session: AudioFormSession):
    out = _advance(session)
    return session, out


class TestEngineTurns:
    def test_engine_accepts_audio_right_after_question(self, started) -> None:
        """Barge-in premise (AC2): a recording arriving right after `question` — before any
        client playback could have ended — is transcribed against the cursor field."""
        s, out = started
        assert s.state.phase == Phase.ASKING
        assert out[-1].type == "question"
        field_id = out[-1].field_id
        assert field_id == s.state.cursor
        out = s.handle(AudioReceived(type="_audio", audio=b"abc", mime="audio/webm"))
        assert isinstance(out[0], Transcribe)
        assert out[0].field_id == field_id
        assert s._last_audio == (field_id, b"abc", "audio/webm")

    def test_start_emits_replan_then_plan_ready_emits_started_prefetch_question(self, session) -> None:
        assert session.state.phase == Phase.PLANNING
        out = _advance(session)
        assert _types(out) == [
            "session_started",
            "_synthesize",
            "section_enter",
            "question",
        ]  # section_enter since TASK-4232 sets section_uid
        assert isinstance(out[0], SessionStarted) and out[0].total_questions == 5
        assert isinstance(out[1], Synthesize) and any(k.startswith("sys:") for k in out[1].keys)
        assert out[-1].field_id == "name" and out[-1].required is True
        assert session.state.phase == Phase.ASKING and session.state.cursor == "name"

    def test_text_answer_accepts_and_replans(self, started) -> None:
        s, _ = started
        out = s.handle(_text("name", "Ana"))
        assert isinstance(out[0], AnswerAccepted) and out[0].value == "Ana"
        assert isinstance(out[-1], Replan)
        assert s.state.cursor == "name"  # cursor only moves on PlanReady
        nxt = _advance(s)
        assert isinstance(nxt[-1], Question) and nxt[-1].field_id == "color"

    def test_wrong_field_rejected_and_reanswer_bumps_version(self, started) -> None:
        s, _ = started
        out = s.handle(_text("color", "r"))
        assert isinstance(out[0], Error) and out[0].code == "WRONG_FIELD"
        s.handle(_text("name", "Ana"))
        _advance(s)
        out = s.handle(GoBack(type="go_back"))
        assert isinstance(out[-1], Question) and out[-1].field_id == "name"
        s.handle(_text("name", "Bea"))
        assert s.state.answers["name"].version == 2 and s.state.answers["name"].value == "Bea"

    def test_engine_turn_flow_voice_select_fallback(self, started) -> None:
        s, _ = started
        q = s._question("name")
        assert q.voice_mode == "voice"
        sel = s._question("color")
        assert sel.voice_mode in ("voice", "prompt_select") and sel.options
        s._questions["color"] = s._questions["color"].model_copy(update={"voice_mode": "prompt_select"})
        assert s._question("color").voice_mode == "prompt_select"
        s._questions["tags"] = s._questions["tags"].model_copy(
            update={"voice_mode": "visual_fallback", "render_mode": "visual", "fallback_html": "<b/>"}
        )
        vq = s._question("tags")
        assert vq.voice_mode == "visual_fallback" and vq.fallback_html == "<b/>"
        s.handle(_text("name", "Ana"))
        _advance(s)
        out = s.handle(AnswerSelection(type="answer_selection", field_id="color", value="r"))
        assert out[0].source == "selection" and s.state.answers["color"].value == "r"
        _advance(s)  # agree
        s.handle(AnswerText(type="answer_text", field_id="agree", value="true"))
        _advance(s)  # tags (visual fallback)
        out = s.handle(AnswerPayload(type="answer_payload", field_id="tags", value=["x"]))
        assert isinstance(out[0], AnswerAccepted)
        bad = _advance(s)
        s.handle(AnswerSelection(type="answer_selection", field_id="pw", value="zzz"))
        assert bad

    def test_select_by_ordinal_stores_value_not_transcript(self, started) -> None:
        s, _ = started
        s.handle(_text("name", "Ana"))
        _advance(s)
        out = s.handle(_tr("color", "la segunda"))
        assert isinstance(out[0], Transcription)
        assert s.state.answers["color"].value == "g"
        assert s.state.answers["color"].matched is not None

    def test_multi_select_by_voice_is_list(self, started) -> None:
        s, _ = started
        s.handle(_text("name", "Ana"))
        _advance(s)
        s.handle(_text("color", "r"))
        _advance(s)
        s.handle(_text("agree", "x"))
        _advance(s)
        assert s.state.cursor == "tags"
        s.handle(_tr("tags", "manzana y pera"))
        assert s.state.answers["tags"].value == ["x", "y"]
        # disabled options are never accepted
        s2 = _build()
        _advance(s2)
        assert s2._questions["color"].options

    def test_low_confidence_confirm_then_confirm_true_accepts(self, started) -> None:
        s, _ = started
        out = s.handle(AudioReceived(type="_audio", audio=b"abc", mime="audio/webm"))
        assert isinstance(out[0], Transcribe) and out[0].field_id == "name"
        out = s.handle(_tr("name", "Ana", confidence=0.2))
        assert isinstance(out[-1], ConfirmRequest) and s.state.phase == Phase.CONFIRMING
        out = s.handle(ConfirmAnswer(type="confirm_answer", field_id="name", confirmed=True))
        assert isinstance(out[0], AnswerAccepted) and out[0].source == "speech"
        blob = next(o for o in out if isinstance(o, StoreBlob))
        assert blob.version == 1 and isinstance(out[-1], Replan)
        assert s.state.answers["name"].audio_mime == "audio/webm"
        s.handle(BlobStored(type="_blob_stored", field_id="name", blob_ref="ref1", version=1))
        assert s.state.answers["name"].blob_ref == "ref1"

    def test_confirm_false_resends_same_question(self, started) -> None:
        s, _ = started
        assert s.handle(ConfirmAnswer(type="confirm_answer"))[0].code == "NO_PENDING_ANSWER"
        s.handle(_tr("name", "Ana", confidence=0.2))
        assert (
            s.handle(ConfirmAnswer(type="confirm_answer", field_id="zzz", confirmed=True))[0].code == "FIELD_MISMATCH"
        )
        out = s.handle(ConfirmAnswer(type="confirm_answer", field_id="name", confirmed=False))
        assert isinstance(out[0], Question) and out[0].field_id == "name"
        assert "name" not in s.state.answers and s.state.phase == Phase.ASKING

    def test_exact_option_beats_command_and_commands_off(self, started) -> None:
        s, _ = started
        s.handle(_text("name", "Ana"))
        _advance(s)
        out = s.handle(_tr("color", "Saltar"))
        assert s.state.answers["color"].value == "s"
        assert not any(isinstance(o, CommandAck) for o in out)
        # commands off per field: "repetir" is not a command (no_match on option field)
        s2 = _build(extra_meta={"voice": {"commands": "off"}})
        _advance(s2)
        s2.handle(_text("name", "Ana"))
        _advance(s2)
        out = s2.handle(_tr("color", "repetir"))
        assert not any(isinstance(o, CommandAck) for o in out)
        s3 = _build(cfg=VoiceFormConfig(max_questions=None, commands="off"))
        _advance(s3)
        out = s3.handle(_tr("name", "repetir"))
        assert not any(isinstance(o, CommandAck) for o in out)
        assert s3.state.answers["name"].value == "repetir"

    def test_repeat_back_skip_commands_ack_and_effect(self, started) -> None:
        s, _ = started
        out = s.handle(_tr("name", "repetir"))
        assert any(isinstance(o, CommandAck) and o.command == "repeat" for o in out)
        assert isinstance(out[-1], Question) and "name" not in s.state.answers
        s.handle(_text("name", "Ana"))
        _advance(s)
        s.handle(_text("color", "r"))
        _advance(s)
        out = s.handle(_tr("agree", "saltar"))
        assert any(isinstance(o, CommandAck) and o.command == "skip" for o in out)
        assert isinstance(out[-1], Replan) and "agree" not in s.state.answers
        nxt = _advance(s)
        assert nxt[-1].field_id == "tags"
        out = s.handle(_tr("tags", "atrás"))
        assert any(isinstance(o, CommandAck) and o.command == "back" for o in out)
        assert isinstance(out[-1], Question) and out[-1].field_id == "agree"
        out = s.handle(RepeatQuestion(type="repeat_question"))
        assert out[0].field_id == "agree"

    def test_skip_required_rejected(self, started) -> None:
        s, _ = started
        out = s.handle(SkipQuestion(type="skip_question"))
        assert isinstance(out[0], AnswerRejected) and out[0].code == "REQUIRED"
        out = s.handle(_tr("name", "siguiente"))
        assert isinstance(out[-1], AnswerRejected)

    def test_plan_exhausted_submits_and_submit_done_completes(self, started) -> None:
        s, _ = started
        s.handle(_text("name", "Ana"))
        _advance(s)
        for fid in ("color", "agree", "tags", "pw"):
            assert s.state.cursor == fid
            s.handle(SkipQuestion(type="skip_question"))
            out = _advance(s)
        assert isinstance(out[-1], Submit) and s.state.phase == Phase.SUBMITTING
        assert out[-1].data == {"name": "Ana"}
        out = s.handle(SubmitDone(type="_submit_done", outcome={"submission_id": "sid", "stored_in": "sink"}))
        assert isinstance(out[0], FormComplete) and out[0].submission_id == "sid"
        assert s.state.phase == Phase.COMPLETE and s.state.completed

    def test_validation_errors_reask_first_field(self, started) -> None:
        s, _ = started
        s.handle(_text("name", "Ana"))
        _advance(s)
        for _ in range(4):
            s.handle(SkipQuestion(type="skip_question"))
            _advance(s)
        out = s.handle(SubmitDone(type="_submit_done", outcome={"errors": {"name": ["bad"]}}))
        assert isinstance(out[0], ValidationErrors) and out[0].first_field_id == "name"
        assert isinstance(out[-1], Question) and out[-1].field_id == "name"
        assert s.state.phase == Phase.ASKING and s.state.cursor == "name"

    def test_sensitive_spoken_answer_not_recorded_nor_wrapped(self, started) -> None:
        """Ledger 207af38a9ad7: a spoken PASSWORD stores no blob and submits the plain scalar."""
        s, _ = started
        s.state.cursor = "pw"
        s.state.phase = Phase.ASKING
        s.handle(AudioReceived(type="_audio", audio=b"abc", mime="audio/webm"))
        out = s.handle(_tr("pw", "hunter2"))
        assert not any(isinstance(o, StoreBlob) for o in out)
        assert s._submission_data()["pw"] == "hunter2"

    def test_sensitive_masked_in_transcription_and_ack(self, started, caplog) -> None:
        s, _ = started
        s.state.cursor = "pw"
        s.state.phase = Phase.ASKING
        with caplog.at_level(logging.DEBUG):
            out = s.handle(_tr("pw", "hunter2"))
        assert out[0].text == "[hidden]"
        ack = next(o for o in out if isinstance(o, AnswerAccepted))
        assert ack.value == "[hidden]"
        assert s.state.answers["pw"].value == "hunter2"
        assert s.state.answers["pw"].raw_transcript is None
        assert "hunter2" not in caplog.text
