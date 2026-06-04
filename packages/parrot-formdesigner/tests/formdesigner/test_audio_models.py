"""Tests for audio form session data models (FEAT-224 TASK-1460)."""

import pytest
from pydantic import ValidationError

from parrot_formdesigner.audio.models import (
    AudioAnswer,
    AudioFormManifest,
    AudioQuestion,
    AudioSessionConfig,
    AudioSessionState,
)


class TestAudioSessionConfig:
    """Tests for AudioSessionConfig model."""

    def test_defaults(self):
        """AudioSessionConfig has correct default values."""
        cfg = AudioSessionConfig(form_id="f1")
        assert cfg.locale == "en"
        assert cfg.tts_mime_format == "audio/ogg"
        assert cfg.auto_advance is True
        assert cfg.tts_voice is None

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


class TestAudioQuestion:
    """Tests for AudioQuestion model."""

    def test_minimal(self):
        """AudioQuestion validates with minimal required fields."""
        q = AudioQuestion(index=0, field_id="name", field_type="text", label="Name?")
        assert q.required is False
        assert q.audio_prompt is None
        assert q.options is None

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
