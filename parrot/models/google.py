"""
Google Related Models to be used in GenAI.
"""
from typing import Literal, List
from enum import Enum
from pydantic import BaseModel, Field

class GoogleModel(Enum):
    """Enum for Google AI models."""
    GEMINI_2_5_FLASH = "gemini-2.5-flash"
    GEMINI_2_5_FLASH_LITE_PREVIEW = "gemini-2.5-flash-lite-preview-06-17"
    GEMINI_2_5_PRO = "gemini-2.5-pro"
    GEMINI_2_0_FLASH = "gemini-2.0-flash-001"
    IMAGEN_3 = "imagen-3.0-generate-002"
    IMAGEN_4 = "imagen-4.0-generate-preview-06-06"
    GEMINI_2_0_IMAGE_GENERATION = "gemini-2.0-flash-preview-image-generation"
    GEMINI_2_5_FLASH_TTS = "gemini-2.5-flash-preview-tts"
    GEMINI_2_5_PRO_TTS = "gemini-2.5-pro-preview-tts"
    VEO_3_0 = "veo-3.0-generate-preview"
    VEO_2_0 = "veo-2.0-generate-001"

# NEW: Enum for all valid TTS voice names
class TTSVoice(str, Enum):
    """Google TTS voices."""
    ACHERNAR = "achernar"
    ACHIRD = "achird"
    ALGENIB = "algenib"
    ALGIEBA = "algieba"
    ALNILAM = "alnilam"
    AOEDE = "aoede"
    AUTONOE = "autonoe"
    CALLIRRHOE = "callirrhoe"
    CHARON = "charon"
    DESPINA = "despina"
    ENCELADUS = "enceladus"
    ERINOME = "erinome"
    FENRIR = "fenrir"
    GACRUX = "gacrux"
    IAPETUS = "iapetus"
    KORE = "kore"
    LAOMEDEIA = "laomedeia"
    LEDA = "leda"
    ORUS = "orus"
    PUCK = "puck"
    PULCHERRIMA = "pulcherrima"
    RASALGETHI = "rasalgethi"
    SADACHBIA = "sadachbia"
    SADALTAGER = "sadaltager"
    SCHEDAR = "schedar"
    SULAFAT = "sulafat"
    UMBRIEL = "umbriel"
    VINDEMIATRIX = "vindemiatrix"
    ZEPHYR = "zephyr"
    ZUBENELGENUBI = "zubenelgenubi"


class VertexAIModel(Enum):
    """Enum for Vertex AI models."""
    GEMINI_2_5_FLASH = "gemini-2.5-flash"
    GEMINI_2_5_FLASH_LITE_PREVIEW = "gemini-2.5-flash-lite-preview-06-17"
    GEMINI_2_5_PRO = "gemini-2.5-pro"
    GEMINI_2_0_FLASH = "gemini-2.0-flash-001"
    IMAGEN_3_FAST = "Imagen 3 Fast"


# Define the gender type for clarity and validation
Gender = Literal["female", "male", "neutral"]


class VoiceProfile(BaseModel):
    """
    Represents a single pre-built generative voice, mapping its name
    to its known characteristics and gender.
    """
    voice_name: str = Field(..., description="The official name of the voice (e.g., 'Erinome').")
    characteristic: str = Field(..., description="The primary characteristic of the voice (e.g., 'Clear', 'Upbeat').")
    gender: Gender = Field(..., description="The perceived gender of the voice.")


# This list is based on the official documentation for Google's generative voices.
# It represents the "HTML table" data you referred to.
ALL_VOICE_PROFILES: List[VoiceProfile] = [
    VoiceProfile(voice_name="Zephyr", characteristic="Bright", gender="female"),
    VoiceProfile(voice_name="Puck", characteristic="Upbeat", gender="male"),
    VoiceProfile(voice_name="Charon", characteristic="Informative", gender="male"),
    VoiceProfile(voice_name="Kore", characteristic="Firm", gender="female"),
    VoiceProfile(voice_name="Fenrir", characteristic="Excitable", gender="male"),
    VoiceProfile(voice_name="Leda", characteristic="Youthful", gender="female"),
    VoiceProfile(voice_name="Orus", characteristic="Firm", gender="male"),
    VoiceProfile(voice_name="Aoede", characteristic="Breezy", gender="female"),
    VoiceProfile(voice_name="Callirrhoe", characteristic="Easy-going", gender="female"),
    VoiceProfile(voice_name="Autonoe", characteristic="Bright", gender="female"),
    VoiceProfile(voice_name="Enceladus", characteristic="Breathy", gender="male"),
    VoiceProfile(voice_name="Iapetus", characteristic="Clear", gender="male"),
    VoiceProfile(voice_name="Umbriel", characteristic="Easy-going", gender="male"),
    VoiceProfile(voice_name="Algieba", characteristic="Smooth", gender="male"),
    VoiceProfile(voice_name="Despina", characteristic="Smooth", gender="female"),
    VoiceProfile(voice_name="Erinome", characteristic="Clear", gender="female"),
    VoiceProfile(voice_name="Algenib", characteristic="Gravelly", gender="male"),
    VoiceProfile(voice_name="Rasalgethi", characteristic="Informative", gender="male"),
    VoiceProfile(voice_name="Laomedeia", characteristic="Upbeat", gender="female"),
    VoiceProfile(voice_name="Achernar", characteristic="Soft", gender="female"),
    VoiceProfile(voice_name="Alnilam", characteristic="Firm", gender="female"),
    VoiceProfile(voice_name="Schedar", characteristic="Even", gender="female"),
    VoiceProfile(voice_name="Gacrux", characteristic="Mature", gender="female"),
    VoiceProfile(voice_name="Pulcherrima", characteristic="Forward", gender="female"),
    VoiceProfile(voice_name="Achird", characteristic="Friendly", gender="female"),
    VoiceProfile(voice_name="Zubenelgenubi", characteristic="Casual", gender="male"),
    VoiceProfile(voice_name="Vindemiatrix", characteristic="Gentle", gender="female"),
    VoiceProfile(voice_name="Sadachbia", characteristic="Lively", gender="female"),
    VoiceProfile(voice_name="Sadaltager", characteristic="Knowledgeable", gender="male"),
    VoiceProfile(voice_name="Sulafat", characteristic="Warm", gender="female"),
]
