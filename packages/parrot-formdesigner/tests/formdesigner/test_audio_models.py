"""Tests for audio form session data models (FEAT-224 TASK-1460)."""

import pytest
from pydantic import ValidationError

from parrot_formdesigner.audio.models import (
    AudioAnswer,
    AudioFormManifest,
    AudioQuestion,
    AudioSessionConfig,
    AudioSessionState,
    VoiceMode,
)


class TestAudioSessionConfig:
    """Tests for AudioSessionConfig model."""

    def test_defaults(self):
        """AudioSessionConfig has correct default values."""
        cfg = AudioSessionConfig(form_id="f1")
        assert cfg.locale == "en"
        assert cfg.tts_mime_format == "audio/wav"
        assert cfg.auto_advance is True
        assert cfg.tts_voice is None

    def test_supertonic_defaults(self):
        """FEAT-236: SuperTonic-first defaults and STT confirm threshold."""
        cfg = AudioSessionConfig(form_id="x")
        assert cfg.tts_backend == "supertonic"
        assert cfg.stt_confirm_threshold == 0.6
        assert cfg.enumerate_options is True
        assert cfg.tts_mime_format == "audio/wav"

    def test_stt_confirm_threshold_bounds(self):
        """stt_confirm_threshold is bounded to the 0.0–1.0 range."""
        assert AudioSessionConfig(form_id="x", stt_confirm_threshold=0.0)
        assert AudioSessionConfig(form_id="x", stt_confirm_threshold=1.0)
        with pytest.raises(ValidationError):
            AudioSessionConfig(form_id="x", stt_confirm_threshold=1.5)
        with pytest.raises(ValidationError):
            AudioSessionConfig(form_id="x", stt_confirm_threshold=-0.1)

    def test_tts_backend_rejects_unknown(self):
        """tts_backend only accepts 'supertonic' or 'google'."""
        with pytest.raises(ValidationError):
            AudioSessionConfig(form_id="x", tts_backend="elevenlabs")

    def test_requires_form_id(self):
        """AudioSessionConfig raises ValidationError when form_id is missing."""
        with pytest.raises(ValidationError):
            AudioSessionConfig()  # type: ignore[call-arg]

    def test_custom_values(self):
        """AudioSessionConfig accepts custom locale and voice."""
        cfg = AudioSessionConfig(form_id="f1", locale="es", tts_voice="Wavenet-A")
        assert cfg.locale == "es"
        assert cfg.tts_voice == "Wavenet-A"

    def test_extra_fields_forbidden(self):
        """AudioSessionConfig rejects extra fields."""
        with pytest.raises(ValidationError):
            AudioSessionConfig(form_id="f1", unknown_field="x")


class TestVoiceMode:
    """Tests for the FEAT-236 VoiceMode taxonomy enum."""

    def test_voice_mode_enum_values(self):
        """VoiceMode exposes VOICE, PROMPT_SELECT, VISUAL_FALLBACK."""
        assert {m.value for m in VoiceMode} >= {
            "voice", "prompt_select", "visual_fallback"
        }

    def test_voice_mode_is_str_enum(self):
        """VoiceMode members compare equal to their string values."""
        assert VoiceMode.VOICE == "voice"
        assert VoiceMode.PROMPT_SELECT == "prompt_select"
        assert VoiceMode.VISUAL_FALLBACK == "visual_fallback"


