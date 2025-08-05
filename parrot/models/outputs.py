from datetime import datetime
from typing import Dict, List, Optional, Any, Callable, Literal
from dataclasses import dataclass
from pydantic import BaseModel, Field
from .basic import OutputFormat


@dataclass
class StructuredOutputConfig:
    """Configuration for structured output parsing."""
    output_type: type
    format: OutputFormat = OutputFormat.JSON
    custom_parser: Optional[Callable[[str], Any]] = None


class BoundingBox(BaseModel):
    """Represents a detected object with its location and details."""
    object_id: str = Field(..., description="Unique identifier for this detection")
    brand: str = Field(..., description="Product brand (Epson, HP, Canon, etc.)")
    model: Optional[str] = Field(None, description="Product model if identifiable")
    product_type: str = Field(
        ..., description="Type of product (printer, scanner, ink cartridge, etc.)"
    )
    description: str = Field(..., description="Brief description of the product")
    confidence: float = Field(..., description="Confidence level (0.0 to 1.0)")
    # Simple bounding box as [x1, y1, x2, y2] normalized coordinates (0.0 to 1.0)
    bbox: List[float] = Field(
        ..., description="Bounding box coordinates [x1, y1, x2, y2] as normalized values (0.0-1.0)"
    )


class ObjectDetectionResult(BaseModel):
    """A list of all prominent items detected in the image."""
    analysis: str = Field(
        ...,
        description="A detailed text analysis of the image that answers the user's prompt."
    )
    total_count: int = Field(..., description="Total number of products detected")
    detections: List[BoundingBox] = Field(
        default_factory=list,
        description="A list of bounding boxes for all prominent detected objects."
    )

class ImageGenerationPrompt(BaseModel):
    """Input schema for generating an image."""
    prompt: str = Field(..., description="The main text prompt describing the desired image.")
    styles: Optional[List[str]] = Field(default_factory=list, description="Optional list of styles to apply (e.g., 'photorealistic', 'cinematic', 'anime').")
    model: str = Field(description="The image generation model to use.")
    negative_prompt: Optional[str] = Field(None, description="A description of what to avoid in the image.")
    aspect_ratio: str = Field(default="1:1", description="The desired aspect ratio (e.g., '1:1', '16:9', '9:16').")


class SpeakerConfig(BaseModel):
    """Configuration for a single speaker in speech generation."""
    name: str = Field(..., description="The name of the speaker in the script (e.g., 'Joe', 'Narrator').")
    voice: str = Field(..., description="The pre-built voice name to use (e.g., 'Kore', 'Puck', 'Chitose').")
    # Gender is often inferred from the voice, but can be included for clarity
    gender: Optional[str] = Field(None, description="The gender associated with the voice (e.g., 'Male', 'Female').")


class SpeechGenerationPrompt(BaseModel):
    """Input schema for generating speech from text."""
    prompt: str = Field(
        ...,
        description="The text to be converted to speech. For multiple speakers, use their names (e.g., 'Joe: Hello. Jane: Hi there.')."
    )
    speakers: List[SpeakerConfig] = Field(
        ...,
        description="A list of speaker configurations. Use one for a single voice, multiple for a conversation."
    )
    model: Optional[str] = Field(default=None, description="The text-to-speech model to use.")
    language: Optional[str] = Field("en-US", description="Language code for the conversation.")


class VideoGenerationPrompt(BaseModel):
    """Input schema for generating video content."""
    prompt: str = Field(..., description="The text prompt describing the desired video content.")
    number_of_videos: int = Field(
        default=1, description="The number of videos to generated per request."
    )
    model: str = Field(..., description="The video generation model to use.")
    aspect_ratio: str = Field(
        default="16:9", description="The desired aspect ratio (e.g., '16:9', '9:16')."
    )
    duration: Optional[int] = Field(None, description="Optional duration in seconds for the video.")
    negative_prompt: Optional[str] = Field(
        default='',
        description="A description of what to avoid in the video."
    )

class SentimentAnalysis(BaseModel):
    """Structured sentiment analysis response."""
    sentiment: Literal["positive", "negative", "neutral", "mixed"] = Field(
        description="Overall sentiment classification"
    )
    confidence_level: float = Field(
        ge=0.0, le=1.0,
        description="Confidence level as decimal between 0 and 1"
    )
    emotional_indicators: List[str] = Field(
        description="List of words/phrases that indicate emotional content"
    )
    reason: str = Field(
        description="Explanation of the sentiment analysis"
    )


class ProductReview(BaseModel):
    """Structured product review response."""
    product_id: str = Field(..., description="Unique identifier for the product being reviewed")
    product_name: str = Field(..., description="Name of the product being reviewed")
    review_text: str = Field(..., description="The text of the product review")
    rating: float = Field(..., description="Rating given to the product")
    sentiment: Literal["positive", "negative", "neutral"] = Field(
        ..., description="Sentiment of the review"
    )
    key_features: list[str] = Field(..., description="Key features highlighted in the review")
