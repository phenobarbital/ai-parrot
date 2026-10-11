"""Tests for AudioFormWSHandler (FEAT-224 TASK-1463, FEAT-236 TASK-1541)."""

import base64
import uuid
from types import SimpleNamespace

import pytest
from unittest.mock import AsyncMock, MagicMock

from parrot_formdesigner.api.audio_ws import AudioFormWSHandler, _ConnCtx
from parrot_formdesigner.audio.models import (
    AudioAnswer,
    AudioQuestion,
    AudioSessionConfig,
    AudioSessionState,
    VoiceMode,
)
from parrot_formdesigner.core.options import FieldOption
from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection
from parrot_formdesigner.core.types import FieldType

# FEAT-393 / TASK-2004: AudioQuestion.field_uid is now required. These WS
# handler tests exercise field_id-keyed wire semantics (unchanged by this
# task) and don't assert on field_uid, so they share this sentinel value.
_UID = uuid.uuid4()

# A minimal-but-valid-looking audio frame: EBML/WebM magic header padded past
# the handler's minimum-size guard. The transcriber is mocked in these tests,
# so the bytes are never actually decoded — they only need to pass the
# payload-sniffing guard in _process_binary (FEAT-236 hardening).
_FAKE_WEBM = b"\x1a\x45\xdf\xa3" + b"\x00" * 512


@pytest.fixture
def mock_registry() -> AsyncMock:
    """Mock FormRegistry returning a simple 2-field form."""
    from parrot_formdesigner.core.schema import FormSchema, FormSection, FormField
    from parrot_formdesigner.core.types import FieldType

    form = FormSchema(
        form_id="test-form",
        title="Test Form",
        sections=[
            FormSection(
                section_id="s1",
                fields=[
                    FormField(
                        field_id="name",
                        field_type=FieldType.TEXT,
                        label="What is your name?",
                        required=True,
                    ),
                    FormField(
                        field_id="note",
                        field_type=FieldType.AUDIO,
                        label="Leave a note",
                    ),
                ],
            )
        ],
    )

    registry = AsyncMock()
    registry.get.return_value = form
    return registry


@pytest.fixture
def mock_synthesizer() -> AsyncMock:
    """Mock VoiceSynthesizer returning dummy audio."""
    synth = AsyncMock()
    synth.synthesize.return_value = MagicMock(
        audio=b"fake-audio", mime_format="audio/ogg"
    )
    return synth


@pytest.fixture
def mock_transcriber() -> AsyncMock:
    """Mock FasterWhisperBackend returning fixed transcription."""
    transcriber = AsyncMock()
    transcriber.transcribe.return_value = MagicMock(
        text="hello", confidence=0.95, language="en"
    )
    return transcriber


@pytest.fixture
def mock_validator() -> MagicMock:
    """Mock FormValidator (accepts all answers)."""
    return MagicMock()


@pytest.fixture
def mock_token_validator() -> AsyncMock:
    """Mock TokenValidator that accepts any token."""
    from parrot.voice.handler import AuthenticatedUser  # type: ignore[import-untyped]

    validator = AsyncMock()
    validator.validate.return_value = AuthenticatedUser(
        user_id="test-user-1", username="testuser"
    )
    return validator


@pytest.fixture
def handler(
    mock_registry: AsyncMock,
    mock_synthesizer: AsyncMock,
    mock_transcriber: AsyncMock,
    mock_validator: MagicMock,
    mock_token_validator: AsyncMock,
) -> AudioFormWSHandler:
    """AudioFormWSHandler with mocked dependencies."""
    return AudioFormWSHandler(
        registry=mock_registry,
        synthesizer=mock_synthesizer,
        transcriber=mock_transcriber,
        validator=mock_validator,
        token_validator=mock_token_validator,
    )


# ---------------------------------------------------------------------------
# Harness: drive the adapter through its public frame path (FEAT-649 TASK-4227)
# ---------------------------------------------------------------------------

_TENANT = "t1"


