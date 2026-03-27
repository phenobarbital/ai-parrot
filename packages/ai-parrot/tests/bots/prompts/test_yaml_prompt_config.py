"""Integration tests for YAML prompt config flow.

Tests the end-to-end path: YAML dict → PromptConfig → PromptBuilder
via both BotManager._build_prompt_builder and AgentRegistry._apply_prompt_config.
"""
import pytest
from parrot.bots.prompts.builder import PromptBuilder
from parrot.bots.prompts.layers import PromptLayer, LayerPriority, RenderPhase
from parrot.bots.prompts.domain_layers import (
    DATAFRAME_CONTEXT_LAYER,
    STRICT_GROUNDING_LAYER,
    get_domain_layer,
)
from parrot.registry.registry import PromptConfig, AgentRegistry


CONFIGURE_CTX = {
    "name": "YAMLBot",
    "role": "YAML-configured assistant",
    "goal": "demonstrate YAML config",
    "capabilities": "- YAML parsing",
    "backstory": "",
    "pre_instructions_content": "",
    "extra_security_rules": "",
    "has_tools": True,
    "extra_tool_instructions": "",
    "rationale": "Be precise.",
}

REQUEST_CTX = {
    "knowledge_content": "YAML docs",
    "user_context": "admin user",
    "chat_history": "Human: hi",
    "output_instructions": "",
}


class TestYAMLPresetSelection:
    """YAML prompt.preset selects the right base builder."""

    def test_default_preset_has_all_layers(self):
        from parrot.manager.manager import BotManager
        builder = BotManager._build_prompt_builder({"preset": "default"})
        for name in ["identity", "security", "knowledge", "user_session",
                      "tools", "output", "behavior"]:
            assert builder.get(name) is not None, f"Missing layer: {name}"

    def test_minimal_preset_omits_tools(self):
        from parrot.manager.manager import BotManager
        builder = BotManager._build_prompt_builder({"preset": "minimal"})
        assert builder.get("tools") is None
        assert builder.get("output") is None

    def test_voice_preset_has_voice_behavior(self):
        from parrot.manager.manager import BotManager
        builder = BotManager._build_prompt_builder({"preset": "voice"})
        behavior = builder.get("behavior")
        assert "concise" in behavior.template.lower()

    def test_agent_preset_has_grounding(self):
        from parrot.manager.manager import BotManager
        builder = BotManager._build_prompt_builder({"preset": "agent"})
        assert builder.get("strict_grounding") is not None


class TestYAMLRemoveOperation:
    """YAML prompt.remove removes layers from the preset."""

    def test_remove_single_layer(self):
        from parrot.manager.manager import BotManager
        builder = BotManager._build_prompt_builder({
            "preset": "default",
            "remove": ["tools"],
        })
        assert builder.get("tools") is None
        assert builder.get("identity") is not None

    def test_remove_multiple_layers(self):
        from parrot.manager.manager import BotManager
        builder = BotManager._build_prompt_builder({
            "preset": "default",
            "remove": ["tools", "output", "behavior"],
        })
        assert builder.get("tools") is None
        assert builder.get("output") is None
        assert builder.get("behavior") is None

    def test_remove_nonexistent_is_noop(self):
        from parrot.manager.manager import BotManager
        builder = BotManager._build_prompt_builder({
            "preset": "default",
            "remove": ["nonexistent_layer"],
        })
        assert builder.get("identity") is not None


class TestYAMLAddOperation:
    """YAML prompt.add adds domain or inline layers."""

    def test_add_domain_layer_by_name(self):
        from parrot.manager.manager import BotManager
        builder = BotManager._build_prompt_builder({
            "preset": "default",
            "add": ["dataframe_context"],
        })
        assert builder.get("dataframe_context") is not None

    def test_add_multiple_domain_layers(self):
        from parrot.manager.manager import BotManager
        builder = BotManager._build_prompt_builder({
            "preset": "default",
            "add": ["dataframe_context", "strict_grounding"],
        })
        assert builder.get("dataframe_context") is not None
        assert builder.get("strict_grounding") is not None

    def test_add_inline_layer_dict(self):
        from parrot.manager.manager import BotManager
        builder = BotManager._build_prompt_builder({
            "preset": "default",
            "add": [{
                "name": "custom_greeting",
                "priority": 75,
                "template": "<greeting>Hello $name, welcome!</greeting>",
            }],
        })
        layer = builder.get("custom_greeting")
        assert layer is not None
        assert layer.priority == 75
        assert "<greeting>" in layer.template

    def test_add_mixed_domain_and_inline(self):
        from parrot.manager.manager import BotManager
        builder = BotManager._build_prompt_builder({
            "preset": "default",
            "add": [
                "strict_grounding",
                {"name": "custom", "priority": 90, "template": "<c>hi</c>"},
            ],
        })
        assert builder.get("strict_grounding") is not None
        assert builder.get("custom") is not None


