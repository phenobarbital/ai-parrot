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