def _fld(field_id: str, field_type: FieldType = FieldType.TEXT, *, label: str | None = None,
         required: bool = False, options: list[tuple[str, str]] | None = None) -> FormField:
    return FormField(
        field_id=field_id, field_type=field_type, label=label or f"{field_id}?", required=required,
        options=[FieldOption(value=v, label=lbl) for v, lbl in options] if options else None,
    )


def _form(*fields: FormField) -> FormSchema:
    return FormSchema(
        form_id="f", title="T", tenant=_TENANT,
        sections=[FormSection(section_id="s1", fields=list(fields))],
    )


def _fresh_ws() -> AsyncMock:
    ws = AsyncMock()
    ws.send_json = AsyncMock()
    ws.send_bytes = AsyncMock()
    return ws


def _sent(ws: AsyncMock) -> list[dict]:
    return [c[0][0] for c in ws.send_json.call_args_list]


def _sent_types(ws: AsyncMock) -> list[str]:
    return [m["type"] for m in _sent(ws)]


def _last(ws: AsyncMock, mtype: str) -> dict:
    return next(m for m in reversed(_sent(ws)) if m["type"] == mtype)


async def _boot(handler: AudioFormWSHandler, form: FormSchema, *, start: dict | None = None):
    """Start a session on ``form``; returns (ws, ctx). Sent messages are cleared after start-up."""
    handler.registry = AsyncMock()
    handler.registry.get.return_value = form
    ws = _fresh_ws()
    request = SimpleNamespace(match_info={"form_uid": "f1", "tenant": _TENANT}, headers={})
    ctx = _ConnCtx(
        request=request, user=SimpleNamespace(user_id="u1", raw_payload={}), tenant=_TENANT,
        state=AudioSessionState(session_id="s1", form_uid="f1", user_id="u1", tenant=_TENANT),
    )
    await handler._process_text(ws, ctx, {"type": "start_session", "form_uid": "f1", **(start or {})})
    return ws, ctx


async def _say(handler: AudioFormWSHandler, ws: AsyncMock, ctx: _ConnCtx, **data) -> None:
    ws.send_json.reset_mock()
    await handler._process_text(ws, ctx, data)


class TestAudioSessionState:
    """Verify AudioSessionState behaves correctly."""

    def test_initial_state(self) -> None:
        """Fresh session has correct defaults."""
        state = AudioSessionState(session_id="s1", form_uid="f1", user_id="u1")
        assert state.current_index == 0
        assert state.answers == {}
        assert state.completed is False

    def test_add_answer(self) -> None:
        """Answers can be added to the state dict."""
        state = AudioSessionState(session_id="s1", form_uid="f1", user_id="u1")
        state.answers["name"] = AudioAnswer(field_id="name", value="Alice", source="text")
        assert state.answers["name"].value == "Alice"


class TestHandlerInstantiation:
    """Basic handler creation tests."""

    def test_handler_created(self, handler: AudioFormWSHandler) -> None:
        """AudioFormWSHandler can be instantiated with mocked deps."""
        assert handler.registry is not None
        assert handler.synthesizer is not None
        assert handler.transcriber is not None

    def test_handler_without_token_validator(
        self, mock_registry: AsyncMock, mock_synthesizer: AsyncMock,
        mock_transcriber: AsyncMock, mock_validator: MagicMock,
    ) -> None:
        """Handler can be created without a token_validator (anonymous mode)."""
        h = AudioFormWSHandler(
            registry=mock_registry, synthesizer=mock_synthesizer,
            transcriber=mock_transcriber, validator=mock_validator,
        )
        assert h._token_validator is None
        assert h._pipeline is None and h._session_store is None and h._blob_storage is None


