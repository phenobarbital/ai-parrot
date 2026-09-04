import pytest

from parrot.models.voice import LiveVoiceResponse


class TestLiveVoiceResponseRole:
    def test_role_defaults_to_none(self):
        """Additive change: existing construction is unaffected."""
        assert LiveVoiceResponse().role is None

    def test_role_can_be_set(self):
        assert LiveVoiceResponse(role="ASSISTANT").role == "ASSISTANT"

    def test_to_websocket_message_includes_role(self):
        msg = LiveVoiceResponse(text="hi", role="ASSISTANT").to_websocket_message()
        assert msg["role"] == "ASSISTANT"

    def test_to_websocket_message_role_is_none_by_default(self):
        assert LiveVoiceResponse(text="hi").to_websocket_message()["role"] is None

    def test_existing_websocket_keys_unchanged(self):
        """Regression guard: consumers depend on these exact keys."""
        msg = LiveVoiceResponse(text="hi").to_websocket_message()
        for key in (
            "type",
            "text",
            "audio_base64",
            "audio_format",
            "is_complete",
            "is_interrupted",
            "tool_calls",
            "usage",
            "metadata",
            "session_id",
            "turn_id",
        ):
            assert key in msg
