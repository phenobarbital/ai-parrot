"""Tests for GoogleModel computer-use entries."""

from parrot.clients.google.models import GoogleModel  # FEAT-523 (TASK-2841): relocated


class TestGoogleModelComputerUseEntries:
    """Tests for new computer-use model enum entries."""

    def test_retired_computer_use_absent(self):
        """FEAT-798: the 2.5 computer-use preview is gone."""
        assert "GEMINI_COMPUTER_USE" not in GoogleModel.__members__

    def test_gemini_3_flash_computer_use_exists(self):
        assert "GEMINI_3_FLASH_COMPUTER_USE" in GoogleModel.__members__

    def test_gemini_3_flash_computer_use_value(self):
        assert GoogleModel.__members__["GEMINI_3_FLASH_COMPUTER_USE"].value == ("gemini-3-flash-preview")

    def test_existing_entries_unchanged(self):
        """Ensure existing model entries are not broken."""
        assert GoogleModel.GEMINI_FLASH_LATEST.value == "gemini-flash-latest"
