"""Tests for YAML prompt config integration in BotManager and AgentRegistry."""
import pytest
from parrot.bots.prompts.builder import PromptBuilder
from parrot.bots.prompts.layers import PromptLayer, LayerPriority, RenderPhase
from parrot.bots.prompts.domain_layers import (
    DATAFRAME_CONTEXT_LAYER,
    get_domain_layer,
)
from parrot.registry.registry import PromptConfig, AgentRegistry


class TestPromptConfig:
    """Test the PromptConfig model."""

    def test_default_preset(self):
        config = PromptConfig()
        assert config.preset == "default"
        assert config.remove == []
        assert config.add == []
        assert config.customize == {}

    def test_custom_preset(self):
        config = PromptConfig(preset="voice")
        assert config.preset == "voice"

    def test_remove_layers(self):
        config = PromptConfig(remove=["tools", "security"])
        assert config.remove == ["tools", "security"]

    def test_add_string_layers(self):
        config = PromptConfig(add=["dataframe_context", "strict_grounding"])
        assert len(config.add) == 2

    def test_add_dict_layers(self):
        config = PromptConfig(add=[{"name": "custom", "priority": 35, "template": "hello"}])
        assert len(config.add) == 1
        assert config.add[0]["name"] == "custom"

    def test_customize(self):
        config = PromptConfig(customize={
            "behavior": {"template": "<response_style>Be kind</response_style>"}
        })
        assert "behavior" in config.customize


class TestApplyPromptConfig:
    """Test AgentRegistry._apply_prompt_config."""

    def _make_mock_bot(self, preset="default"):
        """Create a minimal mock bot with a PromptBuilder."""
        from unittest.mock import MagicMock
        bot = MagicMock()
        from parrot.bots.prompts.presets import get_preset
        bot._prompt_builder = get_preset(preset)
        return bot

    def test_remove_layers(self):
        bot = self._make_mock_bot()
        assert bot._prompt_builder.get("tools") is not None
        config = PromptConfig(remove=["tools"])
        AgentRegistry._apply_prompt_config(bot, config)
        assert bot._prompt_builder.get("tools") is None

    def test_add_domain_layer_by_name(self):
        bot = self._make_mock_bot()
        assert bot._prompt_builder.get("dataframe_context") is None
        config = PromptConfig(add=["dataframe_context"])
        AgentRegistry._apply_prompt_config(bot, config)
        assert bot._prompt_builder.get("dataframe_context") is not None

    def test_add_inline_layer(self):
        bot = self._make_mock_bot()
        config = PromptConfig(add=[{
            "name": "custom_layer",
            "priority": 75,
            "template": "<custom>Hello $name</custom>",
        }])
        AgentRegistry._apply_prompt_config(bot, config)
        layer = bot._prompt_builder.get("custom_layer")
        assert layer is not None
        assert layer.priority == 75
        assert "<custom>" in layer.template

    def test_customize_layer_template(self):
        bot = self._make_mock_bot()
        original = bot._prompt_builder.get("security")
        assert original is not None
        config = PromptConfig(customize={
            "security": {"template": "<security_policy>Custom security rules</security_policy>"}
        })
        AgentRegistry._apply_prompt_config(bot, config)
        updated = bot._prompt_builder.get("security")
        assert "Custom security rules" in updated.template
        # Priority should be preserved
        assert updated.priority == original.priority

    def test_customize_nonexistent_layer_noop(self):
        bot = self._make_mock_bot()
        config = PromptConfig(customize={
            "nonexistent": {"template": "whatever"}
        })
        # Should not raise
        AgentRegistry._apply_prompt_config(bot, config)

    def test_combined_operations(self):
        bot = self._make_mock_bot()
        config = PromptConfig(
            remove=["tools"],
            add=["strict_grounding"],
            customize={
                "identity": {"template": "<agent_identity>Custom $name</agent_identity>"}
            }
        )
        AgentRegistry._apply_prompt_config(bot, config)
        assert bot._prompt_builder.get("tools") is None
        assert bot._prompt_builder.get("strict_grounding") is not None
        identity = bot._prompt_builder.get("identity")
        assert "Custom" in identity.template


