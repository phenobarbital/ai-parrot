from unittest.mock import MagicMock

import pytest

from parrot.clients.google import GoogleGenAIClient


def test_plain_38_flash_not_enabled():
    client = GoogleGenAIClient(api_key="k")

    assert client._computer_use_enabled("gemini-3.8-flash") is False


def test_opt_in_enables_v38_vocabulary():
    client = GoogleGenAIClient(api_key="k")
    client.computer_use = True

    assert client._computer_use_enabled("gemini-3.8-flash") is True
    assert client._computer_use_vocabulary("gemini-3.8-flash") == "v3_8"


def test_retired_legacy_model_no_longer_computer_use():
    """FEAT-798: the shut-down 2.5 computer-use id lost its implicit computer-use routing."""
    client = GoogleGenAIClient(api_key="k")
    retired = "gemini-2.5-computer-use-preview-10-2025"

    assert GoogleGenAIClient._is_computer_use_model(retired) is False
    assert client._computer_use_enabled(retired) is False


def test_remaining_legacy_model_keeps_legacy_vocabulary():
    """gemini-3-flash-preview is the only id still enabled implicitly, with the legacy vocabulary."""
    client = GoogleGenAIClient(api_key="k")

    assert client._computer_use_enabled("gemini-3-flash-preview") is True
    assert client._computer_use_vocabulary("gemini-3-flash-preview") == "legacy"


def test_v38_scroll_args():
    output = GoogleGenAIClient._adapt_computer_use_args(
        "scroll",
        {"x": 500, "y": 500, "direction": "down", "magnitude_in_pixels": 500, "intent": "i"},
        "v3_8",
    )

    assert output == {"x": 500, "y": 500, "direction": "down", "magnitude": 500}


def test_v38_drag_and_drop_and_hotkey_args():
    drag = GoogleGenAIClient._adapt_computer_use_args(
        "drag_and_drop",
        {"start_x": 1, "start_y": 2, "end_x": 3, "end_y": 4, "intent": "i"},
        "v3_8",
    )
    hotkey = GoogleGenAIClient._adapt_computer_use_args("hotkey", {"keys": ["control", "c"], "intent": "i"}, "v3_8")

    assert drag == {"x": 1, "y": 2, "destination_x": 3, "destination_y": 4}
    assert hotkey == {"keys": "control,c"}


@pytest.mark.asyncio
async def test_unknown_v38_action_returns_error_response():
    client = GoogleGenAIClient(api_key="k")
    client.logger = MagicMock()
    client.computer_use = True

    result = await client._execute_computer_use_call("pinch", {"intent": "i"}, model="gemini-3.8-flash")

    assert result["error"] is True
    assert result["action"] == "pinch"
    client.logger.error.assert_called_once()


def test_opt_in_without_config_raises():
    client = GoogleGenAIClient(api_key="k")
    client.computer_use = True

    with pytest.raises(ValueError, match="_computer_use_config is not set"):
        client._build_tools("computer_use")
