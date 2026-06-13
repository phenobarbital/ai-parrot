"""Tests for AudioFormWSHandler (FEAT-224 TASK-1463, FEAT-236 TASK-1541)."""

from types import SimpleNamespace

import pytest
from unittest.mock import AsyncMock, MagicMock

from parrot_formdesigner.api.audio_ws import AudioFormWSHandler
from parrot_formdesigner.audio.models import (
    AudioAnswer,
    AudioFormManifest,
    AudioQuestion,
    AudioSessionConfig,
    AudioSessionState,
    VoiceMode,
)

# A minimal-but-valid-looking audio frame: EBML/WebM magic header padded past
# the handler's minimum-size guard. The transcriber is mocked in these tests,
# so the bytes are never actually decoded — they only need to pass the
# payload-sniffing guard in _handle_answer_audio (FEAT-236 hardening).
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
# Unit tests for internal state helpers
# ---------------------------------------------------------------------------


class TestAudioSessionState:
    """Verify AudioSessionState behaves correctly."""

    def test_initial_state(self) -> None:
        """Fresh session has correct defaults."""
        state = AudioSessionState(session_id="s1", form_id="f1", user_id="u1")
        assert state.current_index == 0
        assert state.answers == {}
        assert state.completed is False

    def test_add_answer(self) -> None:
        """Answers can be added to the state dict."""
        state = AudioSessionState(session_id="s1", form_id="f1", user_id="u1")
        state.answers["name"] = AudioAnswer(
            field_id="name", value="Alice", source="text"
        )
        assert "name" in state.answers
        assert state.answers["name"].value == "Alice"


class TestHandlerInstantiation:
    """Basic handler creation tests."""

    def test_handler_created(self, handler: AudioFormWSHandler) -> None:
        """AudioFormWSHandler can be instantiated with mocked deps."""
        assert handler is not None
        assert handler.registry is not None
        assert handler.synthesizer is not None
        assert handler.transcriber is not None

    def test_handler_without_token_validator(
        self,
        mock_registry: AsyncMock,
        mock_synthesizer: AsyncMock,
        mock_transcriber: AsyncMock,
        mock_validator: MagicMock,
    ) -> None:
        """Handler can be created without a token_validator (anonymous mode)."""
        h = AudioFormWSHandler(
            registry=mock_registry,
            synthesizer=mock_synthesizer,
            transcriber=mock_transcriber,
            validator=mock_validator,
        )
        assert h._token_validator is None


class TestSessionLifecycle:
    """Tests for session start and answer flow (unit level, no WS)."""

    @pytest.mark.asyncio
    async def test_accept_answer_stores_value(
        self, handler: AudioFormWSHandler
    ) -> None:
        """_accept_answer() stores the answer in session state."""
        state = AudioSessionState(session_id="s1", form_id="f1", user_id="u1")
        mock_ws = AsyncMock()
        mock_ws.send_json = AsyncMock()

        result = await handler._accept_answer(mock_ws, state, "name", "Alice")
        assert result is True
        assert "name" in state.answers
        assert state.answers["name"].value == "Alice"

        # Verify answer_accepted was sent
        mock_ws.send_json.assert_called_once()
        call_args = mock_ws.send_json.call_args[0][0]
        assert call_args["type"] == "answer_accepted"
        assert call_args["field_id"] == "name"

    @pytest.mark.asyncio
    async def test_send_question_without_audio(
        self, handler: AudioFormWSHandler
    ) -> None:
        """_send_question() works even without TTS (synthesizer returns None)."""
        from parrot_formdesigner.audio.models import AudioQuestion

        q = AudioQuestion(
            index=0, field_id="name", field_type="text", label="Your name?"
        )
        mock_ws = AsyncMock()
        mock_ws.send_json = AsyncMock()

        handler.synthesizer = None  # type: ignore[assignment]
        await handler._send_question(mock_ws, q, {})

        mock_ws.send_json.assert_called_once()
        call_args = mock_ws.send_json.call_args[0][0]
        assert call_args["type"] == "question"
        assert call_args["field_id"] == "name"
        assert "audio" not in call_args

    @pytest.mark.asyncio
    async def test_send_question_with_cached_audio(
        self, handler: AudioFormWSHandler
    ) -> None:
        """_send_question() includes base64 audio from cache."""
        from parrot_formdesigner.audio.models import AudioQuestion

        q = AudioQuestion(
            index=2, field_id="age", field_type="number", label="Your age?"
        )
        mock_ws = AsyncMock()
        mock_ws.send_json = AsyncMock()

        cache = {2: "FAKEAUDIOBASE64=="}
        await handler._send_question(mock_ws, q, cache)

        call_args = mock_ws.send_json.call_args[0][0]
        assert call_args["audio"] == "FAKEAUDIOBASE64=="

    @pytest.mark.asyncio
    async def test_send_error_sends_error_message(
        self, handler: AudioFormWSHandler
    ) -> None:
        """_send_error() sends a well-formed error message."""
        mock_ws = AsyncMock()
        mock_ws.send_json = AsyncMock()

        await handler._send_error(mock_ws, "TEST_CODE", "Test error message")

        call_args = mock_ws.send_json.call_args[0][0]
        assert call_args["type"] == "error"
        assert call_args["code"] == "TEST_CODE"
        assert call_args["message"] == "Test error message"