class TestSessionLifecycle:
    """Session start and answer flow through the public frame path."""

    @pytest.mark.asyncio
    async def test_text_answer_stores_value_and_acks(self, handler: AudioFormWSHandler) -> None:
        """answer_text stores the answer and sends answer_accepted, then the next question."""
        ws, ctx = await _boot(handler, _form(_fld("name", required=True), _fld("age")))
        assert _sent_types(ws)[:2] == ["session_started", "question"]
        await _say(handler, ws, ctx, type="answer_text", field_id="name", value="Alice")
        ack = _sent(ws)[0]
        assert ack["type"] == "answer_accepted" and ack["field_id"] == "name"
        assert ack["value"] == "Alice" and ack["source"] == "text"
        assert ctx.engine.state.answers["name"].value == "Alice"
        assert _last(ws, "question")["field_id"] == "age"

    @pytest.mark.asyncio
    async def test_question_without_audio(self, handler: AudioFormWSHandler) -> None:
        """With no synthesizer the question is delivered text-only."""
        handler.synthesizer = None  # type: ignore[assignment]
        ws, _ = await _boot(handler, _form(_fld("name")))
        q = _last(ws, "question")
        assert q["field_id"] == "name"
        assert "audio" not in q

    @pytest.mark.asyncio
    async def test_question_with_audio_is_base64(self, handler: AudioFormWSHandler) -> None:
        """A v1 question carries the synthesized narration as base64 ``audio``."""
        ws, _ = await _boot(handler, _form(_fld("age", FieldType.NUMBER)))
        assert _last(ws, "question")["audio"] == base64.b64encode(b"fake-audio").decode()

    @pytest.mark.asyncio
    async def test_send_error_sends_error_message(self, handler: AudioFormWSHandler) -> None:
        """_send_error() sends a well-formed error message."""
        ws = _fresh_ws()
        await handler._send_error(ws, "TEST_CODE", "Test error message")
        assert _sent(ws)[0] == {"type": "error", "code": "TEST_CODE", "message": "Test error message"}

    @pytest.mark.asyncio
    async def test_message_before_start_is_rejected(self, handler: AudioFormWSHandler) -> None:
        """Anything but ping/start_session before start_session is SESSION_NOT_STARTED."""
        ws = _fresh_ws()
        ctx = _ConnCtx(request=None, user=None, tenant=_TENANT,
                       state=AudioSessionState(session_id="s", form_uid="f", user_id="u"))
        await handler._process_text(ws, ctx, {"type": "answer_text", "field_id": "x", "value": "y"})
        assert _sent(ws)[0]["code"] == "SESSION_NOT_STARTED"


class TestNavigation:
    """skip, go_back, repeat, ping."""

    @pytest.mark.asyncio
    async def test_skip_required_field_rejected(self, handler: AudioFormWSHandler) -> None:
        """Skipping a required question sends answer_rejected."""
        ws, ctx = await _boot(handler, _form(_fld("name", required=True)))
        await _say(handler, ws, ctx, type="skip_question", field_id="name")
        assert _sent(ws)[0]["type"] == "answer_rejected"

    @pytest.mark.asyncio
    async def test_skip_optional_field_advances(self, handler: AudioFormWSHandler) -> None:
        """Skipping an optional question delivers the next question."""
        ws, ctx = await _boot(handler, _form(_fld("name"), _fld("age", FieldType.NUMBER)))
        await _say(handler, ws, ctx, type="skip_question")
        assert _last(ws, "question")["field_id"] == "age"

    @pytest.mark.asyncio
    async def test_go_back_navigates_to_previous(self, handler: AudioFormWSHandler) -> None:
        """go_back re-sends the previous question."""
        ws, ctx = await _boot(handler, _form(_fld("q0"), _fld("q1"), _fld("q2")))
        await _say(handler, ws, ctx, type="answer_text", field_id="q0", value="a")
        await _say(handler, ws, ctx, type="go_back")
        q = _last(ws, "question")
        assert q["field_id"] == "q0" and q["index"] == 0

    @pytest.mark.asyncio
    async def test_repeat_question_resends_current(self, handler: AudioFormWSHandler) -> None:
        """repeat_question re-sends the current question (audio included)."""
        ws, ctx = await _boot(handler, _form(_fld("name"), _fld("age", FieldType.NUMBER)))
        await _say(handler, ws, ctx, type="answer_text", field_id="name", value="a")
        await _say(handler, ws, ctx, type="repeat_question")
        q = _sent(ws)[0]
        assert q["type"] == "question" and q["field_id"] == "age" and q.get("audio")

    @pytest.mark.asyncio
    async def test_ping_returns_pong(self, handler: AudioFormWSHandler) -> None:
        """ping receives pong, before and after start_session."""
        ws, ctx = await _boot(handler, _form(_fld("name")))
        await _say(handler, ws, ctx, type="ping")
        assert _sent(ws)[0]["type"] == "pong"
        fresh = _ConnCtx(request=None, user=None, tenant=_TENANT,
                         state=AudioSessionState(session_id="s", form_uid="f", user_id="u"))
        ws2 = _fresh_ws()
        await handler._process_text(ws2, fresh, {"type": "ping"})
        assert _sent(ws2)[0]["type"] == "pong"


