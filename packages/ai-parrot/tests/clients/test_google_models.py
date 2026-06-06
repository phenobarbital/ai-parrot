"""Tests for GoogleModel computer-use entries (TASK-1480)."""
import pytest
from parrot.models.google import GoogleModel


class TestGoogleModelComputerUseEntries:
    """Tests for new computer-use model enum entries."""

    def test_gemini_computer_use_exists(self):
        assert "GEMINI_COMPUTER_USE" in GoogleModel.__members__

    def test_gemini_computer_use_value(self):
        assert GoogleModel.__members__["GEMINI_COMPUTER_USE"].value == (
            "gemini-2.5-computer-use-preview-10-2025"
        )

    def test_gemini_3_flash_computer_use_exists(self):
        assert "GEMINI_3_FLASH_COMPUTER_USE" in GoogleModel.__members__

    def test_gemini_3_flash_computer_use_value(self):
        assert GoogleModel.__members__["GEMINI_3_FLASH_COMPUTER_USE"].value == (
            "gemini-3-flash-preview"
        )

    def test_existing_entries_unchanged(self):
        """Ensure existing model entries are not broken."""
        assert GoogleModel.GEMINI_FLASH_LATEST.value == "gemini-flash-latest"
        assert GoogleModel.GEMINI_2_5_PRO.value == "gemini-2.5-pro"
        assert GoogleModel.GEMINI_2_5_FLASH.value == "gemini-2.5-flash"
