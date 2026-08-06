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
from dataclasses import dataclass
from enum import Enum
from typing import Optional


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