_COLORS = [("red", "Red"), ("blue", "Blue")]


class TestVoiceModeQuestionDelivery:
    """Question messages carry VoiceMode metadata and visual fallback HTML."""

    @pytest.mark.asyncio
    async def test_question_message_includes_voice_mode(self, handler: AudioFormWSHandler) -> None:
        ws, _ = await _boot(handler, _form(_fld("color", FieldType.SELECT, options=_COLORS)))
        msg = _last(ws, "question")
        assert msg["voice_mode"] == "prompt_select"
        assert msg["render_mode"] == "select"
        assert msg["sensitive"] is False
        assert msg["options"]

    @pytest.mark.asyncio
    async def test_visual_fallback_question_has_fallback_html(self, handler: AudioFormWSHandler) -> None:
        ws, _ = await _boot(handler, _form(_fld("doc", FieldType.REST, label="Upload", required=True)))
        msg = _last(ws, "question")
        assert msg["voice_mode"] == "visual_fallback"
        assert msg.get("fallback_html")

    @pytest.mark.asyncio
    async def test_sensitive_password_no_audio(self, handler: AudioFormWSHandler) -> None:
        ws, _ = await _boot(handler, _form(_fld("pw", FieldType.PASSWORD, label="Password?")))
        msg = _last(ws, "question")
        assert msg["sensitive"] is True
        assert "audio" not in msg
        handler.synthesizer.synthesize.assert_not_called()

    @pytest.mark.asyncio
    async def test_prompt_select_enumerates_options_in_tts(self, handler: AudioFormWSHandler) -> None:
        await _boot(handler, _form(_fld("color", FieldType.SELECT, label="Color?", options=_COLORS)))
        spoken = " ".join(c[0][0] for c in handler.synthesizer.synthesize.call_args_list)
        assert "Red" in spoken and "Blue" in spoken


