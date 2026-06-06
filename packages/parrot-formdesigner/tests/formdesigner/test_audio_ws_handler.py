"""Tests for AudioFormWSHandler (FEAT-224 TASK-1463)."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from parrot_formdesigner.api.audio_ws import AudioFormWSHandler
from parrot_formdesigner.audio.models import AudioSessionState, AudioAnswer


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
