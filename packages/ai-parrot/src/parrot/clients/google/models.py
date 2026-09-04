"""Google provider model catalogue (FEAT-523 folder convention).

``GoogleModel`` and ``VertexAIModel`` relocated byte-identical from
``parrot/models/google.py`` (TASK-2841). Pure data — no I/O, no imports
from ``client.py``.
"""

from enum import Enum


class GoogleModel(Enum):
    """Enum for Google AI models."""

    GEMINI_FLASH_LATEST = "gemini-flash-latest"
    GEMINI_PRO_LATEST = "gemini-3.1-pro-preview"
    GEMINI_PRO_CUSTOMTOOLS = "gemini-3.1-pro-preview-customtools"
    GEMINI_FLASH_LITE_LATEST = "gemini-3.1-flash-lite"
    # Gemini 3.8 series
    GEMINI_3_8_FLASH = "gemini-3.8-flash"
    # Gemini 3.7 series
    GEMINI_3_7_FLASH = "gemini-3.7-flash"
    GEMINI_3_7_PRO = "gemini-3.7-pro"
    GEMINI_3_7_FLASH_THINKING = "gemini-3.7-flash-thinking"
    GEMINI_3_7_FLASH_LITE = "gemini-3.7-flash-lite"
    # Gemini 3.6 series
    GEMINI_3_6_FLASH = "gemini-3.6-flash"
    GEMINI_3_5_FLASH = "gemini-3.5-flash"
    GEMINI_3_5_FLASH_LITE = "gemini-3.5-flash-lite"
    GEMINI_3_1_FLASH_LITE = "gemini-3.1-flash-lite"
    GEMINI_3_1_PRO_PREVIEW = "gemini-3.1-pro-preview"
    # Aliases for 3.x models mapped to active GA equivalents
    GEMINI_3_PRO = "gemini-3.1-pro-preview"
    GEMINI_3_PRO_PREVIEW = "gemini-3.1-pro-preview"
    GEMINI_3_FLASH = "gemini-3.5-flash"
    GEMINI_3_FLASH_PREVIEW = "gemini-3.5-flash"
    GEMINI_3_1_FLASH_LITE_PREVIEW = "gemini-3.1-flash-lite"
    GEMINI_3_FLASH_LITE_PREVIEW = "gemini-3.1-flash-lite"
    GEMINI_3_1_FLASH_TTS_PREVIEW = "gemini-3.1-flash-tts-preview"
    GEMINI_3_FLASH_TTS = "gemini-3.1-flash-tts-preview"
    GEMINI_3_1_FLASH_LIVE_PREVIEW = "gemini-3.1-flash-live-preview"
    # Gemini 2.5 series
    GEMINI_2_5_FLASH = "gemini-2.5-flash"
    GEMINI_2_5_FLASH_PREVIEW = "gemini-2.5-flash"
    GEMINI_2_5_FLASH_LITE = "gemini-2.5-flash-lite"
    GEMINI_2_5_FLASH_LITE_PREVIEW = "gemini-2.5-flash-lite"
    GEMINI_2_5_PRO = "gemini-2.5-pro"
    GEMINI_2_5_FLASH_TTS = "gemini-2.5-flash-preview-tts"
    GEMINI_2_5_PRO_TTS = "gemini-2.5-pro-preview-tts"
    GEMINI_2_5_FLASH_IMAGE = "gemini-2.5-flash-image"
    GEMINI_COMPUTER_USE = "gemini-2.5-computer-use-preview-10-2025"
    GEMINI_3_FLASH_COMPUTER_USE = "gemini-3-flash-preview"
    GEMINI_3_5_FLASH_COMPUTER_USE = "gemini-3.5-flash"
    # Specialized & Vision models
    GEMINI_DEEP_RESEARCH = "gemini-deep-research-preview-04-2026"
    GEMINI_DEEP_RESEARCH_PREVIEW = "gemini-deep-research-preview-04-2026"
    GEMINI_3_PRO_IMAGE = "gemini-3-pro-image"
    GEMINI_3_PRO_IMAGE_PREVIEW = "gemini-3-pro-image"
    GEMINI_3_1_PRO_IMAGE_PREVIEW = "gemini-3-pro-image"
    GEMINI_3_1_FLASH_IMAGE = "gemini-3.1-flash-image"
    GEMINI_3_1_FLASH_IMAGE_PREVIEW = "gemini-3.1-flash-image"
    GEMINI_3_1_FLASH_LITE_IMAGE = "gemini-3.1-flash-lite-image"
    GEMINI_2_5_FLASH_IMAGE_PREVIEW = "gemini-2.5-flash-image"
    GEMINI_FLASH_IMAGE = "gemini-3.1-flash-image"
    # Media & Audio generation models
    VEO_3_1 = "veo-3.1-generate-preview"
    VEO_3_1_FAST = "veo-3.1-fast-generate-preview"
    VEO_3_1_LITE = "veo-3.1-lite-generate-preview"
    LYRIA = "lyria-3-pro-preview"
    LYRIA_CLIP = "lyria-3-clip-preview"
    IMAGEN_3 = "imagen-3.0-generate-002"
    IMAGEN_4 = "imagen-4.0-generate-001"
    IMAGE_4_ULTRA = "imagen-4.0-ultra-generate-001"
    IMAGEN_4_ULTRA = "imagen-4.0-ultra-generate-001"


class VertexAIModel(Enum):
    """Enum for Vertex AI models.

    Note: Gemini 3.x models require location='global' on Vertex AI.
    Preview models additionally require api_version='v1beta1'.
    """

    GEMINI_3_8_FLASH = "gemini-3.8-flash"
    GEMINI_3_7_FLASH = "gemini-3.7-flash"
    GEMINI_3_7_PRO = "gemini-3.7-pro"
    GEMINI_3_6_FLASH = "gemini-3.6-flash"
    GEMINI_3_5_FLASH = "gemini-3.5-flash"
    GEMINI_3_5_FLASH_LITE = "gemini-3.5-flash-lite"
    GEMINI_3_1_PRO_PREVIEW = "gemini-3.1-pro-preview"
    GEMINI_3_1_FLASH_LITE = "gemini-3.1-flash-lite"
    GEMINI_3_PRO_IMAGE = "gemini-3-pro-image"
    GEMINI_3_1_FLASH_IMAGE = "gemini-3.1-flash-image"
    GEMINI_3_1_FLASH_LITE_IMAGE = "gemini-3.1-flash-lite-image"
    GEMINI_2_5_FLASH = "gemini-2.5-flash"
    GEMINI_2_5_FLASH_LITE = "gemini-2.5-flash-lite"
    GEMINI_2_5_PRO = "gemini-2.5-pro"
    IMAGEN_3 = "imagen-3.0-generate-002"
    IMAGEN_4 = "imagen-4.0-generate-001"
    IMAGEN_4_ULTRA = "imagen-4.0-ultra-generate-001"


__all__ = ["GoogleModel", "VertexAIModel"]