class TestSelectionAndPayloadHandlers:
    """answer_selection and answer_payload."""

    @pytest.mark.asyncio
    async def test_answer_selection_single(self, handler: AudioFormWSHandler) -> None:
        ws, ctx = await _boot(handler, _form(_fld("color", FieldType.SELECT, options=_COLORS), _fld("x")))
        await _say(handler, ws, ctx, type="answer_selection", field_id="color", value="red")
        assert ctx.engine.state.answers["color"].value == "red"
        assert ctx.engine.state.answers["color"].source == "selection"
        assert _last(ws, "question")["field_id"] == "x"

    @pytest.mark.asyncio
    async def test_answer_selection_multi(self, handler: AudioFormWSHandler) -> None:
        """AC6: MULTI_SELECT is stored as a list; the v1 wire still echoes a comma-joined value."""
        ws, ctx = await _boot(handler, _form(
            _fld("tags", FieldType.MULTI_SELECT, options=[("a", "A"), ("b", "B")]), _fld("x")))
        await _say(handler, ws, ctx, type="answer_selection", field_id="tags", values=["a", "b"])
        assert ctx.engine.state.answers["tags"].value == ["a", "b"]
        assert ctx.engine.state.answers["tags"].source == "selection"
        assert _sent(ws)[0]["value"] == "a,b"

    @pytest.mark.asyncio
    async def test_answer_selection_invalid_rejected(self, handler: AudioFormWSHandler) -> None:
        ws, ctx = await _boot(handler, _form(_fld("color", FieldType.SELECT, options=[("red", "Red")])))
        await _say(handler, ws, ctx, type="answer_selection", field_id="color", value="green")
        assert _sent(ws)[0]["type"] == "error"
        assert _sent(ws)[0]["code"] == "INVALID_OPTION"
        assert "color" not in ctx.engine.state.answers

    @pytest.mark.asyncio
    async def test_answer_payload_completes_rest(self, handler: AudioFormWSHandler) -> None:
        ws, ctx = await _boot(handler, _form(_fld("doc", FieldType.REST, label="Upload", required=True), _fld("x")))
        await _say(handler, ws, ctx, type="answer_payload", field_id="doc", value="blob://123")
        assert ctx.engine.state.answers["doc"].value == "blob://123"
        assert _last(ws, "question")["field_id"] == "x"


def _mock_stt(transcriber: AsyncMock, *, text: str, confidence: float) -> None:
    transcriber.transcribe.return_value = MagicMock(text=text, confidence=confidence, language="en")


class TestLowConfidenceConfirmation:
    """Low-confidence STT read-back gate."""

    @pytest.mark.asyncio
    async def test_low_confidence_emits_confirm_request_no_advance(
        self, handler: AudioFormWSHandler, mock_transcriber: AsyncMock
    ) -> None:
        _mock_stt(mock_transcriber, text="alice", confidence=0.2)
        ws, ctx = await _boot(handler, _form(_fld("name", required=True), _fld("x")))
        ws.send_json.reset_mock()
        await handler._process_binary(ws, ctx, _FAKE_WEBM)
        assert "confirm_request" in _sent_types(ws)
        assert "question" not in _sent_types(ws)
        assert ctx.engine.state.pending is not None
        assert ctx.engine.state.pending.value == "alice"
        assert "name" not in ctx.engine.state.answers

    @pytest.mark.asyncio
    async def test_high_confidence_auto_advances(
        self, handler: AudioFormWSHandler, mock_transcriber: AsyncMock
    ) -> None:
        _mock_stt(mock_transcriber, text="alice", confidence=0.95)
        ws, ctx = await _boot(handler, _form(_fld("name", required=True), _fld("x")))
        ws.send_json.reset_mock()
        await handler._process_binary(ws, ctx, _FAKE_WEBM)
        assert "confirm_request" not in _sent_types(ws)
        assert ctx.engine.state.answers["name"].value == "alice"
        assert _last(ws, "question")["field_id"] == "x"

    @pytest.mark.asyncio
    async def test_confirm_true_stores_and_advances(
        self, handler: AudioFormWSHandler, mock_transcriber: AsyncMock
    ) -> None:
        _mock_stt(mock_transcriber, text="alice", confidence=0.2)
        ws, ctx = await _boot(handler, _form(_fld("name", required=True), _fld("x")))
        await handler._process_binary(ws, ctx, _FAKE_WEBM)
        await _say(handler, ws, ctx, type="confirm_answer", field_id="name", confirmed=True)
        assert ctx.engine.state.answers["name"].value == "alice"
        assert ctx.engine.state.pending is None
        assert _last(ws, "question")["field_id"] == "x"

    @pytest.mark.asyncio
    async def test_confirm_false_resends_same_question(
        self, handler: AudioFormWSHandler, mock_transcriber: AsyncMock
    ) -> None:
        _mock_stt(mock_transcriber, text="alice", confidence=0.2)
        ws, ctx = await _boot(handler, _form(_fld("name", required=True)))
        await handler._process_binary(ws, ctx, _FAKE_WEBM)
        await _say(handler, ws, ctx, type="confirm_answer", field_id="name", confirmed=False)
        assert "name" not in ctx.engine.state.answers
        assert ctx.engine.state.pending is None
        last = _sent(ws)[-1]
        assert last["type"] == "question" and last["field_id"] == "name"

    @pytest.mark.asyncio
    async def test_confirm_without_pending_errors(self, handler: AudioFormWSHandler) -> None:
        ws, ctx = await _boot(handler, _form(_fld("name")))
        await _say(handler, ws, ctx, type="confirm_answer", field_id="name", confirmed=True)
        assert "error" in _sent_types(ws)


