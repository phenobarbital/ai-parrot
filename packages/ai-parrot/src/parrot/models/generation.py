from enum import Enum
from typing import Any, List, Optional
from pydantic import BaseModel, Field


class VideoResolution(str, Enum):
    """Supported video resolutions for VEO models.

    Notes:
        - ``1080p`` and ``4k`` require ``duration=8`` and are unsupported by VEO 2.0.
        - Video extension only supports ``720p``.
    """
    RES_720P = "720p"
    RES_1080P = "1080p"
    RES_4K = "4k"


class VideoGenInput(BaseModel):
    """Structured input for VEO video generation with all supported parameters.

    Accepted by ``video_generation`` as an alternative to a plain ``str`` prompt.
    When individual kwargs are also passed to ``video_generation``, they override
    the values from this model.

    See: https://ai.google.dev/gemini-api/docs/video
    """

    prompt: str = Field(..., description="Text description of the desired video.")

    negative_prompt: Optional[str] = Field(
        None,
        description="Text describing what NOT to include in the video.",
    )
    duration: int = Field(
        8,
        description=(
            "Duration in seconds. VEO 3.1 accepts 4, 6, or 8; "
            "VEO 2.0 accepts 5, 6, or 8. Must be 8 for 1080p/4k resolution, "
            "extension, or reference images."
        ),
    )
    aspect_ratio: str = Field(
        "16:9",
        description="Video aspect ratio: '16:9' (default) or '9:16'.",
    )
    resolution: Optional[str] = Field(
        None,
        description=(
            "Video resolution: '720p' (default), '1080p', or '4k'. "
            "VEO 3.1 only — unsupported by VEO 2.0."
        ),
    )
    person_generation: str = Field(
        "allow_adult",
        description=(
            "Controls person generation. "
            "VEO 3.1 text-to-video: 'allow_all' only. "
            "VEO 3.1 image-to-video / reference images: 'allow_adult' only. "
            "VEO 2.0: 'allow_all', 'allow_adult', or 'dont_allow'."
        ),
    )
    include_audio: bool = Field(
        True,
        description=(
            "Whether to keep generated audio in the output. "
            "VEO 3.1 generates native audio; set False to strip it from the file."
        ),
    )
    number_of_videos: int = Field(1, description="Number of videos to generate.")
    seed: Optional[int] = Field(
        None,
        description="Optional seed for reproducibility (VEO 3.x only; does not guarantee determinism).",
    )

    # ── Image inputs ──────────────────────────────────────────────────────────
    image_path: Optional[str] = Field(
        None,
        description="Path (or URL) of a starting image for image-to-video generation.",
    )
    last_frame_path: Optional[str] = Field(
        None,
        description=(
            "Path of the ending frame for interpolation. "
            "Must be combined with ``image_path``."
        ),
    )
    reference_image_paths: Optional[List[str]] = Field(
        None,
        description=(
            "Up to 3 reference image paths used as style/content guides. "
            "VEO 3.1 only. Implies ``duration=8``."
        ),
        max_length=3,
    )
    reference_type: str = Field(
        "asset",
        description="Reference image type: 'asset' (content) or 'style'.",
    )

    # ── Video extension ───────────────────────────────────────────────────────
    extend_video: Optional[Any] = Field(
        None,
        description=(
            "Video object from a previous Veo generation to extend (VEO 3.1 only). "
            "Must be a ``types.Video`` from ``operation.response.generated_videos[n].video``."
        ),
    )

    # ── Convenience generation ─────────────────────────────────────────────────
    generate_image_first: bool = Field(
        False,
        description="If True, generate a reference image from ``image_prompt`` or ``prompt`` before video generation.",
    )
    image_prompt: Optional[str] = Field(
        None,
        description="Custom prompt for reference image generation when ``generate_image_first=True``.",
    )

    class Config:
        json_schema_extra = {
            "example": {
                "prompt": "A cinematic shot of a majestic lion in the savannah.",
                "negative_prompt": "cartoon, drawing, low quality",
                "duration": 8,
                "aspect_ratio": "16:9",
                "resolution": "1080p",
                "person_generation": "allow_all",
                "include_audio": True,
                "number_of_videos": 1,
            }
        }


class VideoGenerationPrompt(BaseModel):
    """Input schema for generating video content with VEO models (handler-facing)."""

    prompt: str = Field(
        ...,
        description="The text prompt describing the desired video content."
    )

    model: str = Field(
        ...,
        description="The video generation model to use (e.g., 'veo-3.1-generate-preview')."
    )

    aspect_ratio: str = Field(
        default="16:9",
        description="The desired aspect ratio (e.g., '16:9', '9:16')."
    )

    resolution: Optional[str] = Field(
        default="720p",
        description="Video resolution ('720p', '1080p', or '4k'). VEO 3.1 only for 1080p/4k."
    )

    negative_prompt: Optional[str] = Field(
        default='',
        description="A description of what to avoid in the video."
    )

    number_of_videos: int = Field(
        default=1,
        description="The number of videos to generate per request."
    )

    duration: Optional[int] = Field(
        None,
        description="Duration in seconds. VEO 3.1: 4/6/8; VEO 2.0: 5/6/8."
    )

    seed: Optional[int] = Field(
        None,
        description="Optional seed for reproducible generation (VEO 3.x only)."
    )

    include_audio: bool = Field(
        True,
        description="Whether to include generated audio (VEO 3.1 generates native audio)."
    )

    class Config:
        json_schema_extra = {
            "example": {
                "prompt": "A cinematic shot of a majestic lion in the savannah",
                "model": "veo-3.1-generate-preview",
                "aspect_ratio": "16:9",
                "resolution": "1080p",
                "negative_prompt": "cartoon, drawing, low quality",
                "number_of_videos": 1,
                "duration": 8,
                "include_audio": True,
            }
        }


def validate_aspect_ratio(aspect_ratio: str) -> bool:
    """Validate that aspect ratio is in a supported format."""
    valid_ratios = ["16:9", "9:16"]
    return aspect_ratio in valid_ratios


def validate_resolution(resolution: str) -> bool:
    """Validate that resolution is supported."""
    valid_resolutions = ["720p", "1080p", "4k"]
    return resolution in valid_resolutions

