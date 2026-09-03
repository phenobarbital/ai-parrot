"""Tests for GoogleModel enum entries."""

from parrot.models.google import GoogleModel


def test_google_model_enum_has_gemini_3_5_flash():
    """GEMINI_3_5_FLASH is registered with the canonical Google identifier."""
    assert GoogleModel.GEMINI_3_5_FLASH.value == "gemini-3.5-flash"


def test_google_model_enum_has_gemini_3_8_flash():
    """GEMINI_3_8_FLASH is registered with the canonical Google identifier."""
    assert GoogleModel.GEMINI_3_8_FLASH.value == "gemini-3.8-flash"


def test_google_model_enum_has_gemini_3_7_flash():
    """GEMINI_3_7_FLASH is registered with the canonical Google identifier."""
    assert GoogleModel.GEMINI_3_7_FLASH.value == "gemini-3.7-flash"
    assert GoogleModel.GEMINI_3_7_PRO.value == "gemini-3.7-pro"
    assert GoogleModel.GEMINI_3_7_FLASH_THINKING.value == "gemini-3.7-flash-thinking"


def test_google_model_enum_has_gemini_3_6_flash():
    """GEMINI_3_6_FLASH, GEMINI_3_5_FLASH_LITE, GEMINI_3_1_FLASH_LITE, and GEMINI_3_1_FLASH_LITE_IMAGE are registered."""
    assert GoogleModel.GEMINI_3_6_FLASH.value == "gemini-3.6-flash"
    assert GoogleModel.GEMINI_3_5_FLASH_LITE.value == "gemini-3.5-flash-lite"
    assert GoogleModel.GEMINI_3_1_FLASH_LITE.value == "gemini-3.1-flash-lite"
    assert GoogleModel.GEMINI_3_1_FLASH_LITE_IMAGE.value == "gemini-3.1-flash-lite-image"


def test_google_model_lookup_by_value():
    """The new entry is reachable via Enum(value) lookup."""
    assert GoogleModel("gemini-3.5-flash") is GoogleModel.GEMINI_3_5_FLASH
    assert GoogleModel("gemini-3.6-flash") is GoogleModel.GEMINI_3_6_FLASH
    assert GoogleModel("gemini-3.5-flash-lite") is GoogleModel.GEMINI_3_5_FLASH_LITE
    assert GoogleModel("gemini-3.1-flash-lite-image") is GoogleModel.GEMINI_3_1_FLASH_LITE_IMAGE
    assert GoogleModel("gemini-3.8-flash") is GoogleModel.GEMINI_3_8_FLASH
    assert GoogleModel("gemini-3.7-flash") is GoogleModel.GEMINI_3_7_FLASH
    assert GoogleModel("gemini-3.7-pro") is GoogleModel.GEMINI_3_7_PRO