class TestBinaryGuards:
    """The v1 binary-frame guards run before the engine."""

    @pytest.mark.asyncio
    async def test_empty_audio_rejected(self, handler: AudioFormWSHandler, mock_transcriber: AsyncMock) -> None:
        ws, ctx = await _boot(handler, _form(_fld("name")))
        await handler._process_binary(ws, ctx, b"\x1a\x45\xdf\xa3")
        assert _sent(ws)[-1]["code"] == "EMPTY_AUDIO"
        mock_transcriber.transcribe.assert_not_called()

    @pytest.mark.asyncio
    async def test_unsupported_audio_rejected(self, handler: AudioFormWSHandler) -> None:
        ws, ctx = await _boot(handler, _form(_fld("name")))
        await handler._process_binary(ws, ctx, b"x" * 512)
        assert _sent(ws)[-1]["code"] == "UNSUPPORTED_AUDIO"

    @pytest.mark.asyncio
    async def test_no_transcriber_rejected(self, handler: AudioFormWSHandler) -> None:
        ws, ctx = await _boot(handler, _form(_fld("name")))
        handler.transcriber = None
        await handler._process_binary(ws, ctx, _FAKE_WEBM)
        assert _sent(ws)[-1]["code"] == "TRANSCRIBER_UNAVAILABLE"

    @pytest.mark.asyncio
    async def test_audio_before_start_rejected(self, handler: AudioFormWSHandler) -> None:
        ws = _fresh_ws()
        ctx = _ConnCtx(request=None, user=None, tenant=_TENANT,
                       state=AudioSessionState(session_id="s", form_uid="f", user_id="u"))
        await handler._process_binary(ws, ctx, _FAKE_WEBM)
        assert _sent(ws)[-1]["code"] == "SESSION_NOT_STARTED"


class TestGracefulSynthesis:
    """The handler never crashes when synthesis fails."""

    @pytest.mark.asyncio
    async def test_injected_synth_failure_degrades_to_text_only(self, handler: AudioFormWSHandler) -> None:
        handler.synthesizer.synthesize.side_effect = RuntimeError("no weights")
        ws, _ = await _boot(handler, _form(_fld("name")))
        msg = _last(ws, "question")
        assert "audio" not in msg

    @pytest.mark.asyncio
    async def test_no_synth_no_auto_is_text_only(self, handler: AudioFormWSHandler) -> None:
        handler.synthesizer = None  # type: ignore[assignment]
        assert handler._auto_synthesize is False
        ws, _ = await _boot(handler, _form(_fld("name")))
        assert "audio" not in _last(ws, "question")


