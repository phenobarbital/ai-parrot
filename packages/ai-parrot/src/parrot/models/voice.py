"""
Voice configuration models for VoiceBot (unified, FEAT-416).

Contains the single source-of-truth ``VoiceConfig`` dataclass and
``VoiceProvider`` enum used by ``VoiceBot`` (``parrot/bots/voice.py``),
``VoiceSession`` (``parrot/voice/session.py``), and the
ai-parrot-integrations ``VoiceChatHandler``.

Prior to FEAT-416, two incompatible ``VoiceConfig`` classes existed: this
core (11-field) version and a 17-field version in the ai-parrot-integrations
satellite package's ``parrot.voice.models``, with ``provider`` typed as a
plain ``str`` here and a ``VoiceProvider`` enum there. FEAT-416 merges both
into this single class and promotes ``VoiceProvider`` to core. The
integrations ``parrot.voice.models.VoiceConfig`` is now a deprecation-warning
re-export of this class (see that module for the shim); ``VoiceProvider`` is
re-exported there too, without a deprecation warning (a move, not a rename).
"""
import base64
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional


# Voice models
class AudioFormat(Enum):
    """Audio formats for voice sessions."""
    PCM_16K = "audio/pcm;rate=16000"
    PCM_24K = "audio/pcm;rate=24000"


class VoiceProvider(str, Enum):
    """Supported voice providers (promoted from
    ``parrot.voice.models`` in ai-parrot-integrations, FEAT-416).

    Inherits from ``str`` (matching the ``GoogleVoiceModel`` pattern in
    ``parrot.models.google``) so plain-string comparisons already used
    throughout the codebase (e.g. ``voice_config.provider == "nova"``)
    keep working once ``VoiceConfig.__post_init__`` coerces the
    ``provider`` field to this enum.
    """
    GOOGLE_LIVE = "google_live"
    OPENAI_REALTIME = "openai_realtime"
    WHISPER_TTS = "whisper_tts"
    # FEAT-302/FEAT-315: Amazon Nova 2 Sonic bidirectional voice —
    # backed by parrot.clients.nova.NovaClient. FEAT-315 breaking change:
    # renamed from the previous snake-case provider key; no alias kept.
    NOVA = "nova"


@dataclass
class VoiceConfig:
    """Unified configuration for voice sessions (FEAT-416).

    Merges the former core (11-field) and ai-parrot-integrations
    (17-field) ``VoiceConfig`` classes into one source of truth, and adds
    the inference (``top_p``), reconnection (``reconnect_on_limit``,
    ``max_reconnects``), and parallel-tool-execution fields introduced by
    the Voice Agent Framework (spec §2).
    """
    # Provider
    provider: VoiceProvider = VoiceProvider.GOOGLE_LIVE

    # Audio formats
    input_format: AudioFormat = AudioFormat.PCM_16K
    output_format: AudioFormat = AudioFormat.PCM_24K
    input_sample_rate: int = 16000
    output_sample_rate: int = 24000

    # Model & voice
    # NOTE: default is None (not a provider-specific model constant) so
    # this config stays provider-agnostic; provider-specific defaults are
    # applied downstream (e.g. GeminiLiveClient, VoiceBot._resolve_llm_config).
    model: Optional[str] = None
    voice_name: str = "Puck"
    language: str = "en-US"

    # Inference
    temperature: float = 0.7
    max_tokens: int = 4096
    top_p: float = 0.9

    # VAD
    enable_vad: bool = True
    vad_mode: str = "server_vad"
    enable_interruption: bool = True

    # Transcription
    enable_input_transcription: bool = True
    enable_output_transcription: bool = True

    # Session
    session_timeout_seconds: int = 1800
    silence_timeout_seconds: int = 30
    reconnect_on_limit: bool = True
    max_reconnects: int = 3

    # Tools
    parallel_tool_execution: bool = False

    def __post_init__(self):
        """Coerce a plain-string ``provider`` into the ``VoiceProvider``
        enum, so both ``VoiceConfig(provider="nova")`` (current core
        callers) and ``VoiceConfig(provider=VoiceProvider.NOVA)`` (current
        integrations callers) are accepted."""
        if isinstance(self.provider, str):
            self.provider = VoiceProvider(self.provider)

    def get_model(self) -> str:
        """Get configured model."""
        return self.model

    def to_stream_options(self, **overrides: object) -> "VoiceStreamOptions":
        """Project this config into the per-call option object (FEAT-418).

        This is the single place a ``VoiceConfig`` becomes per-call
        ``VoiceStreamOptions`` — ``VoiceBot``, ``VoiceSession`` and
        ``VoiceChatHandler`` all go through this method instead of
        building their own ad-hoc kwargs dict.

        Args:
            **overrides: Explicit per-call values that win over the values
                derived from this config, preserving the precedence
                ``VoiceBot.ask_stream()`` implements today
                (``bots/voice.py:539-545``).

        Returns:
            A frozen ``VoiceStreamOptions`` instance.
        """
        projected = {
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "top_p": self.top_p,
            "voice": self.voice_name,
            "language": self.language,
            "stt_only": False,
            "parallel_tool_execution": self.parallel_tool_execution,
            "enable_input_transcription": self.enable_input_transcription,
            "enable_output_transcription": self.enable_output_transcription,
        }
        projected.update(overrides)
        return VoiceStreamOptions(**projected)


