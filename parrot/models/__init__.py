"""
Models for the Parrot application.
Includes definitions for various data structures used in the application,
such as responses, outputs, and configurations.
"""

from .basic import OutputFormat, ToolCall, CompletionUsage, ToolConfig
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
from .generation import (
    VideoGenInput,
    VideoResolution,
)
from .google import (
    GoogleModel,
    TTSVoice,
    MusicGenre,
    MusicMood,
    MusicGenerationRequest,
    AspectRatio,
    ImageResolution,
    VideoReelRequest,
    VideoReelScene,
)
from .voice import VoiceConfig, AudioFormat

__all__ = (
    "OutputFormat",
    "ToolCall",
    "CompletionUsage",
    "ToolConfig",
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
    "VoiceConfig",
    "AudioFormat",
    "MusicGenre",
    "MusicMood",
    "MusicGenerationRequest",
    "AspectRatio",
    "ImageResolution",
    "VideoReelRequest",
    "VideoReelScene",
    "VideoGenInput",
    "VideoResolution",
)
