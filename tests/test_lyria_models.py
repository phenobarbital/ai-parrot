"""Tests for Lyria batch music generation models."""
import pytest
from parrot.models.google import LyriaModel, MusicBatchRequest, MusicBatchResponse


class TestLyriaModel:
    """Tests for LyriaModel enum."""

    def test_lyria_002_value(self):
        """LyriaModel.LYRIA_002 has correct value."""
        assert LyriaModel.LYRIA_002.value == "lyria-002"

    def test_lyria_realtime_value(self):
        """LyriaModel.LYRIA_REALTIME has correct value."""
        assert LyriaModel.LYRIA_REALTIME.value == "lyria-realtime-exp"

    def test_is_string_enum(self):
        """LyriaModel is a string enum."""
        assert isinstance(LyriaModel.LYRIA_002, str)
        assert LyriaModel.LYRIA_002 == "lyria-002"


class TestMusicBatchRequest:
    """Tests for MusicBatchRequest model."""

    def test_valid_request(self):
        """MusicBatchRequest validates with required fields."""
        req = MusicBatchRequest(prompt="Calm acoustic guitar")
        assert req.prompt == "Calm acoustic guitar"
        assert req.sample_count == 1
        assert req.seed is None

    def test_request_with_all_fields(self):
        """MusicBatchRequest accepts all optional fields."""
        req = MusicBatchRequest(
            prompt="Upbeat electronic",
            negative_prompt="drums",
            seed=42,
            sample_count=1
        )
        assert req.negative_prompt == "drums"
        assert req.seed == 42

    def test_sample_count_min(self):
        """sample_count must be >= 1."""
        with pytest.raises(ValueError):
            MusicBatchRequest(prompt="test", sample_count=0)

    def test_sample_count_max(self):
        """sample_count must be <= 4."""
        with pytest.raises(ValueError):
            MusicBatchRequest(prompt="test", sample_count=5)

    def test_sample_count_valid_range(self):
        """sample_count accepts values 1-4."""
        for count in [1, 2, 3, 4]:
            req = MusicBatchRequest(prompt="test", sample_count=count)
            assert req.sample_count == count

    def test_empty_prompt_raises(self):
        """Empty prompt raises validation error."""
        with pytest.raises(ValueError):
            MusicBatchRequest(prompt="")

    def test_negative_prompt_optional(self):
        """negative_prompt is optional."""
        req = MusicBatchRequest(prompt="test")
        assert req.negative_prompt is None

    def test_seed_optional(self):
        """seed is optional."""
        req = MusicBatchRequest(prompt="test")
        assert req.seed is None

    def test_seed_accepts_integers(self):
        """seed accepts integer values."""
        req = MusicBatchRequest(prompt="test", seed=12345)
        assert req.seed == 12345


class TestMusicBatchResponse:
    """Tests for MusicBatchResponse model."""

    def test_valid_response(self):
        """MusicBatchResponse parses correctly."""
        resp = MusicBatchResponse(
            audio_content="SGVsbG8=",
            mime_type="audio/wav"
        )
        assert resp.audio_content == "SGVsbG8="
        assert resp.mime_type == "audio/wav"

    def test_default_mime_type(self):
        """mime_type defaults to audio/wav."""
        resp = MusicBatchResponse(audio_content="SGVsbG8=")
        assert resp.mime_type == "audio/wav"

    def test_audio_content_required(self):
        """audio_content is required."""
        with pytest.raises(ValueError):
            MusicBatchResponse()

    def test_custom_mime_type(self):
        """Custom mime_type is accepted."""
        resp = MusicBatchResponse(
            audio_content="SGVsbG8=",
            mime_type="audio/mpeg"
        )
        assert resp.mime_type == "audio/mpeg"