@dataclass(frozen=True)
class VoiceStreamOptions:
    """Per-call voice options, projected from ``VoiceConfig`` (FEAT-418).

    Provider-specific extras continue to travel via ``**kwargs``; anything
    in THIS object must be honored identically by every ``VoiceCapable``
    client.

    Attributes:
        temperature: Sampling temperature.
        max_tokens: Maximum output tokens.
        top_p: Nucleus-sampling probability mass.
        voice: Provider-native voice name. ``None`` means "provider
            default" — do NOT default this to a Gemini-specific voice
            name like ``"Puck"``; leaking it into Nova was the bug this
            feature fixes (``bots/voice.py:198``).
        language: BCP-47 language tag.
        stt_only: Request speech-to-text-only behavior. Not every
            provider can honor this natively (see
            ``VoiceCapabilities.native_stt_only``).
        parallel_tool_execution: Whether to execute tool calls in
            parallel.
        enable_input_transcription: Whether to transcribe user audio.
        enable_output_transcription: Whether to transcribe model audio.
    """
    temperature: float = 0.7
    max_tokens: int = 4096
    top_p: float = 0.9
    voice: str | None = None
    language: str = "en-US"
    stt_only: bool = False
    parallel_tool_execution: bool = False
    enable_input_transcription: bool = True
    enable_output_transcription: bool = True


@dataclass(frozen=True)
class VoiceCapabilities:
    """What a provider natively supports (FEAT-418).

    Inspectable at runtime and asserted against observed behavior by the
    provider conformance suite (``tests/voice/test_provider_conformance.py``).

    Attributes:
        provider: The provider this descriptor describes.
        native_stt_only: Whether the provider can natively suppress its
            spoken response when ``stt_only=True`` is requested.
        supports_top_p: Whether ``top_p`` reaches the provider.
        supports_per_call_voice: Whether the voice can be overridden
            per-call (vs. constructor-only).
        supports_per_call_inference: Whether inference params
            (``temperature``/``max_tokens``) can be overridden per-call.
        parallel_tool_execution: Whether the provider supports executing
            tool calls in parallel.
        emits_reconnect_signal: Whether the provider emits
            ``metadata["reconnect_required"]`` at its session limit.
        supports_session_resumption: Whether the provider can resume a
            session using a stored handle rather than reconnecting cold.
        max_session_seconds: The provider's documented session limit, or
            ``None`` if no such limit is documented.
        max_output_tokens: The provider's maximum output tokens.

            NOTE: Nova 2 Sonic's real ceiling is not yet confirmed against
            the Bedrock docs (spec §8 Open Questions) — ``4096`` is used
            here as a documented placeholder until that value is verified.
        input_formats: Audio formats the provider accepts as input.
        output_formats: Audio formats the provider emits as output.
        input_sample_rates: Sample rates the provider accepts as input.
        output_sample_rates: Sample rates the provider emits as output.
        voice_catalog: The set of provider-native voice names.
        default_voice: The provider's default voice name.
    """
    provider: VoiceProvider

    # Behavioral knobs
    native_stt_only: bool
    supports_top_p: bool
    supports_per_call_voice: bool
    supports_per_call_inference: bool
    parallel_tool_execution: bool

    # Session lifecycle
    emits_reconnect_signal: bool
    supports_session_resumption: bool
    max_session_seconds: float | None

    # Inference bounds
    max_output_tokens: int

    # Audio contract (G4) — descriptive today, load-bearing for a future
    # non-PCM provider (Opus, mu-law, other rates).
    input_formats: frozenset[AudioFormat]
    output_formats: frozenset[AudioFormat]
    input_sample_rates: frozenset[int]
    output_sample_rates: frozenset[int]

    # Synthesis
    voice_catalog: frozenset[str]
    default_voice: str


# =============================================================================
# Live-response models (FEAT-523, TASK-2841): relocated byte-identical from
# ``parrot/clients/live.py`` (now ``parrot/clients/google/live.py``).
# ``LiveVoiceResponse`` is the only type ``parrot.clients.protocols.
# VoiceCapable`` needs, but it depends on the three dataclasses below, and
# all four are pure data (no I/O, no client/SDK imports) — moved together
# so core never has to import a satellite to type-check ``VoiceCapable``.
# =============================================================================