class TestBotManagerApplyPromptConfig:
    """Test BotManager._apply_prompt_config (DB-loaded bots flow)."""

    def _make_mock_bot(self, preset="default"):
        from unittest.mock import MagicMock
        from parrot.bots.prompts.presets import get_preset
        bot = MagicMock()
        bot._prompt_builder = get_preset(preset)
        return bot

    def test_noop_when_config_empty(self):
        from parrot.manager.manager import BotManager
        bot = self._make_mock_bot()
        before = list(bot._prompt_builder.layer_names)
        BotManager._apply_prompt_config(bot, {})
        assert list(bot._prompt_builder.layer_names) == before

    def test_noop_when_builder_missing(self):
        from parrot.manager.manager import BotManager
        from unittest.mock import MagicMock
        bot = MagicMock()
        bot._prompt_builder = None
        BotManager._apply_prompt_config(bot, {"remove": ["tools"]})

    def test_remove_layers(self):
        from parrot.manager.manager import BotManager
        bot = self._make_mock_bot()
        assert bot._prompt_builder.get("tools") is not None
        BotManager._apply_prompt_config(bot, {"remove": ["tools", "output"]})
        assert bot._prompt_builder.get("tools") is None
        assert bot._prompt_builder.get("output") is None
        assert bot._prompt_builder.get("identity") is not None

    def test_add_domain_layer(self):
        from parrot.manager.manager import BotManager
        bot = self._make_mock_bot()
        BotManager._apply_prompt_config(bot, {"add": ["dataframe_context"]})
        assert bot._prompt_builder.get("dataframe_context") is not None

    def test_add_inline_layer(self):
        from parrot.manager.manager import BotManager
        bot = self._make_mock_bot()
        BotManager._apply_prompt_config(bot, {
            "add": [{"name": "my_layer", "priority": 55, "template": "<my>hello</my>"}]
        })
        layer = bot._prompt_builder.get("my_layer")
        assert layer is not None
        assert "<my>" in layer.template

    def test_customize_layer(self):
        from parrot.manager.manager import BotManager
        bot = self._make_mock_bot()
        BotManager._apply_prompt_config(bot, {
            "customize": {
                "behavior": {"template": "<response_style>Be empathetic.</response_style>"}
            }
        })
        behavior = bot._prompt_builder.get("behavior")
        assert "empathetic" in behavior.template

    def test_rag_preset_via_mock_bot(self):
        from parrot.manager.manager import BotManager
        bot = self._make_mock_bot(preset="rag")
        assert bot._prompt_builder.get("rag_grounding") is not None
        assert bot._prompt_builder.get("knowledge_scope") is not None
        assert bot._prompt_builder.get("tools") is None
        BotManager._apply_prompt_config(bot, {"customize": {
            "rag_grounding": {"template": "<rag_policy>Custom rag rules</rag_policy>"}
        }})
        assert "Custom rag rules" in bot._prompt_builder.get("rag_grounding").template


class TestLegacyPathUnchanged:
    """YAML agents without prompt: section should use legacy path."""

    def test_no_prompt_config_in_botconfig(self):
        """BotConfig without prompt field should have prompt=None."""
        from parrot.registry.registry import BotConfig
        config = BotConfig(
            name="test",
            class_name="BasicBot",
            module="parrot.bots.basic",
        )
        assert config.prompt is None

    def test_prompt_config_from_yaml_dict(self):
        """PromptConfig should parse from a dict (simulating YAML)."""
        config = PromptConfig(**{
            "preset": "voice",
            "remove": ["tools"],
            "add": ["strict_grounding"],
        })
        assert config.preset == "voice"
        assert config.remove == ["tools"]
        assert "strict_grounding" in config.add
