from typing import Optional
from pydantic import BaseModel, Field


class VideoGenerationPrompt(BaseModel):
    """Input schema for generating video content with VEO models."""

    prompt: str = Field(
        ...,
        description="The text prompt describing the desired video content."
    )

    model: str = Field(
        ...,
        description="The video generation model to use (e.g., 'veo-3.0-generate-001')."
    )

    aspect_ratio: str = Field(
        default="16:9",
        description="The desired aspect ratio (e.g., '16:9', '9:16', '1:1')."
    )

    resolution: Optional[str] = Field(
        default="720p",
        description="Video resolution ('720p' or '1080p'). Default is '720p'."
    )

    negative_prompt: Optional[str] = Field(
        default='',
        description="A description of what to avoid in the video (e.g., 'cartoon, low quality')."
    )

    number_of_videos: int = Field(
        default=1,
        description="The number of videos to generate per request (typically 1)."
    )

    duration: Optional[int] = Field(
        None,
        description="Optional duration in seconds for the video (if supported by model)."
    )

    # Additional metadata fields (optional)
    seed: Optional[int] = Field(
        None,
        description="Optional seed for reproducible generation (if supported)."
    )

    class Config:
        json_schema_extra = {
            "example": {
                "prompt": "A cinematic shot of a majestic lion in the savannah",
                "model": "veo-3.0-generate-001",
                "aspect_ratio": "16:9",
                "resolution": "1080p",
                "negative_prompt": "cartoon, drawing, low quality",
                "number_of_videos": 1
            }
        }

def validate_aspect_ratio(aspect_ratio: str) -> bool:
    """Validate that aspect ratio is in correct format."""
    valid_ratios = ["16:9", "9:16", "1:1", "4:3", "3:4", "21:9"]
    return aspect_ratio in valid_ratios


def validate_resolution(resolution: str) -> bool:
    """Validate that resolution is supported."""
    valid_resolutions = ["720p", "1080p"]
    return resolution in valid_resolutions


# # Example usage:
# if __name__ == "__main__":
#     # Create a video generation prompt
#     prompt = VideoGenerationPrompt(
#         prompt="A time-lapse of a sunset over the ocean",
#         model="veo-3.0-generate-001",
#         aspect_ratio="16:9",
#         resolution="1080p",
#         negative_prompt="people, buildings, text",
#         number_of_videos=1
#     )

#     print(prompt.model_dump_json(indent=2))