@dataclass
class LiveCompletionUsage:
    """
    Usage tracking for Gemini Live API responses.

    Compatible with CompletionUsage from parrot.models.basic
    """

    # Core token metrics
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    # Aliases for Gemini naming
    input_tokens: int = 0
    output_tokens: int = 0

    # Audio-specific metrics
    input_audio_duration_ms: float = 0.0
    output_audio_duration_ms: float = 0.0

    # Timing
    response_time_ms: float = 0.0
    first_token_time_ms: float = 0.0

    # Tool execution
    tool_calls_executed: int = 0
    tool_execution_time_ms: float = 0.0

    # Provider metadata
    extra: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        # Sync aliases
        if self.input_tokens and not self.prompt_tokens:
            self.prompt_tokens = self.input_tokens
        if self.output_tokens and not self.completion_tokens:
            self.completion_tokens = self.output_tokens
        if not self.total_tokens:
            self.total_tokens = self.prompt_tokens + self.completion_tokens

    @classmethod
    def from_gemini_usage(cls, usage_metadata: Any) -> "LiveCompletionUsage":
        """Create from Gemini usage metadata when available."""
        if usage_metadata is None:
            return cls()

        return cls(
            prompt_tokens=getattr(usage_metadata, "prompt_token_count", 0) or 0,
            completion_tokens=getattr(usage_metadata, "candidates_token_count", 0) or 0,
            total_tokens=getattr(usage_metadata, "total_token_count", 0) or 0,
            input_tokens=getattr(usage_metadata, "prompt_token_count", 0) or 0,
            output_tokens=getattr(usage_metadata, "candidates_token_count", 0) or 0,
            extra=usage_metadata.__dict__ if hasattr(usage_metadata, "__dict__") else {},
        )


@dataclass
class LiveToolCall:
    """Represents a tool call from Gemini Live API."""

    id: str
    name: str
    arguments: Dict[str, Any]
    result: Optional[Any] = None
    error: Optional[str] = None
    execution_time_ms: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "arguments": self.arguments,
            "result": self.result,
            "error": self.error,
            "execution_time_ms": self.execution_time_ms,
        }


@dataclass
class VoiceTurnMetadata:
    """Metadata for a single voice turn/response."""

    turn_id: str
    started_at: datetime = field(default_factory=datetime.now)
    ended_at: Optional[datetime] = None
    input_transcription: Optional[str] = None
    output_transcription: Optional[str] = None
    tool_calls_count: int = 0
    was_interrupted: bool = False

    @property
    def duration_ms(self) -> float:
        if self.ended_at:
            return (self.ended_at - self.started_at).total_seconds() * 1000
        return 0.0


@dataclass
class LiveVoiceResponse:
    """
    Response from GeminiLiveClient voice interaction.

    Enhanced version of VoiceResponse with CompletionUsage metadata
    for consistency with other AbstractClient implementations.
    """

    # Content
    text: str = ""
    audio_data: Optional[bytes] = None
    audio_format: str = "audio/pcm;rate=24000"

    # State
    is_complete: bool = False
    is_interrupted: bool = False

    # Tool calls
    tool_calls: List[LiveToolCall] = field(default_factory=list)

    # Usage metadata - consistent with CompletionUsage
    usage: Optional[LiveCompletionUsage] = None

    # Turn metadata
    turn_metadata: Optional[VoiceTurnMetadata] = None

    # Session info
    session_id: Optional[str] = None
    turn_id: Optional[str] = None
    user_id: Optional[str] = None

    # Speaker attribution (FEAT-408, canonicalized lowercase in FEAT-418)
    role: Optional[str] = None
    """Speaker this frame is attributed to: "user" or "assistant" (canonical
    lowercase form, FEAT-418). GeminiLiveClient sets this on every
    model-originated and user-transcription frame as of FEAT-418
    (previously always None here; user transcription instead traveled via
    the now-removed metadata["user_transcription"])."""

    # Extra metadata
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_websocket_message(self) -> Dict[str, Any]:
        """Format for WebSocket transmission."""

        return {
            "type": "voice_response",
            "text": self.text,
            "audio_base64": base64.b64encode(self.audio_data).decode() if self.audio_data else None,
            "audio_format": self.audio_format,
            "is_complete": self.is_complete,
            "is_interrupted": self.is_interrupted,
            "tool_calls": [tc.to_dict() for tc in self.tool_calls],
            "usage": (
                {
                    "prompt_tokens": self.usage.prompt_tokens if self.usage else 0,
                    "completion_tokens": self.usage.completion_tokens if self.usage else 0,
                    "total_tokens": self.usage.total_tokens if self.usage else 0,
                    "response_time_ms": self.usage.response_time_ms if self.usage else 0,
                }
                if self.usage
                else None
            ),
            "metadata": self.metadata,
            "session_id": self.session_id,
            "turn_id": self.turn_id,
            "role": self.role,
        }
