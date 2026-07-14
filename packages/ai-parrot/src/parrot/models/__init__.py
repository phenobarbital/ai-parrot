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
from .infographic import (
    BlockType,
    ChartType,
    TrendDirection,
    CalloutLevel,
    InfographicBlock,
    InfographicResponse,
    TitleBlock,
    HeroCardBlock,
    SummaryBlock,
    ChartBlock,
    ChartDataSeries,
    BulletListBlock,
    TableBlock,
    ImageBlock,
    QuoteBlock,
    CalloutBlock,
    DividerBlock,
    TimelineBlock,
    TimelineEvent,
    ProgressBlock,
    ProgressItem,
    ThemeConfig,
    ThemeRegistry,
    theme_registry,
)
from .infographic_templates import (
    BlockSpec,
    InfographicTemplate,
    InfographicTemplateRegistry,
    infographic_registry,
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
from .nvidia import NvidiaModel
from .zai import ZaiModel
from .crew_definition import (
    ExecutionMode,
    AgentDefinition,
    ToolNodeDefinition,
    FlowRelation,
    CrewDefinition,
)
from .conference import (
    PeerVote,
    ConferenceRound,
    ConferenceResult,
)
from .stores import StoreType, StoreConfig, SearchResult

__all__ = (
    "OutputFormat",
    "ToolCall",
    "CompletionUsage",
    "ZaiModel",
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
    # Infographic models
    "BlockType",
    "ChartType",
    "TrendDirection",
    "CalloutLevel",
    "InfographicBlock",
    "InfographicResponse",
    "TitleBlock",
    "HeroCardBlock",
    "SummaryBlock",
    "ChartBlock",
    "ChartDataSeries",
    "BulletListBlock",
    "TableBlock",
    "ImageBlock",
    "QuoteBlock",
    "CalloutBlock",
    "DividerBlock",
    "TimelineBlock",
    "TimelineEvent",
    "ProgressBlock",
    "ProgressItem",
    "ThemeConfig",
    "ThemeRegistry",
    "theme_registry",
    # Infographic templates
    "BlockSpec",
    "InfographicTemplate",
    "InfographicTemplateRegistry",
    "infographic_registry",
    # Nvidia models
    "NvidiaModel",
    # Crew definition models
    "ExecutionMode",
    "AgentDefinition",
    "ToolNodeDefinition",
    "FlowRelation",
    "CrewDefinition",
    # Conference models (FEAT-223)
    "PeerVote",
    "ConferenceRound",
    "ConferenceResult",
    # Store identifiers + data contracts
    "StoreType",
    "StoreConfig",
    "SearchResult",
)
