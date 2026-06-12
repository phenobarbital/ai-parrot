"""Shared test fixtures for formdesigner audio tests (FEAT-224)."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection
from parrot_formdesigner.core.types import FieldType


@pytest.fixture
def sample_audio_form() -> FormSchema:
    """A simple 3-question form for audio testing (from spec §4)."""
    return FormSchema(
        form_id="test-audio-001",
        title="Audio Test Form",
        sections=[
            FormSection(
                section_id="s1",
                title="Personal Info",
                fields=[
                    FormField(
                        field_id="name",
                        field_type=FieldType.TEXT,
                        label="What is your name?",
                        required=True,
                    ),
                    FormField(
                        field_id="age",
                        field_type=FieldType.NUMBER,
                        label="How old are you?",
                    ),
                    FormField(
                        field_id="voice_note",
                        field_type=FieldType.AUDIO,
                        label="Please leave a voice note",
                    ),
                ],
            )
        ],
    )


@pytest.fixture
def mixed_mode_form() -> FormSchema:
    """A form exercising all three FEAT-236 VoiceModes.

    A TEXT question (VOICE), a SELECT question (PROMPT_SELECT), and a required
    REST question (VISUAL_FALLBACK) so the hybrid flow can be exercised
    end-to-end (spec §4 fixtures).
    """
    from parrot_formdesigner.core.options import FieldOption

    return FormSchema(
        form_id="mixed-mode-form",
        title="Mixed Mode Form",
        sections=[
            FormSection(
                section_id="s1",
                title="Mixed",
                fields=[
                    FormField(
                        field_id="name",
                        field_type=FieldType.TEXT,
                        label="What is your name?",
                        required=True,
                    ),
                    FormField(
                        field_id="color",
                        field_type=FieldType.SELECT,
                        label="Favorite color?",
                        options=[
                            FieldOption(value="red", label="Red"),
                            FieldOption(value="green", label="Green"),
                            FieldOption(value="blue", label="Blue"),
                        ],
                    ),
                    FormField(
                        field_id="doc",
                        field_type=FieldType.REST,
                        label="Upload supporting document",
                        required=True,
                    ),
                ],
            )
        ],
    )


@pytest.fixture
def mock_synthesizer() -> AsyncMock:
    """Mock VoiceSynthesizer returning dummy WAV audio bytes (FEAT-236).

    Configure ``synth.synthesize.side_effect`` in a test to simulate a backend
    that raises (exercising graceful degradation to text-only).
    """
    synth = AsyncMock()
    synth.synthesize.return_value = MagicMock(
        audio=b"fake-tts-wav", mime_format="audio/wav"
    )
    return synth


@pytest.fixture
def mock_transcriber() -> AsyncMock:
    """Mock FasterWhisperBackend returning fixed transcription.

    Configure ``transcriber.transcribe.return_value`` in a test to set a
    specific ``.confidence`` for the low-confidence read-back gate (FEAT-236).
    """
    transcriber = AsyncMock()
    transcriber.transcribe.return_value = MagicMock(
        text="hello world", confidence=0.95, language="en",
        duration_seconds=1.5, processing_time_ms=200,
    )
    return transcriber
