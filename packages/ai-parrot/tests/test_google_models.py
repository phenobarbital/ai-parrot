"""Tests for GoogleModel enum entries."""

import pytest

from parrot.clients.google.models import GoogleModel  # FEAT-523 (TASK-2841): relocated


def test_google_model_enum_has_gemini_3_5_flash():
    """GEMINI_3_5_FLASH is registered with the canonical Google identifier."""
    assert GoogleModel.GEMINI_3_5_FLASH.value == "gemini-3.5-flash"


def test_google_model_enum_has_gemini_3_8_flash():
    """GEMINI_3_8_FLASH is registered with the canonical Google identifier."""
    assert GoogleModel.GEMINI_3_8_FLASH.value == "gemini-3.8-flash"


def test_google_model_enum_has_gemini_3_7_flash():
    """GEMINI_3_7_FLASH is registered with the canonical Google identifier."""
    assert GoogleModel.GEMINI_3_7_FLASH.value == "gemini-3.7-flash"


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


RETIRED_VALUES = (
    "gemini-3.7-pro",
    "gemini-3.7-flash-thinking",
    "gemini-3.7-flash-lite",
    "gemini-deep-research-preview-04-2026",
)
RETIRED_NAMES = (
    "GEMINI_3_7_PRO",
    "GEMINI_3_7_FLASH_THINKING",
    "GEMINI_3_7_FLASH_LITE",
    "GEMINI_DEEP_RESEARCH",
    "GEMINI_DEEP_RESEARCH_PREVIEW",
)


def test_google_model_enum_has_gemini_4_argon():
    """GEMINI_4_ARGON is registered and reachable by value (FEAT-688)."""
    assert GoogleModel.GEMINI_4_ARGON.value == "gemini-4-argon"
    assert GoogleModel("gemini-4-argon") is GoogleModel.GEMINI_4_ARGON


@pytest.mark.parametrize("value", RETIRED_VALUES)
def test_google_model_retired_values_raise(value):
    """Ids no longer served by the Gemini API are deleted outright (FEAT-688 U2)."""
    with pytest.raises(ValueError):
        GoogleModel(value)


def test_google_model_retired_names_absent():
    """The five retired member names are gone from GoogleModel."""
    assert not set(RETIRED_NAMES) & GoogleModel.__members__.keys()


def test_google_model_alias_count():
    """Guards against a new member silently collapsing onto an existing value."""
    assert len(GoogleModel.__members__) == 49
    assert len({model.value for model in GoogleModel}) == 31
