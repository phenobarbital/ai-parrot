"""Tests for Audio Control Metadata Registration (FEAT-224 TASK-1465)."""

import pytest

from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.controls.builtin import _BUILTIN_METADATA


class TestAudioControlMetadata:
    """Tests for FieldType.AUDIO entry in _BUILTIN_METADATA."""

    def test_audio_in_builtin_metadata(self) -> None:
        """FieldType.AUDIO has an entry in _BUILTIN_METADATA."""
        assert FieldType.AUDIO in _BUILTIN_METADATA

    def test_audio_metadata_fields(self) -> None:
        """AUDIO metadata has all required fields."""
        meta = _BUILTIN_METADATA[FieldType.AUDIO]
        assert meta["label"] == "Audio"
        assert "category" in meta
        assert "icon" in meta
        assert meta["is_container"] is False

    def test_audio_category_is_advanced(self) -> None:
        """AUDIO field type is in the 'advanced' category."""
        meta = _BUILTIN_METADATA[FieldType.AUDIO]
        assert meta["category"] == "advanced"

    def test_audio_icon_is_microphone(self) -> None:
        """AUDIO field type has 'microphone' icon."""
        meta = _BUILTIN_METADATA[FieldType.AUDIO]
        assert meta["icon"] == "microphone"

    def test_audio_render_hint(self) -> None:
        """AUDIO field type has 'audio-recorder' render hint."""
        meta = _BUILTIN_METADATA[FieldType.AUDIO]
        assert meta["render_hint"] == "audio-recorder"

    def test_audio_supports_constraints_false(self) -> None:
        """AUDIO field type does not support constraints."""
        meta = _BUILTIN_METADATA[FieldType.AUDIO]
        assert meta["supports_constraints"] is False

    def test_audio_description_present(self) -> None:
        """AUDIO field type has a non-empty description."""
        meta = _BUILTIN_METADATA[FieldType.AUDIO]
        assert meta["description"]
        assert len(meta["description"]) > 0