class TestAudioQuestion:
    """Tests for AudioQuestion model."""

    def test_minimal(self):
        """AudioQuestion validates with minimal required fields."""
        q = AudioQuestion(index=0, field_id="name", field_type="text", label="Name?")
        assert q.required is False
        assert q.audio_prompt is None
        assert q.options is None

    def test_voice_fields_default(self):
        """FEAT-236: new voice fields default to VOICE / 'voice' / False / None."""
        q = AudioQuestion(index=0, field_id="f", field_type="text", label="L")
        assert q.voice_mode == VoiceMode.VOICE
        assert q.render_mode == "voice"
        assert q.sensitive is False
        assert q.fallback_html is None

    def test_voice_fields_custom(self):
        """FEAT-236: voice fields accept explicit VISUAL_FALLBACK values."""
        q = AudioQuestion(
            index=0, field_id="f", field_type="rest", label="L",
            voice_mode=VoiceMode.VISUAL_FALLBACK, render_mode="visual",
            sensitive=True, fallback_html="<input name='f'>",
        )
        assert q.voice_mode == VoiceMode.VISUAL_FALLBACK
        assert q.render_mode == "visual"
        assert q.sensitive is True
        assert q.fallback_html == "<input name='f'>"

    def test_render_mode_rejects_unknown(self):
        """render_mode only accepts voice/select/visual."""
        with pytest.raises(ValidationError):
            AudioQuestion(index=0, field_id="f", field_type="text",
                          label="L", render_mode="audio")  # type: ignore[arg-type]

    def test_with_options(self):
        """AudioQuestion stores options list for SELECT fields."""
        q = AudioQuestion(
            index=1,
            field_id="color",
            field_type="select",
            label="Favorite color?",
            options=[{"value": "red", "label": "Red"}],
        )
        assert len(q.options) == 1
        assert q.options[0]["value"] == "red"

    def test_with_audio_prompt(self):
        """AudioQuestion stores raw bytes as audio_prompt."""
        q = AudioQuestion(
            index=0, field_id="name", field_type="text",
            label="Name?", audio_prompt=b"fake-audio"
        )
        assert q.audio_prompt == b"fake-audio"

    def test_required_field(self):
        """AudioQuestion.required defaults to False and can be set to True."""
        q = AudioQuestion(index=0, field_id="name", field_type="text",
                          label="Name?", required=True)
        assert q.required is True


class TestAudioFormManifest:
    """Tests for AudioFormManifest model."""

    def test_minimal_manifest(self):
        """AudioFormManifest validates with required fields."""
        q = AudioQuestion(index=0, field_id="name", field_type="text", label="Name?")
        manifest = AudioFormManifest(
            form_id="f1",
            title="Test Form",
            total_questions=1,
            questions=[q],
            ws_endpoint="/api/v1/forms/f1/audio/ws",
        )
        assert manifest.total_questions == 1
        assert manifest.locale == "en"

    def test_questions_list(self):
        """AudioFormManifest holds multiple questions."""
        questions = [
            AudioQuestion(index=i, field_id=f"q{i}", field_type="text", label=f"Q{i}?")
            for i in range(3)
        ]
        manifest = AudioFormManifest(
            form_id="f1",
            title="Test Form",
            total_questions=3,
            questions=questions,
            ws_endpoint="/api/v1/forms/f1/audio/ws",
        )
        assert len(manifest.questions) == 3


class TestAudioAnswer:
    """Tests for AudioAnswer model."""

    def test_text_source(self):
        """AudioAnswer with source='text' has no confidence."""
        a = AudioAnswer(field_id="name", value="Alice", source="text")
        assert a.confidence is None
        assert a.raw_transcript is None

    def test_speech_source(self):
        """AudioAnswer with source='speech' stores confidence."""
        a = AudioAnswer(field_id="name", value="Alice", source="speech", confidence=0.95)
        assert a.confidence == 0.95

    def test_default_source(self):
        """AudioAnswer source defaults to 'text'."""
        a = AudioAnswer(field_id="name", value="Bob")
        assert a.source == "text"

    def test_selection_source(self):
        """FEAT-236: AudioAnswer accepts source='selection'."""
        a = AudioAnswer(field_id="color", value="red", source="selection")
        assert a.source == "selection"

    def test_invalid_source(self):
        """AudioAnswer rejects invalid source values."""
        with pytest.raises(ValidationError):
            AudioAnswer(field_id="name", value="x", source="video")  # type: ignore[arg-type]


class TestAudioSessionState:
    """Tests for AudioSessionState model."""

    def test_initial_state(self):
        """AudioSessionState initializes with correct defaults."""
        state = AudioSessionState(session_id="s1", form_id="f1", user_id="u1")
        assert state.current_index == 0
        assert state.answers == {}
        assert state.completed is False
        assert state.manifest is None

    def test_add_answer(self):
        """AudioSessionState can accumulate answers."""
        state = AudioSessionState(session_id="s1", form_id="f1", user_id="u1")
        state.answers["name"] = AudioAnswer(field_id="name", value="Alice", source="text")
        assert "name" in state.answers
        assert state.answers["name"].value == "Alice"

    def test_advance_index(self):
        """AudioSessionState.current_index can be incremented."""
        state = AudioSessionState(session_id="s1", form_id="f1", user_id="u1")
        state.current_index = 2
        assert state.current_index == 2

    def test_mark_completed(self):
        """AudioSessionState.completed can be set to True."""
        state = AudioSessionState(session_id="s1", form_id="f1", user_id="u1")
        state.completed = True
        assert state.completed is True
