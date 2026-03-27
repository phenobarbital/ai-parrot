"""Tests for LyriaMusicHandler and MusicGenerationRequest."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError

from parrot.models.google import (
    MusicGenerationRequest,
    MusicGenre,
    MusicMood,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def music_payload() -> dict:
    """Valid full payload for music generation."""
    return {
        "prompt": "Relaxing lo-fi beats for a rainy afternoon",
        "genre": "Lo-Fi Hip Hop",
        "mood": "Chill",
        "bpm": 85,
        "temperature": 1.0,
        "density": 0.4,
        "brightness": 0.3,
        "timeout": 60,
    }


@pytest.fixture
def handler():
    """Create a LyriaMusicHandler with mocked BaseHandler internals."""
    from parrot.handlers.lyria_music import LyriaMusicHandler

    h = LyriaMusicHandler.__new__(LyriaMusicHandler)
    h.logger = MagicMock()
    h.request = MagicMock()
    h.error = MagicMock(side_effect=lambda msg, status=400: _make_response(
        body=msg, status=status, content_type="application/json",
    ))
    h.json_response = MagicMock(side_effect=lambda data, **kw: _make_response(
        body=data, status=200, content_type="application/json",
    ))
    return h


def _make_response(body, status=200, content_type="application/json"):
    """Build a lightweight fake web.Response-like object."""
    resp = MagicMock()
    resp.status = status
    resp.body = body
    resp.content_type = content_type
    return resp


# ---------------------------------------------------------------------------
# 1. Model validation tests
# ---------------------------------------------------------------------------

class TestMusicGenerationRequestModel:
    """Pydantic model tests for MusicGenerationRequest."""

    def test_model_valid_minimal(self):
        """MusicGenerationRequest with only a prompt succeeds."""
        req = MusicGenerationRequest(prompt="test music")
        assert req.prompt == "test music"
        assert req.bpm == 90  # default
        assert req.temperature == 1.0
        assert req.density == 0.5
        assert req.brightness == 0.5
        assert req.timeout == 300
        assert req.genre is None
        assert req.mood is None

    def test_model_missing_prompt(self):
        """Missing prompt raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            MusicGenerationRequest()  # type: ignore[call-arg]
        assert "prompt" in str(exc_info.value)

    def test_model_bpm_out_of_range(self):
        """BPM outside 60–200 raises ValidationError."""
        with pytest.raises(ValidationError):
            MusicGenerationRequest(prompt="x", bpm=250)
        with pytest.raises(ValidationError):
            MusicGenerationRequest(prompt="x", bpm=10)

    def test_model_temperature_out_of_range(self):
        """Temperature outside 0.0–3.0 raises ValidationError."""
        with pytest.raises(ValidationError):
            MusicGenerationRequest(prompt="x", temperature=5.0)
        with pytest.raises(ValidationError):
            MusicGenerationRequest(prompt="x", temperature=-1.0)

    def test_model_density_out_of_range(self):
        """Density outside 0.0–1.0 raises ValidationError."""
        with pytest.raises(ValidationError):
            MusicGenerationRequest(prompt="x", density=2.0)

    def test_model_brightness_out_of_range(self):
        """Brightness outside 0.0–1.0 raises ValidationError."""
        with pytest.raises(ValidationError):
            MusicGenerationRequest(prompt="x", brightness=1.5)

    def test_model_json_schema(self):
        """JSON schema includes all 8 documented properties."""
        schema = MusicGenerationRequest.model_json_schema()
        props = schema["properties"]
        expected = {
            "prompt", "genre", "mood", "bpm",
            "temperature", "density", "brightness", "timeout",
        }
        assert expected == set(props.keys())

    def test_model_full_payload(self, music_payload):
        """Full payload constructs successfully with all fields."""
        req = MusicGenerationRequest(**music_payload)
        assert req.prompt == music_payload["prompt"]
        assert req.genre == MusicGenre.LO_FI_HIP_HOP
        assert req.mood == MusicMood.CHILL
        assert req.bpm == 85