class TestYAMLCustomizeOperation:
    """YAML prompt.customize modifies existing layer templates."""

    def test_customize_behavior_template(self):
        from parrot.manager.manager import BotManager
        builder = BotManager._build_prompt_builder({
            "preset": "default",
            "customize": {
                "behavior": {
                    "template": "<response_style>Be extremely formal and detailed.</response_style>"
                }
            },
        })
        behavior = builder.get("behavior")
        assert "extremely formal" in behavior.template

    def test_customize_preserves_priority(self):
        from parrot.manager.manager import BotManager
        original = BotManager._build_prompt_builder({"preset": "default"})
        original_priority = original.get("security").priority

        customized = BotManager._build_prompt_builder({
            "preset": "default",
            "customize": {
                "security": {"template": "<security_policy>Custom rules</security_policy>"}
            },
        })
        assert customized.get("security").priority == original_priority

    def test_customize_nonexistent_layer_is_noop(self):
        from parrot.manager.manager import BotManager
        builder = BotManager._build_prompt_builder({
            "preset": "default",
            "customize": {"nonexistent": {"template": "whatever"}},
        })
        assert builder.get("nonexistent") is None


class TestYAMLCombinedOperations:
    """Test remove + add + customize in a single config."""

    def test_full_yaml_config_flow(self):
        from parrot.manager.manager import BotManager
        builder = BotManager._build_prompt_builder({
            "preset": "default",
            "remove": ["tools"],
            "add": ["strict_grounding"],
            "customize": {
                "identity": {
                    "template": "<agent_identity>Custom $name agent</agent_identity>"
                }
            },
        })
        # tools removed
        assert builder.get("tools") is None
        # strict_grounding added
        assert builder.get("strict_grounding") is not None
        # identity customized
        assert "Custom" in builder.get("identity").template
        # other layers preserved
        assert builder.get("security") is not None
        assert builder.get("knowledge") is not None

    def test_yaml_config_renders_correctly(self):
        """End-to-end: config → builder → configure → build."""
        from parrot.manager.manager import BotManager
        builder = BotManager._build_prompt_builder({
            "preset": "default",
            "remove": ["tools", "output"],
            "add": ["strict_grounding"],
        })
        builder.configure(CONFIGURE_CTX)
        prompt = builder.build(REQUEST_CTX)

        assert "YAMLBot" in prompt
        assert "<security_policy>" in prompt
        assert "<tool_policy>" not in prompt
        assert "<output_format>" not in prompt
        assert "<grounding_policy>" in prompt
        assert "YAML docs" in prompt


class TestApplyPromptConfigOnBot:
    """Test AgentRegistry._apply_prompt_config modifies a bot's builder."""

    def _make_bot(self, preset="default"):
        from unittest.mock import MagicMock
        from parrot.bots.prompts.presets import get_preset
        bot = MagicMock()
        bot._prompt_builder = get_preset(preset)
        return bot

    def test_apply_removes_layers(self):
        bot = self._make_bot()
        config = PromptConfig(remove=["tools", "behavior"])
        AgentRegistry._apply_prompt_config(bot, config)
        assert bot._prompt_builder.get("tools") is None
        assert bot._prompt_builder.get("behavior") is None

    def test_apply_adds_domain_layers(self):
        bot = self._make_bot()
        config = PromptConfig(add=["strict_grounding", "dataframe_context"])
        AgentRegistry._apply_prompt_config(bot, config)
        assert bot._prompt_builder.get("strict_grounding") is not None
        assert bot._prompt_builder.get("dataframe_context") is not None

    def test_apply_customizes_template(self):
        bot = self._make_bot()
        config = PromptConfig(customize={
            "security": {"template": "<security_policy>No PII sharing</security_policy>"}
        })
        AgentRegistry._apply_prompt_config(bot, config)
        assert "No PII sharing" in bot._prompt_builder.get("security").template

    def test_apply_combined_on_voice_preset(self):
        """Apply config on top of voice preset."""
        bot = self._make_bot("voice")
        config = PromptConfig(
            remove=["tools"],
            add=["company_context"],
            customize={
                "behavior": {"template": "<response_style>Be warm and friendly.</response_style>"}
            },
        )
        AgentRegistry._apply_prompt_config(bot, config)
        assert bot._prompt_builder.get("tools") is None
        assert bot._prompt_builder.get("company_context") is not None
        assert "warm and friendly" in bot._prompt_builder.get("behavior").template
