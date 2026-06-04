"""Tests for FieldType.AUDIO enum member (FEAT-224 TASK-1459)."""

import pytest

from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.core.schema import FormField


class TestAudioFieldType:
    """Unit tests for the AUDIO FieldType enum member."""

    def test_audio_enum_exists(self):
        """FieldType.AUDIO is a valid enum member with value 'audio'."""
        assert hasattr(FieldType, "AUDIO")
        assert FieldType.AUDIO.value == "audio"

    def test_audio_from_value(self):
        """FieldType('audio') resolves to FieldType.AUDIO."""
        assert FieldType("audio") == FieldType.AUDIO

    def test_formfield_accepts_audio(self):
        """FormField validates with field_type=FieldType.AUDIO."""
        field = FormField(
            field_id="voice_note",
            field_type=FieldType.AUDIO,
            label="Leave a voice note",
        )
        assert field.field_type == FieldType.AUDIO

    def test_audio_is_str_enum(self):
        """FieldType.AUDIO behaves as a str (str Enum)."""
        assert isinstance(FieldType.AUDIO, str)
        assert FieldType.AUDIO == "audio"
