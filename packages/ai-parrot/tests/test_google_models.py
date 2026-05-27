"""Tests for GoogleModel enum entries."""
from parrot.models.google import GoogleModel


def test_google_model_enum_has_gemini_3_5_flash():
    """GEMINI_3_5_FLASH is registered with the canonical Google identifier."""
    assert GoogleModel.GEMINI_3_5_FLASH.value == "gemini-3.5-flash"


def test_google_model_lookup_by_value():
    """The new entry is reachable via Enum(value) lookup."""
    assert GoogleModel("gemini-3.5-flash") is GoogleModel.GEMINI_3_5_FLASH
