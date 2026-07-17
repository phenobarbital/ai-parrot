"""
Voice configuration models for VoiceBot.

Contains configuration dataclasses for audio sessions used
by VoiceBot in parrot/bots/voice.py.
"""
from dataclasses import dataclass
from enum import Enum
from .google import GoogleVoiceModel


# Voice models
class AudioFormat(Enum):
    """Audio formats for voice sessions."""
    PCM_16K = "audio/pcm;rate=16000"
    PCM_24K = "audio/pcm;rate=24000"


@dataclass
class VoiceConfig:
    """Configuration for Audio Sessions"""
    # Model
    model: str = GoogleVoiceModel.DEFAULT

    # FEAT-302/FEAT-315: which voice LLM backend VoiceBot should use.
    # Currently supported: "google_live" (default — GeminiLiveClient) and
    # "nova" (experimental — parrot.clients.nova.NovaClient, requires the
    # optional Pre-Alpha aws_sdk_bedrock_runtime SDK, Python >= 3.12 only,
    # only at first stream_voice() call). A plain string rather than an
    # enum import: parrot.voice.models.VoiceProvider lives in the
    # ai-parrot-integrations satellite package, which depends on core
    # ai-parrot — not the other way around. Values are expected to match
    # VoiceProvider.value from that enum when both are in play. FEAT-315
    # breaking change: the provider key was renamed from "nova_sonic" to
    # "nova" (VoiceProvider.NOVA_SONIC → VoiceProvider.NOVA); there is no
    # backward-compatible alias.
    provider: str = "google_live"

    # Voice
    voice_name: str = "Puck"
    language: str = "en-US"

    # Audio
    input_format: AudioFormat = AudioFormat.PCM_16K
    output_format: AudioFormat = AudioFormat.PCM_24K

    # Generation
    temperature: float = 0.7
    max_tokens: int = 4096

    # VAD
    enable_vad: bool = True

    # Transcription
    enable_input_transcription: bool = True
    enable_output_transcription: bool = True

    def get_model(self) -> str:
        """Get configured model."""
        return self.model