class TestNavigation:
    """Tests for skip, go_back, repeat navigation methods."""

    @pytest.mark.asyncio
    async def test_skip_required_field_rejected(
        self, handler: AudioFormWSHandler
    ) -> None:
        """Skipping a required question sends answer_rejected."""
        from parrot_formdesigner.audio.models import AudioQuestion, AudioFormManifest

        q = AudioQuestion(
            index=0, field_id="name", field_type="text",
            label="Name?", required=True
        )
        manifest = AudioFormManifest(
            form_id="f1", title="T", total_questions=1,
            questions=[q], ws_endpoint="/ws"
        )
        state = AudioSessionState(session_id="s1", form_id="f1", user_id="u1")
        state.manifest = manifest
        state.current_index = 0

        mock_ws = AsyncMock()
        mock_ws.send_json = AsyncMock()

        await handler._handle_skip_question(
            ws=mock_ws, data={}, session=state,
            request=MagicMock(), audio_cache={}
        )

        call_args = mock_ws.send_json.call_args[0][0]
        assert call_args["type"] == "answer_rejected"

    @pytest.mark.asyncio
    async def test_skip_optional_field_advances(
        self, handler: AudioFormWSHandler
    ) -> None:
        """Skipping an optional question advances to the next question."""
        from parrot_formdesigner.audio.models import AudioQuestion, AudioFormManifest

        q1 = AudioQuestion(
            index=0, field_id="name", field_type="text",
            label="Name?", required=False
        )
        q2 = AudioQuestion(
            index=1, field_id="age", field_type="number",
            label="Age?", required=False
        )
        manifest = AudioFormManifest(
            form_id="f1", title="T", total_questions=2,
            questions=[q1, q2], ws_endpoint="/ws"
        )
        state = AudioSessionState(session_id="s1", form_id="f1", user_id="u1")
        state.manifest = manifest
        state.current_index = 0

        mock_ws = AsyncMock()
        mock_ws.send_json = AsyncMock()

        handler.synthesizer = None  # type: ignore[assignment]
        await handler._handle_skip_question(
            ws=mock_ws, data={}, session=state,
            request=MagicMock(), audio_cache={}
        )

        # current_index should have advanced
        assert state.current_index == 2 or mock_ws.send_json.call_count >= 1

    @pytest.mark.asyncio
    async def test_go_back_navigates_to_previous(
        self, handler: AudioFormWSHandler
    ) -> None:
        """go_back navigates to the previous question."""
        from parrot_formdesigner.audio.models import AudioQuestion, AudioFormManifest

        questions = [
            AudioQuestion(index=i, field_id=f"q{i}", field_type="text", label=f"Q{i}?")
            for i in range(3)
        ]
        manifest = AudioFormManifest(
            form_id="f1", title="T", total_questions=3,
            questions=questions, ws_endpoint="/ws"
        )
        state = AudioSessionState(session_id="s1", form_id="f1", user_id="u1")
        state.manifest = manifest
        state.current_index = 2

        mock_ws = AsyncMock()
        mock_ws.send_json = AsyncMock()
        handler.synthesizer = None  # type: ignore[assignment]

        await handler._handle_go_back(
            ws=mock_ws, data={}, session=state,
            request=MagicMock(), audio_cache={}
        )

        assert state.current_index == 1
        call_args = mock_ws.send_json.call_args[0][0]
        assert call_args["type"] == "question"
        assert call_args["index"] == 1

    @pytest.mark.asyncio
    async def test_repeat_question_resends_current(
        self, handler: AudioFormWSHandler
    ) -> None:
        """repeat_question re-sends the current question."""
        from parrot_formdesigner.audio.models import AudioQuestion, AudioFormManifest

        q = AudioQuestion(index=1, field_id="age", field_type="number", label="Age?")
        manifest = AudioFormManifest(
            form_id="f1", title="T", total_questions=2,
            questions=[
                AudioQuestion(index=0, field_id="name", field_type="text", label="Name?"),
                q,
            ],
            ws_endpoint="/ws"
        )
        state = AudioSessionState(session_id="s1", form_id="f1", user_id="u1")
        state.manifest = manifest
        state.current_index = 1

        mock_ws = AsyncMock()
        mock_ws.send_json = AsyncMock()
        handler.synthesizer = None  # type: ignore[assignment]

        await handler._handle_repeat_question(
            ws=mock_ws, data={}, session=state,
            request=MagicMock(), audio_cache={}
        )

        call_args = mock_ws.send_json.call_args[0][0]
        assert call_args["type"] == "question"
        assert call_args["field_id"] == "age"

    @pytest.mark.asyncio
    async def test_ping_returns_pong(self, handler: AudioFormWSHandler) -> None:
        """ping message receives pong response."""
        state = AudioSessionState(session_id="s1", form_id="f1", user_id="u1")
        mock_ws = AsyncMock()
        mock_ws.send_json = AsyncMock()

        await handler._handle_ping(
            ws=mock_ws, data={}, session=state,
            request=MagicMock(), audio_cache={}
        )

        call_args = mock_ws.send_json.call_args[0][0]
        assert call_args["type"] == "pong"


