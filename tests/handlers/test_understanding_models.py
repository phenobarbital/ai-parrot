"""Unit tests for UnderstandingRequest, UnderstandingResponse, and media_type_from_filename."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from parrot.handlers.models.understanding import (
    UnderstandingRequest,
    UnderstandingResponse,
    media_type_from_filename,
)


# ---------------------------------------------------------------------------
# media_type_from_filename
# ---------------------------------------------------------------------------


class TestMediaTypeDetection:
    """Tests for the media_type_from_filename helper."""

    @pytest.mark.parametrize("ext", [".png", ".jpg", ".jpeg", ".gif", ".webp"])
    def test_image_extensions(self, ext: str) -> None:
        """Common image extensions resolve to 'image'."""
        assert media_type_from_filename(f"file{ext}") == "image"

    @pytest.mark.parametrize("ext", [".bmp", ".tiff"])
    def test_image_extensions_extra(self, ext: str) -> None:
        """Less-common image extensions also resolve to 'image'."""
        assert media_type_from_filename(f"file{ext}") == "image"

    @pytest.mark.parametrize("ext", [".mp4", ".mov", ".avi", ".webm", ".mkv"])
    def test_video_extensions(self, ext: str) -> None:
        """Common video extensions resolve to 'video'."""
        assert media_type_from_filename(f"file{ext}") == "video"

    @pytest.mark.parametrize("ext", [".flv", ".wmv"])
    def test_video_extensions_extra(self, ext: str) -> None:
        """Less-common video extensions also resolve to 'video'."""
        assert media_type_from_filename(f"file{ext}") == "video"

    def test_unknown_extension_raises(self) -> None:
        """An unrecognised extension raises ValueError containing 'Unsupported'."""
        with pytest.raises(ValueError, match="Unsupported"):
            media_type_from_filename("file.xyz")

    def test_no_extension_raises(self) -> None:
        """A filename with no extension raises ValueError."""
        with pytest.raises(ValueError, match="Unsupported"):
            media_type_from_filename("noextension")

    def test_uppercase_extension_normalised(self) -> None:
        """Extension detection is case-insensitive (.PNG → 'image')."""
        assert media_type_from_filename("photo.PNG") == "image"
        assert media_type_from_filename("clip.MP4") == "video"

    def test_path_with_directories(self) -> None:
        """A full path is handled correctly."""
        assert media_type_from_filename("/tmp/uploads/photo.jpg") == "image"
        assert media_type_from_filename("/tmp/uploads/clip.mp4") == "video"


# ---------------------------------------------------------------------------
# UnderstandingRequest validation
# ---------------------------------------------------------------------------


class TestUnderstandingRequest:
    """Tests for UnderstandingRequest Pydantic model."""

    def test_valid_minimal_request(self) -> None:
        """A request with only 'prompt' uses default values."""
        req = UnderstandingRequest(prompt="Describe this image")
        assert req.prompt == "Describe this image"
        assert req.detect_objects is True
        assert req.as_image is True
        assert req.timeout == 600
        assert req.media_url is None
        assert req.media_type is None
        assert req.model is None
        assert req.temperature is None

    def test_missing_prompt_raises(self) -> None:
        """Omitting the required 'prompt' field raises a validation error."""
        with pytest.raises(Exception):
            UnderstandingRequest()  # type: ignore[call-arg]

    def test_invalid_media_type_rejected(self) -> None:
        """A media_type value other than 'image'/'video' is rejected."""
        with pytest.raises(Exception):
            UnderstandingRequest(prompt="x", media_type="audio")

    def test_valid_media_type_image(self) -> None:
        """'image' is a valid media_type."""
        req = UnderstandingRequest(prompt="x", media_type="image")
        assert req.media_type == "image"

    def test_valid_media_type_video(self) -> None:
        """'video' is a valid media_type."""
        req = UnderstandingRequest(prompt="x", media_type="video")
        assert req.media_type == "video"

    def test_temperature_bounds(self) -> None:
        """Temperature outside 0.0–2.0 is rejected."""
        with pytest.raises(Exception):
            UnderstandingRequest(prompt="x", temperature=-0.1)
        with pytest.raises(Exception):
            UnderstandingRequest(prompt="x", temperature=2.1)

    def test_timeout_bounds(self) -> None:
        """Timeout outside 1–3600 is rejected."""
        with pytest.raises(Exception):
            UnderstandingRequest(prompt="x", timeout=0)
        with pytest.raises(Exception):
            UnderstandingRequest(prompt="x", timeout=3601)

    def test_full_request(self) -> None:
        """All fields can be set simultaneously."""
        req = UnderstandingRequest(
            prompt="What objects are visible?",
            media_url="https://example.com/image.png",
            media_type="image",
            model="gemini-2.0-flash",
            detect_objects=False,
            as_image=False,
            temperature=0.5,
            timeout=120,
        )
        assert req.prompt == "What objects are visible?"
        assert req.media_url == "https://example.com/image.png"
        assert req.media_type == "image"
        assert req.model == "gemini-2.0-flash"
        assert req.detect_objects is False
        assert req.as_image is False
        assert req.temperature == 0.5
        assert req.timeout == 120


# ---------------------------------------------------------------------------
# UnderstandingResponse
# ---------------------------------------------------------------------------


class TestUnderstandingResponse:
    """Tests for UnderstandingResponse Pydantic model and from_ai_message factory."""

    def test_direct_construction(self) -> None:
        """UnderstandingResponse can be built with explicit values."""
        resp = UnderstandingResponse(
            content="A red square on white background",
            structured_output={"detections": []},
            model="gemini-2.0-flash",
            provider="google_genai",
            usage={"prompt_tokens": 10, "completion_tokens": 50},
        )
        assert resp.content == "A red square on white background"
        assert resp.structured_output == {"detections": []}
        assert resp.model == "gemini-2.0-flash"
        assert resp.provider == "google_genai"
        assert resp.usage is not None

    def test_default_provider(self) -> None:
        """Default provider is 'google_genai'."""
        resp = UnderstandingResponse(content="hello")
        assert resp.provider == "google_genai"

    def test_from_ai_message_text_output(self) -> None:
        """from_ai_message() extracts text content from an AIMessage-like object."""
        msg = MagicMock()
        msg.content = "An image of a cat"
        msg.structured_output = None
        msg.model = "gemini-2.0-flash"
        msg.provider = "google_genai"
        msg.usage = None

        resp = UnderstandingResponse.from_ai_message(msg)
        assert resp.content == "An image of a cat"
        assert resp.structured_output is None
        assert resp.model == "gemini-2.0-flash"
        assert resp.provider == "google_genai"
        assert resp.usage is None

    def test_from_ai_message_with_structured_output(self) -> None:
        """from_ai_message() serialises a Pydantic structured_output via model_dump."""
        structured = MagicMock()
        structured.model_dump.return_value = {"detections": [{"label": "cat"}]}

        msg = MagicMock()
        msg.content = "Image with a cat"
        msg.structured_output = structured
        msg.model = "gemini-2.0-flash"
        msg.provider = "google_genai"
        msg.usage = None

        resp = UnderstandingResponse.from_ai_message(msg)
        assert resp.structured_output == {"detections": [{"label": "cat"}]}

    def test_from_ai_message_with_dict_usage(self) -> None:
        """from_ai_message() passes through dict usage directly."""
        usage = {"prompt_tokens": 5, "completion_tokens": 20}

        msg = MagicMock()
        msg.content = "Video summary"
        msg.structured_output = None
        msg.model = "gemini-2.0-flash"
        msg.provider = "google_genai"
        msg.usage = usage

        resp = UnderstandingResponse.from_ai_message(msg)
        assert resp.usage == usage

    def test_from_ai_message_non_string_content_coerced(self) -> None:
        """Non-string content is coerced to str."""
        msg = MagicMock()
        msg.content = 42
        msg.structured_output = None
        msg.model = "gemini-2.0-flash"
        msg.provider = "google_genai"
        msg.usage = None

        resp = UnderstandingResponse.from_ai_message(msg)
        assert isinstance(resp.content, str)
        assert resp.content == "42"