# ---------------------------------------------------------------------------
# 2. Handler POST tests
# ---------------------------------------------------------------------------

class TestLyriaMusicHandlerPost:
    """Tests for LyriaMusicHandler.post()."""

    @pytest.mark.asyncio
    async def test_post_valid_stream(self, handler, music_payload):
        """POST with valid payload in stream mode returns chunked audio/wav."""
        handler.request.json = AsyncMock(return_value={**music_payload, "stream": True})

        # Mock StreamResponse
        mock_stream = AsyncMock()
        mock_stream.prepare = AsyncMock()
        mock_stream.write = AsyncMock()
        mock_stream.write_eof = AsyncMock()
        mock_stream.status = 200
        mock_stream.headers = {"Content-Type": "audio/wav"}

        audio_chunk = b"\x00\x01\x02\x03"

        async def mock_generate_music(**kwargs):
            yield audio_chunk

        with (
            patch("parrot.handlers.lyria_music.GoogleGenAIClient") as MockClient,
            patch("parrot.handlers.lyria_music.web.StreamResponse", return_value=mock_stream),
        ):
            mock_client_instance = AsyncMock()
            mock_client_instance.generate_music = mock_generate_music
            mock_client_instance.close = AsyncMock()
            MockClient.return_value = mock_client_instance

            result = await handler.post()

        assert result is mock_stream
        mock_stream.prepare.assert_called_once_with(handler.request)
        mock_stream.write.assert_called_once_with(audio_chunk)
        mock_stream.write_eof.assert_called_once()
        mock_client_instance.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_post_valid_download(self, handler, music_payload):
        """POST with stream=false returns full buffered audio with Content-Length."""
        handler.request.json = AsyncMock(
            return_value={**music_payload, "stream": False}
        )

        audio_chunks = [b"\x00\x01", b"\x02\x03"]

        async def mock_generate_music(**kwargs):
            for chunk in audio_chunks:
                yield chunk

        with patch("parrot.handlers.lyria_music.GoogleGenAIClient") as MockClient:
            mock_client_instance = AsyncMock()
            mock_client_instance.generate_music = mock_generate_music
            mock_client_instance.close = AsyncMock()
            MockClient.return_value = mock_client_instance

            with patch("parrot.handlers.lyria_music.web.Response") as MockResponse:
                mock_resp = MagicMock()
                mock_resp.status = 200
                MockResponse.return_value = mock_resp

                result = await handler.post()

        assert result is mock_resp
        # Verify Response was called with combined audio bytes
        MockResponse.assert_called_once()
        call_kwargs = MockResponse.call_args
        assert call_kwargs.kwargs["body"] == b"\x00\x01\x02\x03"
        assert call_kwargs.kwargs["content_type"] == "audio/wav"
        assert "Content-Length" in call_kwargs.kwargs["headers"]
        assert call_kwargs.kwargs["headers"]["Content-Length"] == "4"
        mock_client_instance.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_post_invalid_payload(self, handler):
        """POST with missing prompt returns 400."""
        handler.request.json = AsyncMock(return_value={"bpm": 90})

        result = await handler.post()

        handler.error.assert_called_once()
        call_args = handler.error.call_args
        assert call_args.kwargs.get("status", call_args[1].get("status", None)) == 400
        assert result.status == 400

    @pytest.mark.asyncio
    async def test_post_invalid_json(self, handler):
        """POST with unparseable body returns 400."""
        handler.request.json = AsyncMock(side_effect=Exception("bad json"))

        result = await handler.post()

        handler.error.assert_called_once()
        assert result.status == 400

    @pytest.mark.asyncio
    async def test_post_invalid_bpm(self, handler, music_payload):
        """POST with out-of-range BPM returns 400."""
        music_payload["bpm"] = 999
        handler.request.json = AsyncMock(return_value=music_payload)

        result = await handler.post()

        handler.error.assert_called_once()
        assert result.status == 400

    @pytest.mark.asyncio
    async def test_post_generation_error(self, handler, music_payload):
        """POST returns 500 when generate_music raises."""
        handler.request.json = AsyncMock(
            return_value={**music_payload, "stream": True}
        )

        # Adjust error mock to handle 500 status
        handler.error = MagicMock(side_effect=lambda msg, status=400: _make_response(
            body=msg, status=status,
        ))

        mock_stream = AsyncMock()
        mock_stream.prepare = AsyncMock()
        mock_stream.write = AsyncMock()
        mock_stream.write_eof = AsyncMock()

        async def mock_generate_music_fail(**kwargs):
            raise RuntimeError("Lyria API down")
            # Make it an async generator that raises
            yield  # pragma: no cover

        with (
            patch("parrot.handlers.lyria_music.GoogleGenAIClient") as MockClient,
            patch("parrot.handlers.lyria_music.web.StreamResponse", return_value=mock_stream),
        ):
            mock_client_instance = AsyncMock()
            mock_client_instance.generate_music = mock_generate_music_fail
            mock_client_instance.close = AsyncMock()
            MockClient.return_value = mock_client_instance

            result = await handler.post()

        assert result.status == 500
        mock_client_instance.close.assert_called_once()