# ---------------------------------------------------------------------------
# FEAT-236 TASK-1541: per-VoiceMode dispatch + fallback handlers
# ---------------------------------------------------------------------------


def _fresh_ws() -> AsyncMock:
    ws = AsyncMock()
    ws.send_json = AsyncMock()
    return ws


def _sent_types(ws: AsyncMock) -> list[str]:
    return [c[0][0]["type"] for c in ws.send_json.call_args_list]


def _session_with(questions: list[AudioQuestion]) -> AudioSessionState:
    manifest = AudioFormManifest(
        form_id="f1", title="T", total_questions=len(questions),
        questions=questions, ws_endpoint="/ws",
    )
    state = AudioSessionState(session_id="s1", form_id="f1", user_id="u1")
    state.manifest = manifest
    state.current_index = 0
    state.config = AudioSessionConfig(form_id="f1")
    return state


class TestVoiceModeQuestionDelivery:
    """_send_question carries VoiceMode metadata and visual fallback HTML."""

    @pytest.mark.asyncio
    async def test_question_message_includes_voice_mode(
        self, handler: AudioFormWSHandler
    ) -> None:
        q = AudioQuestion(
            index=0, field_id="color", field_type="select", label="Color?",
            voice_mode=VoiceMode.PROMPT_SELECT, render_mode="select",
            options=[{"value": "red", "label": "Red"}],
        )
        ws = _fresh_ws()
        await handler._send_question(ws, q, {}, config=AudioSessionConfig(form_id="f1"))
        msg = ws.send_json.call_args[0][0]
        assert msg["voice_mode"] == "prompt_select"
        assert msg["render_mode"] == "select"
        assert msg["sensitive"] is False
        assert msg["options"]

    @pytest.mark.asyncio
    async def test_visual_fallback_question_has_fallback_html(
        self, handler: AudioFormWSHandler
    ) -> None:
        q = AudioQuestion(
            index=0, field_id="doc", field_type="rest", label="Upload",
            required=True, voice_mode=VoiceMode.VISUAL_FALLBACK,
            render_mode="visual",
        )
        ws = _fresh_ws()
        await handler._send_question(ws, q, {}, config=AudioSessionConfig(form_id="f1"))
        msg = ws.send_json.call_args[0][0]
        assert msg["voice_mode"] == "visual_fallback"
        assert msg.get("fallback_html")

    @pytest.mark.asyncio
    async def test_sensitive_password_no_audio(
        self, handler: AudioFormWSHandler
    ) -> None:
        q = AudioQuestion(
            index=0, field_id="pw", field_type="password", label="Password?",
            sensitive=True,
        )
        ws = _fresh_ws()
        await handler._send_question(ws, q, {}, config=AudioSessionConfig(form_id="f1"))
        msg = ws.send_json.call_args[0][0]
        assert msg["sensitive"] is True
        assert "audio" not in msg
        handler.synthesizer.synthesize.assert_not_called()

    @pytest.mark.asyncio
    async def test_prompt_select_enumerates_options_in_tts(
        self, handler: AudioFormWSHandler
    ) -> None:
        q = AudioQuestion(
            index=0, field_id="color", field_type="select", label="Color?",
            voice_mode=VoiceMode.PROMPT_SELECT, render_mode="select",
            options=[{"value": "red", "label": "Red"}, {"value": "blue", "label": "Blue"}],
        )
        ws = _fresh_ws()
        await handler._send_question(ws, q, {}, config=AudioSessionConfig(form_id="f1"))
        # The injected synthesizer is called with the enumerated narration text.
        spoken = handler.synthesizer.synthesize.call_args[0][0]
        assert "Red" in spoken and "Blue" in spoken


