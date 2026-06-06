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
def mock_synthesizer() -> AsyncMock:
    """Mock VoiceSynthesizer returning dummy audio bytes."""
    synth = AsyncMock()
    synth.synthesize.return_value = MagicMock(
        audio=b"fake-tts-audio", mime_format="audio/ogg"
    )
    return synth


@pytest.fixture
def mock_transcriber() -> AsyncMock:
    """Mock FasterWhisperBackend returning fixed transcription."""
    transcriber = AsyncMock()
    transcriber.transcribe.return_value = MagicMock(
        text="hello world", confidence=0.95, language="en",
        duration_seconds=1.5, processing_time_ms=200,
    )
    return transcriber
