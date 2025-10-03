"""
Models for the Parrot application.
Includes definitions for various data structures used in the application,
such as responses, outputs, and configurations.
"""

from .basic import OutputFormat, ToolCall, CompletionUsage
from .responses import (
    AIMessage,
    SourceDocument,
    AIMessageFactory,
    MessageResponse,
    StreamChunk,
)
from .outputs import (
    StructuredOutputConfig,
    BoundingBox,
    ObjectDetectionResult,
    ImageGenerationPrompt,
    SpeakerConfig,
    SpeechGenerationPrompt,
    VideoGenerationPrompt
)
from .google import GoogleModel, TTSVoice
from .generation import VideoGenerationPrompt

__all__ = (
    "OutputFormat",
    "ToolCall",
    "CompletionUsage",
    "AIMessage",
    "AIMessageFactory",
    "SourceDocument",
    "MessageResponse",
    "StreamChunk",
    "StructuredOutputConfig",
    "BoundingBox",
    "ObjectDetectionResult",
    "ImageGenerationPrompt",
    "SpeakerConfig",
    "SpeechGenerationPrompt",
    "VideoGenerationPrompt",
    "GoogleModel",
    "TTSVoice",
    "VideoGenerationPrompt",
)