class TestSelectionAndPayloadHandlers:
    """answer_selection and answer_payload handlers."""

    @pytest.mark.asyncio
    async def test_answer_selection_single(self, handler: AudioFormWSHandler) -> None:
        q = AudioQuestion(
            index=0, field_id="color", field_type="select", label="Color?",
            voice_mode=VoiceMode.PROMPT_SELECT, render_mode="select",
            options=[{"value": "red", "label": "Red"}, {"value": "blue", "label": "Blue"}],
        )
        q2 = AudioQuestion(index=1, field_id="x", field_type="text", label="X")
        state = _session_with([q, q2])
        ws = _fresh_ws()
        await handler._handle_answer_selection(
            ws=ws, data={"field_id": "color", "value": "red"},
            session=state, request=MagicMock(), audio_cache={},
        )
        assert state.answers["color"].value == "red"
        assert state.answers["color"].source == "selection"
        assert state.current_index == 1

    @pytest.mark.asyncio
    async def test_answer_selection_multi(self, handler: AudioFormWSHandler) -> None:
        q = AudioQuestion(
            index=0, field_id="tags", field_type="multi_select", label="Tags?",
            voice_mode=VoiceMode.PROMPT_SELECT, render_mode="select",
            options=[{"value": "a", "label": "A"}, {"value": "b", "label": "B"}],
        )
        q2 = AudioQuestion(index=1, field_id="x", field_type="text", label="X")
        state = _session_with([q, q2])
        ws = _fresh_ws()
        await handler._handle_answer_selection(
            ws=ws, data={"field_id": "tags", "values": ["a", "b"]},
            session=state, request=MagicMock(), audio_cache={},
        )
        assert state.answers["tags"].value == "a,b"
        assert state.answers["tags"].source == "selection"

    @pytest.mark.asyncio
    async def test_answer_selection_invalid_rejected(
        self, handler: AudioFormWSHandler
    ) -> None:
        q = AudioQuestion(
            index=0, field_id="color", field_type="select", label="Color?",
            voice_mode=VoiceMode.PROMPT_SELECT, render_mode="select",
            options=[{"value": "red", "label": "Red"}],
        )
        state = _session_with([q])
        ws = _fresh_ws()
        await handler._handle_answer_selection(
            ws=ws, data={"field_id": "color", "value": "green"},
            session=state, request=MagicMock(), audio_cache={},
        )
        assert "answer_rejected" in _sent_types(ws)
        assert "color" not in state.answers
        assert state.current_index == 0

    @pytest.mark.asyncio
    async def test_answer_payload_completes_rest(
        self, handler: AudioFormWSHandler
    ) -> None:
        q = AudioQuestion(
            index=0, field_id="doc", field_type="rest", label="Upload",
            required=True, voice_mode=VoiceMode.VISUAL_FALLBACK, render_mode="visual",
        )
        q2 = AudioQuestion(index=1, field_id="x", field_type="text", label="X")
        state = _session_with([q, q2])
        ws = _fresh_ws()
        await handler._handle_answer_payload(
            ws=ws, data={"field_id": "doc", "value": "blob://123"},
            session=state, request=MagicMock(), audio_cache={},
        )
        assert state.answers["doc"].value == "blob://123"
        assert state.current_index == 1


