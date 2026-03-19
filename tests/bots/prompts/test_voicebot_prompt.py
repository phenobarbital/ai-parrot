"""Tests for VoiceBot prompt migration to composable layers.

Since VoiceBot has complex dependencies (GeminiLiveClient, A2A, etc.),
we test the prompt layer integration by inspecting the source and
verifying the PromptBuilder.voice() preset directly.
"""
import ast
import pytest
from pathlib import Path
from parrot.bots.prompts.builder import PromptBuilder


VOICE_BOT_SOURCE = Path(__file__).resolve().parents[3] / "parrot" / "bots" / "voice.py"


class TestVoiceBotUsesVoicePreset:

    def test_source_has_prompt_builder_assignment(self):
        """VoiceBot source should assign _prompt_builder = PromptBuilder.voice()."""
        source = VOICE_BOT_SOURCE.read_text()
        assert "_prompt_builder = PromptBuilder.voice()" in source

    def test_source_does_not_use_basic_voice_template(self):
        """VoiceBot class should not reference BASIC_VOICE_PROMPT_TEMPLATE."""
        source = VOICE_BOT_SOURCE.read_text()
        # Parse the AST to find the VoiceBot class
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == "VoiceBot":
                class_source = ast.get_source_segment(source, node)
                assert "BASIC_VOICE_PROMPT_TEMPLATE" not in class_source

    def test_source_imports_prompt_builder(self):
        """VoiceBot module should import PromptBuilder."""
        source = VOICE_BOT_SOURCE.read_text()
        assert "from .prompts.builder import PromptBuilder" in source

    def test_voice_preset_has_behavior_layer(self):
        """PromptBuilder.voice() should include a behavior layer."""
        builder = PromptBuilder.voice()
        behavior = builder.get("behavior")
        assert behavior is not None

    def test_voice_preset_behavior_is_concise(self):
        """Voice behavior layer should include concise/conversational."""
        builder = PromptBuilder.voice()
        behavior = builder.get("behavior")
        template_lower = behavior.template.lower()
        assert "concise" in template_lower or "conversational" in template_lower

    def test_voice_preset_has_identity(self):
        """Voice preset should have identity layer."""
        builder = PromptBuilder.voice()
        assert builder.get("identity") is not None

    def test_voice_preset_has_security(self):
        """Voice preset should have security layer."""
        builder = PromptBuilder.voice()
        assert builder.get("security") is not None

    def test_voice_preset_has_response_style_tag(self):
        """Voice behavior should use <response_style> XML tag."""
        builder = PromptBuilder.voice()
        behavior = builder.get("behavior")
        assert "<response_style>" in behavior.template
