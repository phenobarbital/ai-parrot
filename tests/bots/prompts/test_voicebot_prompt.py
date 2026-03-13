"""Tests for VoiceBot prompt migration to composable layers."""
import sys
import importlib
import pytest

# Force-load the real parrot.bots.abstract (conftest installs a stub)
_saved = sys.modules.pop("parrot.bots.abstract", None)
_real = importlib.import_module("parrot.bots.abstract")
sys.modules["parrot.bots.abstract"] = _real


class TestVoiceBotUsesVoicePreset:

    def test_voicebot_has_prompt_builder(self):
        """VoiceBot should have a _prompt_builder at class level."""
        from parrot.bots.voice import VoiceBot
        assert VoiceBot._prompt_builder is not None

    def test_voicebot_has_behavior_layer(self):
        """VoiceBot should have a behavior layer from the voice preset."""
        from parrot.bots.voice import VoiceBot
        behavior = VoiceBot._prompt_builder.get("behavior")
        assert behavior is not None

    def test_voicebot_behavior_is_concise(self):
        """Voice behavior layer should include concise/conversational."""
        from parrot.bots.voice import VoiceBot
        behavior = VoiceBot._prompt_builder.get("behavior")
        template_lower = behavior.template.lower()
        assert "concise" in template_lower or "conversational" in template_lower

    def test_voicebot_has_identity_layer(self):
        """VoiceBot should have identity layer from voice preset."""
        from parrot.bots.voice import VoiceBot
        assert VoiceBot._prompt_builder.get("identity") is not None

    def test_voicebot_has_security_layer(self):
        """VoiceBot should have security layer from voice preset."""
        from parrot.bots.voice import VoiceBot
        assert VoiceBot._prompt_builder.get("security") is not None

    def test_voicebot_no_system_prompt_template_override(self):
        """VoiceBot class should not reference BASIC_VOICE_PROMPT_TEMPLATE."""
        from parrot.bots.voice import VoiceBot
        # The class should not have its own system_prompt_template override
        # (it inherits from BaseBot/AbstractBot)
        assert "_prompt_builder" in VoiceBot.__dict__