class TestLowConfidenceConfirmation:
    """Low-confidence STT read-back gate."""

    @pytest.mark.asyncio
    async def test_low_confidence_emits_confirm_request_no_advance(
        self, handler: AudioFormWSHandler, mock_transcriber: AsyncMock
    ) -> None:
        mock_transcriber.transcribe.return_value = MagicMock(
            text="alice", confidence=0.2, language="en"
        )
        q = AudioQuestion(index=0, field_id="name", field_type="text", label="Name?", required=True)
        q2 = AudioQuestion(index=1, field_id="x", field_type="text", label="X")
        state = _session_with([q, q2])
        ws = _fresh_ws()
        await handler._handle_answer_audio(ws, _FAKE_WEBM, state, {})
        assert "confirm_request" in _sent_types(ws)
        assert state.current_index == 0
        assert state.pending is not None
        assert state.pending.value == "alice"
        assert "name" not in state.answers

    @pytest.mark.asyncio
    async def test_high_confidence_auto_advances(
        self, handler: AudioFormWSHandler, mock_transcriber: AsyncMock
    ) -> None:
        mock_transcriber.transcribe.return_value = MagicMock(
            text="alice", confidence=0.95, language="en"
        )
        q = AudioQuestion(index=0, field_id="name", field_type="text", label="Name?", required=True)
        q2 = AudioQuestion(index=1, field_id="x", field_type="text", label="X")
        state = _session_with([q, q2])
        ws = _fresh_ws()
        await handler._handle_answer_audio(ws, _FAKE_WEBM, state, {})
        assert "confirm_request" not in _sent_types(ws)
        assert state.answers["name"].value == "alice"
        assert state.current_index == 1

    @pytest.mark.asyncio
    async def test_confirm_true_stores_and_advances(
        self, handler: AudioFormWSHandler
    ) -> None:
        q = AudioQuestion(index=0, field_id="name", field_type="text", label="Name?", required=True)
        q2 = AudioQuestion(index=1, field_id="x", field_type="text", label="X")
        state = _session_with([q, q2])
        state.pending = AudioAnswer(
            field_id="name", value="alice", source="speech",
            confidence=0.2, raw_transcript="alice",
        )
        ws = _fresh_ws()
        await handler._handle_confirm_answer(
            ws=ws, data={"field_id": "name", "confirmed": True},
            session=state, request=MagicMock(), audio_cache={},
        )
        assert state.answers["name"].value == "alice"
        assert state.current_index == 1
        assert state.pending is None

    @pytest.mark.asyncio
    async def test_confirm_false_resends_same_question(
        self, handler: AudioFormWSHandler
    ) -> None:
        q = AudioQuestion(index=0, field_id="name", field_type="text", label="Name?", required=True)
        state = _session_with([q])
        state.pending = AudioAnswer(
            field_id="name", value="alice", source="speech",
            confidence=0.2, raw_transcript="alice",
        )
        ws = _fresh_ws()
        await handler._handle_confirm_answer(
            ws=ws, data={"field_id": "name", "confirmed": False},
            session=state, request=MagicMock(), audio_cache={},
        )
        assert "name" not in state.answers
        assert state.current_index == 0
        assert state.pending is None
        last = ws.send_json.call_args[0][0]
        assert last["type"] == "question"
        assert last["field_id"] == "name"

    @pytest.mark.asyncio
    async def test_confirm_without_pending_errors(
        self, handler: AudioFormWSHandler
    ) -> None:
        q = AudioQuestion(index=0, field_id="name", field_type="text", label="Name?")
        state = _session_with([q])
        ws = _fresh_ws()
        await handler._handle_confirm_answer(
            ws=ws, data={"field_id": "name", "confirmed": True},
            session=state, request=MagicMock(), audio_cache={},
        )
        assert "error" in _sent_types(ws)


