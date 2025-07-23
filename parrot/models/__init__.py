"""
Models for the Parrot application.
Includes definitions for various data structures used in the application,
such as responses, outputs, and configurations.
"""

from .basic import OutputFormat, ToolCall, CompletionUsage
from .responses import (
    AIMessage,
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


__all__ = (
    "OutputFormat",
    "ToolCall",
    "CompletionUsage",
    "AIMessage",
    "AIMessageFactory",
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
)
