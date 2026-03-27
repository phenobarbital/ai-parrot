"""Pydantic request/response models for the image & video understanding handler."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator

# ---------------------------------------------------------------------------
# Media-type extension sets
# ---------------------------------------------------------------------------

IMAGE_EXTENSIONS: frozenset[str] = frozenset(
    {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tiff"}
)
VIDEO_EXTENSIONS: frozenset[str] = frozenset(
    {".mp4", ".mov", ".avi", ".webm", ".mkv", ".flv", ".wmv"}
)


def media_type_from_filename(filename: str) -> str:
    """Return 'image' or 'video' based on the file extension of *filename*.

    Args:
        filename: A file name or path whose extension is used for detection.

    Returns:
        ``"image"`` or ``"video"``.

    Raises:
        ValueError: If the extension is not recognised as an image or video type.
    """
    ext = Path(filename).suffix.lower()
    if ext in IMAGE_EXTENSIONS:
        return "image"
    if ext in VIDEO_EXTENSIONS:
        return "video"
    raise ValueError(
        f"Unsupported media extension: {ext!r}. "
        f"Supported image extensions: {sorted(IMAGE_EXTENSIONS)}. "
        f"Supported video extensions: {sorted(VIDEO_EXTENSIONS)}."
    )


# ---------------------------------------------------------------------------
# Request model
# ---------------------------------------------------------------------------


class UnderstandingRequest(BaseModel):
    """Request body for the image/video understanding endpoint.

    Supports both multipart file uploads (where *prompt* is sent as a form
    field) and JSON mode (where *media_url* points to a remote resource).
    """

    prompt: str = Field(
        ...,
        description="Analysis prompt / question to send to the model.",
    )
    media_url: Optional[str] = Field(
        default=None,
        description=(
            "URL of a remote image or video to analyse. "
            "Used in JSON mode when no file is uploaded."
        ),
    )
    media_type: Optional[str] = Field(
        default=None,
        description=(
            "Explicit media-type hint: 'image' or 'video'. "
            "Auto-detected from file extension / content-type when omitted."
        ),
    )
    model: Optional[str] = Field(
        default=None,
        description="GoogleModel override (e.g. 'gemini-2.0-flash').",
    )
    detect_objects: bool = Field(
        default=True,
        description="Enable object detection bounding boxes for image analysis.",
    )
    as_image: bool = Field(
        default=True,
        description="Extract video frames as images for analysis (video path only).",
    )
    temperature: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=2.0,
        description="Sampling temperature passed to the model (0.0 – 2.0).",
    )
    timeout: Optional[int] = Field(
        default=600,
        ge=1,
        le=3600,
        description="Request timeout in seconds (1 – 3600).",
    )

    @field_validator("media_type")
    @classmethod
    def _validate_media_type(cls, v: Optional[str]) -> Optional[str]:
        """Reject media_type values other than 'image' or 'video'.

        Args:
            v: The candidate media_type string.

        Returns:
            The validated value, or ``None`` if not provided.

        Raises:
            ValueError: If *v* is not ``'image'`` or ``'video'``.
        """
        if v is not None and v not in ("image", "video"):
            raise ValueError(
                f"media_type must be 'image' or 'video', got {v!r}."
            )
        return v


# ---------------------------------------------------------------------------
# Response model
# ---------------------------------------------------------------------------


class UnderstandingResponse(BaseModel):
    """Serialised subset of AIMessage returned to callers.

    Only the fields relevant to the understanding endpoint are exposed here;
    this keeps the response payload compact and stable.
    """

    content: str = Field(
        ...,
        description="Text response from the model.",
    )
    structured_output: Optional[Any] = Field(
        default=None,
        description=(
            "Structured detection results for image analysis, "
            "or ``None`` for video analysis."
        ),
    )
    model: Optional[str] = Field(
        default=None,
        description="Name of the model used for generation.",
    )
    provider: str = Field(
        default="google_genai",
        description="LLM provider identifier.",
    )
    usage: Optional[dict] = Field(
        default=None,
        description="Token usage statistics from the provider.",
    )

    @classmethod
    def from_ai_message(cls, msg: Any) -> "UnderstandingResponse":
        """Build an UnderstandingResponse from an AIMessage instance.

        Args:
            msg: An ``AIMessage`` object returned by ``GoogleGenAIClient``.

        Returns:
            A populated ``UnderstandingResponse``.
        """
        # AIMessage.content is a property alias for .output; use it for the
        # human-readable text.  Fall back to str(output) for safety.
        content = msg.content
        if not isinstance(content, str):
            content = str(content)

        # Serialise structured_output if it is a Pydantic model or dataclass.
        structured: Any = None
        if msg.structured_output is not None:
            so = msg.structured_output
            if hasattr(so, "model_dump"):
                structured = so.model_dump()
            elif hasattr(so, "__dict__"):
                structured = so.__dict__
            else:
                structured = so

        # Serialise usage information.
        usage: Optional[dict] = None
        if msg.usage is not None:
            u = msg.usage
            if hasattr(u, "model_dump"):
                usage = u.model_dump()
            elif hasattr(u, "__dict__"):
                usage = {
                    k: v
                    for k, v in u.__dict__.items()
                    if not k.startswith("_")
                }
            elif isinstance(u, dict):
                usage = u

        return cls(
            content=content,
            structured_output=structured,
            model=getattr(msg, "model", None),
            provider=getattr(msg, "provider", "google_genai"),
            usage=usage,
        )