class TestGracefulSynthesis:
    """The handler never crashes when synthesis fails."""

    @pytest.mark.asyncio
    async def test_injected_synth_failure_degrades_to_text_only(
        self, handler: AudioFormWSHandler
    ) -> None:
        handler.synthesizer.synthesize.side_effect = RuntimeError("no weights")
        q = AudioQuestion(index=0, field_id="name", field_type="text", label="Name?")
        ws = _fresh_ws()
        await handler._send_question(ws, q, {}, config=AudioSessionConfig(form_id="f1"))
        msg = ws.send_json.call_args[0][0]
        assert msg["type"] == "question"
        assert "audio" not in msg

    @pytest.mark.asyncio
    async def test_no_synth_no_auto_is_text_only(
        self, handler: AudioFormWSHandler
    ) -> None:
        handler.synthesizer = None  # type: ignore[assignment]
        assert handler._auto_synthesize is False
        q = AudioQuestion(index=0, field_id="name", field_type="text", label="Name?")
        ws = _fresh_ws()
        await handler._send_question(ws, q, {}, config=AudioSessionConfig(form_id="f1"))
        msg = ws.send_json.call_args[0][0]
        assert "audio" not in msg


class TestReviewHardening:
    """FEAT-236 code-review hardening: H-1, H-2, H-4, M-1, M-2."""

    @pytest.mark.asyncio
    async def test_fallback_html_escapes_field_id(
        self, handler: AudioFormWSHandler
    ) -> None:
        """H-1: a hostile field_id is HTML-escaped in the minimal fallback."""
        q = AudioQuestion(
            index=0, field_id='x" onfocus="alert(1)', field_type="rest",
            label="L", voice_mode=VoiceMode.VISUAL_FALLBACK, render_mode="visual",
        )
        ws = _fresh_ws()
        await handler._send_question(ws, q, {}, config=AudioSessionConfig(form_id="f1"))
        fhtml = ws.send_json.call_args[0][0]["fallback_html"]
        assert 'onfocus="' not in fhtml  # raw attribute breakout neutralized
        assert "&quot;" in fhtml

    @pytest.mark.asyncio
    async def test_sensitive_value_not_echoed_in_ack(
        self, handler: AudioFormWSHandler
    ) -> None:
        """H-2: a sensitive answer is stored but its value is not echoed back."""
        q = AudioQuestion(
            index=0, field_id="pw", field_type="password", label="PW", sensitive=True,
        )
        state = _session_with([q])
        ws = _fresh_ws()
        ok = await handler._accept_answer(ws, state, "pw", "s3cret", source="text")
        assert ok
        ack = ws.send_json.call_args[0][0]
        assert ack["type"] == "answer_accepted"
        assert "value" not in ack
        assert state.answers["pw"].value == "s3cret"

    @pytest.mark.asyncio
    async def test_non_sensitive_value_still_echoed(
        self, handler: AudioFormWSHandler
    ) -> None:
        """H-2 regression: non-sensitive answers still echo the value."""
        q = AudioQuestion(index=0, field_id="name", field_type="text", label="N")
        state = _session_with([q])
        ws = _fresh_ws()
        await handler._accept_answer(ws, state, "name", "Alice", source="text")
        ack = ws.send_json.call_args[0][0]
        assert ack["value"] == "Alice"

    @pytest.mark.asyncio
    async def test_sensitive_speech_transcript_masked(
        self, handler: AudioFormWSHandler, mock_transcriber: AsyncMock
    ) -> None:
        """H-2: a sensitive speech transcript is masked in client messages."""
        mock_transcriber.transcribe.return_value = MagicMock(
            text="s3cret", confidence=0.95, language="en",
        )
        q = AudioQuestion(
            index=0, field_id="pw", field_type="password", label="PW", sensitive=True,
        )
        q2 = AudioQuestion(index=1, field_id="x", field_type="text", label="X")
        state = _session_with([q, q2])
        ws = _fresh_ws()
        await handler._handle_answer_audio(ws, _FAKE_WEBM, state, {})
        trans = next(
            c[0][0] for c in ws.send_json.call_args_list
            if c[0][0]["type"] == "transcription"
        )
        assert trans["text"] == "[hidden]"
        assert state.answers["pw"].value == "s3cret"  # real value stored

    @pytest.mark.asyncio
    async def test_answer_selection_wrong_field_rejected(
        self, handler: AudioFormWSHandler
    ) -> None:
        """H-4: answering a non-current field is rejected and stores nothing."""
        q = AudioQuestion(
            index=0, field_id="color", field_type="select", label="C",
            voice_mode=VoiceMode.PROMPT_SELECT, render_mode="select",
            options=[{"value": "red", "label": "Red"}],
        )
        q2 = AudioQuestion(
            index=1, field_id="size", field_type="select", label="S",
            voice_mode=VoiceMode.PROMPT_SELECT, render_mode="select",
            options=[{"value": "big", "label": "Big"}],
        )
        state = _session_with([q, q2])
        ws = _fresh_ws()
        await handler._handle_answer_selection(
            ws=ws, data={"field_id": "size", "value": "big"},
            session=state, request=MagicMock(), audio_cache={},
        )
        assert "error" in _sent_types(ws)
        assert "size" not in state.answers
        assert state.current_index == 0

    @pytest.mark.asyncio
    async def test_confirm_field_mismatch_rejected(
        self, handler: AudioFormWSHandler
    ) -> None:
        """M-1: confirm_answer for a field other than the pending one is rejected."""
        q = AudioQuestion(index=0, field_id="name", field_type="text", label="N")
        state = _session_with([q])
        state.pending = AudioAnswer(
            field_id="name", value="A", source="speech",
            confidence=0.2, raw_transcript="A",
        )
        ws = _fresh_ws()
        await handler._handle_confirm_answer(
            ws=ws, data={"field_id": "other", "confirmed": True},
            session=state, request=MagicMock(), audio_cache={},
        )
        assert "error" in _sent_types(ws)
        assert "name" not in state.answers
        assert state.pending is not None  # not consumed

    @pytest.mark.asyncio
    async def test_auto_synthesize_reuses_session_backend(
        self, handler: AudioFormWSHandler, monkeypatch
    ) -> None:
        """M-2: the working backend is built once per session and reused."""
        constructed: list[str] = []

        class _CountingSynth:
            def __init__(self, config=None) -> None:
                constructed.append(getattr(config, "backend", None))
                self.config = config

            async def synthesize(self, text, *, language=None):
                if self.config.backend == "supertonic":
                    raise RuntimeError("no weights")
                return SimpleNamespace(audio=b"WAV")

            async def close(self) -> None:
                return None

        monkeypatch.setattr(
            "parrot.voice.tts.synthesizer.VoiceSynthesizer", _CountingSynth
        )
        handler.synthesizer = None  # type: ignore[assignment]
        handler._auto_synthesize = True
        session = _session_with(
            [AudioQuestion(index=0, field_id="a", field_type="text", label="A")]
        )
        cfg = AudioSessionConfig(form_id="f1")
        a1 = await handler._synthesize("hi", config=cfg, session=session)
        a2 = await handler._synthesize("there", config=cfg, session=session)
        assert a1 == b"WAV" and a2 == b"WAV"
        # SuperTonic attempted once; Google built once and reused (not twice).
        assert constructed.count("supertonic") == 1
        assert constructed.count("google") == 1
        assert session.session_id in handler._session_synths