# ---------------------------------------------------------------------------
# 3. Handler GET catalog test
# ---------------------------------------------------------------------------

class TestLyriaMusicHandlerGet:
    """Tests for LyriaMusicHandler.get()."""

    @pytest.mark.asyncio
    async def test_get_catalog(self, handler):
        """GET returns JSON with genres, moods, parameters, schema."""
        await handler.get()

        handler.json_response.assert_called_once()
        payload = handler.json_response.call_args[0][0]
        assert "genres" in payload
        assert "moods" in payload
        assert "parameters" in payload
        assert "schema" in payload

    @pytest.mark.asyncio
    async def test_get_catalog_genres_complete(self, handler):
        """GET genres list contains all MusicGenre enum values."""
        await handler.get()
        payload = handler.json_response.call_args[0][0]
        expected_genres = {g.value for g in MusicGenre}
        assert set(payload["genres"]) == expected_genres

    @pytest.mark.asyncio
    async def test_get_catalog_moods_complete(self, handler):
        """GET moods list contains all MusicMood enum values."""
        await handler.get()
        payload = handler.json_response.call_args[0][0]
        expected_moods = {m.value for m in MusicMood}
        assert set(payload["moods"]) == expected_moods

    @pytest.mark.asyncio
    async def test_get_catalog_parameters(self, handler):
        """GET parameters include bpm, temperature, density, brightness, timeout."""
        await handler.get()
        payload = handler.json_response.call_args[0][0]
        expected_params = {"bpm", "temperature", "density", "brightness", "timeout"}
        assert set(payload["parameters"].keys()) == expected_params

    @pytest.mark.asyncio
    async def test_get_catalog_parameter_ranges(self, handler):
        """GET parameter ranges match Pydantic field constraints."""
        await handler.get()
        payload = handler.json_response.call_args[0][0]
        params = payload["parameters"]
        # BPM: ge=60, le=200, default=90
        assert params["bpm"]["min"] == 60
        assert params["bpm"]["max"] == 200
        assert params["bpm"]["default"] == 90


# ---------------------------------------------------------------------------
# 4. Schema helper test
# ---------------------------------------------------------------------------

class TestSchemaHelper:
    """Test GoogleGenerationHelper.list_schemas includes music schema."""

    def test_schema_helper_includes_music(self):
        """list_schemas() dict has 'music_generation_request' key."""
        from parrot.handlers.google_generation import GoogleGenerationHelper

        schemas = GoogleGenerationHelper.list_schemas()
        assert "music_generation_request" in schemas

    def test_schema_helper_music_schema_has_properties(self):
        """Music schema in list_schemas() contains expected properties."""
        from parrot.handlers.google_generation import GoogleGenerationHelper

        schemas = GoogleGenerationHelper.list_schemas()
        music_schema = schemas["music_generation_request"]
        props = music_schema["properties"]
        expected = {"prompt", "genre", "mood", "bpm", "temperature", "density", "brightness", "timeout"}
        assert expected == set(props.keys())