class TestReviewHardening:
    """FEAT-236 code-review hardening: H-1, H-2, H-4, M-1, M-2."""

    @pytest.mark.asyncio
    async def test_fallback_html_escapes_field_id(self, handler: AudioFormWSHandler) -> None:
        """H-1: a hostile field_id is HTML-escaped in the minimal fallback."""
        q = AudioQuestion(
            field_uid=_UID, index=0, field_id='x" onfocus="alert(1)', field_type="rest",
            label="L", voice_mode=VoiceMode.VISUAL_FALLBACK, render_mode="visual",
        )
        fhtml = await handler._build_fallback_html(q, AudioSessionConfig(form_uid="f1"))
        assert 'onfocus="' not in fhtml  # raw attribute breakout neutralized
        assert "&quot;" in fhtml

    @pytest.mark.asyncio
    async def test_sensitive_value_not_echoed_in_ack(self, handler: AudioFormWSHandler) -> None:
        """H-2: a sensitive answer is stored but its value is not echoed back (v1 wire)."""
        ws, ctx = await _boot(handler, _form(_fld("pw", FieldType.PASSWORD, label="PW")))
        await _say(handler, ws, ctx, type="answer_text", field_id="pw", value="s3cret")
        ack = _sent(ws)[0]
        assert ack["type"] == "answer_accepted"
        assert "value" not in ack
        assert "s3cret" not in str(_sent(ws))
        assert ctx.engine.state.answers["pw"].value == "s3cret"

    @pytest.mark.asyncio
    async def test_non_sensitive_value_still_echoed(self, handler: AudioFormWSHandler) -> None:
        """H-2 regression: non-sensitive answers still echo the value."""
        ws, ctx = await _boot(handler, _form(_fld("name", label="N")))
        await _say(handler, ws, ctx, type="answer_text", field_id="name", value="Alice")
        assert _sent(ws)[0]["value"] == "Alice"

    @pytest.mark.asyncio
    async def test_sensitive_speech_transcript_masked(
        self, handler: AudioFormWSHandler, mock_transcriber: AsyncMock
    ) -> None:
        """H-2: a sensitive speech transcript is masked in client messages."""
        _mock_stt(mock_transcriber, text="s3cret", confidence=0.95)
        ws, ctx = await _boot(handler, _form(_fld("pw", FieldType.PASSWORD, label="PW"), _fld("x")))
        ws.send_json.reset_mock()
        await handler._process_binary(ws, ctx, _FAKE_WEBM)
        assert _last(ws, "transcription")["text"] == "[hidden]"
        assert "s3cret" not in str(_sent(ws))
        assert ctx.engine.state.answers["pw"].value == "s3cret"  # real value stored

    @pytest.mark.asyncio
    async def test_answer_selection_wrong_field_rejected(self, handler: AudioFormWSHandler) -> None:
        """H-4: answering a non-current field is rejected and stores nothing."""
        ws, ctx = await _boot(handler, _form(
            _fld("color", FieldType.SELECT, options=[("red", "Red")]),
            _fld("size", FieldType.SELECT, options=[("big", "Big")])))
        await _say(handler, ws, ctx, type="answer_selection", field_id="size", value="big")
        assert _sent(ws)[0]["type"] == "error"
        assert "size" not in ctx.engine.state.answers

    @pytest.mark.asyncio
    async def test_confirm_field_mismatch_rejected(
        self, handler: AudioFormWSHandler, mock_transcriber: AsyncMock
    ) -> None:
        """M-1: confirm_answer for a field other than the pending one is rejected."""
        _mock_stt(mock_transcriber, text="A", confidence=0.2)
        ws, ctx = await _boot(handler, _form(_fld("name", label="N")))
        await handler._process_binary(ws, ctx, _FAKE_WEBM)
        await _say(handler, ws, ctx, type="confirm_answer", field_id="other", confirmed=True)
        assert _sent(ws)[0]["type"] == "error"
        assert "name" not in ctx.engine.state.answers
        assert ctx.engine.state.pending is not None  # not consumed

    @pytest.mark.asyncio
    async def test_auto_synthesize_shares_one_backend_per_config(
        self, handler: AudioFormWSHandler, monkeypatch
    ) -> None:
        """Round 3: one backend per (backend, voice, mime) across sessions; cooldown; cleanup closes them."""

        constructed: list[tuple[str, str]] = []
        closed: list[object] = []

        class _CountingSynth:
            def __init__(self, config=None) -> None:
                constructed.append((config.backend, config.mime_format))
                self.config = config

            async def synthesize(self, text, *, language=None):
                if self.config.backend == "supertonic":
                    raise RuntimeError("no weights")
                return SimpleNamespace(audio=b"WAV")

            async def close(self) -> None:
                closed.append(self)

        monkeypatch.setattr("parrot.voice.tts.synthesizer.VoiceSynthesizer", _CountingSynth)
        handler.synthesizer = None  # type: ignore[assignment]
        handler._auto_synthesize = True
        s1 = AudioSessionState(session_id="s1", form_uid="f1", user_id="u1")
        s2 = AudioSessionState(session_id="s2", form_uid="f1", user_id="u2")
        wav = AudioSessionConfig(form_uid="f1")
        mpeg = AudioSessionConfig(form_uid="f1", tts_mime_format="audio/mpeg")
        assert await handler._synthesize("hi", config=wav, session=s1) == b"WAV"
        assert await handler._synthesize("there", config=wav, session=s2) == b"WAV"
        # SuperTonic tried once (then cooling down); google built once and shared by both sessions.
        assert constructed.count(("supertonic", "audio/wav")) == 1
        assert constructed.count(("google", "audio/wav")) == 1
        assert len(handler._tts_backends) == 1
        # different mime → different instance
        assert await handler._synthesize("hi", config=mpeg, session=s1) == b"WAV"
        assert len(handler._tts_backends) == 2
        # a session ending never closes the shared backend; cleanup does
        assert closed.count(next(iter(handler._tts_backends.values()))) == 0
        shared = list(handler._tts_backends.values())
        await handler.close_tts_backends()
        assert all(b in closed for b in shared) and handler._tts_backends == {}

    @pytest.mark.asyncio
    async def test_failed_backend_cooldown_is_honoured(self, handler: AudioFormWSHandler, monkeypatch) -> None:

        attempts: list[str] = []

        class _Down:
            def __init__(self, config=None) -> None:
                self.config = config

            async def synthesize(self, text, *, language=None):
                attempts.append(self.config.backend)
                raise RuntimeError("down")

            async def close(self) -> None:
                return None

        monkeypatch.setattr("parrot.voice.tts.synthesizer.VoiceSynthesizer", _Down)
        handler.synthesizer = None  # type: ignore[assignment]
        handler._auto_synthesize = True
        session = AudioSessionState(session_id="s1", form_uid="f1", user_id="u1")
        cfg = AudioSessionConfig(form_uid="f1")
        assert await handler._synthesize("a", config=cfg, session=session) is None
        n = len(attempts)
        assert await handler._synthesize("b", config=cfg, session=session) is None
        assert len(attempts) == n  # both backends cooling down: no new attempts
        for k in handler._tts_unavailable:
            handler._tts_unavailable[k] = 0.0  # cooldown elapsed
        await handler._synthesize("c", config=cfg, session=session)
        assert len(attempts) > n

    @pytest.mark.asyncio
    async def test_auto_path_goes_through_segment_cache_and_lock(self, handler: AudioFormWSHandler) -> None:
        from types import SimpleNamespace

        from parrot_formdesigner.api.audio_ws import _AutoSynthAdapter, _ConnCtx
        from parrot_formdesigner.audio import segments as seg

        handler.synthesizer = None  # type: ignore[assignment]
        handler._auto_synthesize = True
        calls: list[str] = []

        async def fake_cached(session, text, *, config=None, language=None):
            calls.append(text)
            return b"WAV"

        handler._auto_synthesize_cached = fake_cached  # type: ignore[method-assign]
        state = AudioSessionState(session_id="s-auto", form_uid="f1", user_id="u1")
        ctx = _ConnCtx(request=None, user=None, tenant=None, state=state)
        ctx.form = SimpleNamespace(form_uid="f-auto-cache", version="1")
        ctx.segments = seg.AudioSegmentCache(_AutoSynthAdapter(handler, state), lock=seg._SYNTH_LOCK)
        seg._PROCESS_LRU.clear()
        first = await handler._synth_items(ctx, {"q:a:label": "Hello"})
        second = await handler._synth_items(ctx, {"q:a:label": "Hello"})
        assert first == second == {"q:a:label": b"WAV"}
        assert calls == ["Hello"]  # second call served by the shared cache
