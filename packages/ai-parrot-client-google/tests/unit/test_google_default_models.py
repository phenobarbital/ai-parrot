"""FEAT-798: Google mixin method defaults no longer name retired 2.5 members."""

import inspect

import pytest

from parrot.clients.google import GoogleGenAIClient
from parrot.clients.google.models import GoogleModel

FLASH_DEFAULTS = (
    "analyze_sentiment",
    "analyze_product_review",
    "document_understanding",
    "summarize_text",
    "translate_text",
    "extract_key_points",
    "create_conversation_script",
)


def _default(method_name: str) -> GoogleModel:
    return inspect.signature(getattr(GoogleGenAIClient, method_name)).parameters["model"].default


@pytest.mark.parametrize("method_name", FLASH_DEFAULTS)
def test_flash_class_defaults_are_3_8_flash(method_name: str) -> None:
    assert _default(method_name) is GoogleModel.GEMINI_3_8_FLASH


def test_image_identification_default_is_argon() -> None:
    assert _default("image_identification") is GoogleModel.GEMINI_4_ARGON


def test_generate_speech_default_is_3_8_tts() -> None:
    assert _default("generate_speech") is GoogleModel.GEMINI_3_8_FLASH_TTS
