"""Unit tests for presets registry."""
import pytest
from parrot.bots.prompts.presets import register_preset, get_preset, list_presets
from parrot.bots.prompts.builder import PromptBuilder


class TestGetPreset:

    def test_get_default_preset(self):
        builder = get_preset("default")
        assert isinstance(builder, PromptBuilder)
        assert builder.get("identity") is not None
        assert builder.get("security") is not None
        assert builder.get("tools") is not None

    def test_get_minimal_preset(self):
        builder = get_preset("minimal")
        assert builder.get("identity") is not None
        assert builder.get("tools") is None

    def test_get_voice_preset(self):
        builder = get_preset("voice")
        behavior = builder.get("behavior")
        assert behavior is not None
        assert "concise" in behavior.template.lower()

    def test_get_agent_preset(self):
        builder = get_preset("agent")
        assert builder.get("strict_grounding") is not None

    def test_get_rag_preset_has_grounding_and_scope(self):
        builder = get_preset("rag")
        assert builder.get("knowledge_scope") is not None
        assert builder.get("rag_grounding") is not None
        assert builder.get("knowledge") is not None

    def test_get_rag_preset_drops_tools_layer(self):
        builder = get_preset("rag")
        assert builder.get("tools") is None

    def test_rag_preset_projects_capabilities_into_scope(self):
        builder = get_preset("rag")
        builder.configure({
            "name": "att_concierge",
            "role": "AT&T support concierge",
            "goal": "Answer customer questions from the support KB.",
            "backstory": "Friendly residential customer-service persona.",
            "rationale": "",
            "capabilities": "Knows AT&T fiber and wireless plans for US residential customers.",
            "pre_instructions_content": "",
            "extra_security_rules": "",
            "extra_rag_rules": "",
            "has_tools": False,
        })
        prompt = builder.build({
            "knowledge_content": "Plan A: $50/mo.",
            "user_context": "",
            "chat_history": "",
            "output_instructions": "",
        })
        # capabilities is the scope source of truth, projected into <knowledge_scope>
        assert "<knowledge_scope>" in prompt
        assert "AT&T fiber and wireless plans" in prompt
        # backstory stays in identity (persona), not in scope
        assert "Friendly residential" in prompt
        assert "<rag_policy>" in prompt
        assert "<tool_policy>" not in prompt

    def test_get_unknown_preset_raises(self):
        with pytest.raises(KeyError, match="Unknown preset"):
            get_preset("nonexistent")

    def test_error_message_lists_available(self):
        with pytest.raises(KeyError, match="default"):
            get_preset("nonexistent")


class TestPresetIndependence:

    def test_returns_independent_instances(self):
        b1 = get_preset("default")
        b2 = get_preset("default")
        b1.remove("tools")
        assert b2.get("tools") is not None

    def test_each_call_returns_new_builder(self):
        b1 = get_preset("default")
        b2 = get_preset("default")
        assert b1 is not b2


class TestRegisterPreset:

    def test_register_custom_preset(self):
        register_preset("custom_test", PromptBuilder.minimal)
        builder = get_preset("custom_test")
        assert builder.get("identity") is not None
        assert builder.get("tools") is None

    def test_register_overwrites_existing(self):
        register_preset("override_test", PromptBuilder.default)
        b1 = get_preset("override_test")
        assert b1.get("tools") is not None
        register_preset("override_test", PromptBuilder.minimal)
        b2 = get_preset("override_test")
        assert b2.get("tools") is None


class TestListPresets:

    def test_lists_builtin_presets(self):
        names = list_presets()
        assert "default" in names
        assert "minimal" in names
        assert "voice" in names
        assert "agent" in names
        assert "rag" in names

    def test_lists_at_least_five(self):
        assert len(list_presets()) >= 5

    def test_registered_preset_appears_in_list(self):
        register_preset("list_test_preset", PromptBuilder.minimal)
        assert "list_test_preset" in list_presets()
