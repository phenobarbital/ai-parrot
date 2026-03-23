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
from .datasets import (
    DatasetAction,
    DatasetPatchRequest,
    DatasetQueryRequest,
    DatasetListResponse,
    DatasetUploadResponse,
    DatasetDeleteResponse,
    DatasetErrorResponse,
)
from .vllm import (
    VLLMConfig,
    VLLMSamplingParams,
    VLLMLoRARequest,
    VLLMGuidedParams,
    VLLMBatchRequest,
    VLLMBatchResponse,
    VLLMServerInfo,
    pydantic_to_guided_json,
)

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
    # Dataset models
    "DatasetAction",
    "DatasetPatchRequest",
    "DatasetQueryRequest",
    "DatasetListResponse",
    "DatasetUploadResponse",
    "DatasetDeleteResponse",
    "DatasetErrorResponse",
    # vLLM models
    "VLLMConfig",
    "VLLMSamplingParams",
    "VLLMLoRARequest",
    "VLLMGuidedParams",
    "VLLMBatchRequest",
    "VLLMBatchResponse",
    "VLLMServerInfo",
    "pydantic_to_guided_json",
)
