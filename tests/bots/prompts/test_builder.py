"""Unit tests for PromptBuilder class."""
import pytest
from parrot.bots.prompts.builder import PromptBuilder
from parrot.bots.prompts.layers import (
    PromptLayer, LayerPriority, RenderPhase,
    IDENTITY_LAYER, SECURITY_LAYER, KNOWLEDGE_LAYER,
    USER_SESSION_LAYER, TOOLS_LAYER, OUTPUT_LAYER,
    BEHAVIOR_LAYER, PRE_INSTRUCTIONS_LAYER,
)


# ── Shared test contexts ───────────────────────────────────────

CONFIGURE_CTX = {
    "name": "TestBot",
    "role": "helpful assistant",
    "goal": "help users",
    "capabilities": "- Can search\n- Can analyze",
    "backstory": "Expert in AI",
    "pre_instructions_content": "",
    "extra_security_rules": "",
    "has_tools": False,
    "extra_tool_instructions": "",
    "rationale": "",
}

REQUEST_CTX = {
    "knowledge_content": "Some knowledge facts",
    "user_context": "User prefers JSON",
    "chat_history": "Human: hello\nAssistant: hi",
    "output_instructions": "",
}

FULL_CTX = {**CONFIGURE_CTX, **REQUEST_CTX}


# ── Factory method tests ───────────────────────────────────────


class TestPromptBuilderFactories:

    def test_default_has_all_builtin_layers(self):
        builder = PromptBuilder.default()
        assert builder.get("identity") is not None
        assert builder.get("pre_instructions") is not None
        assert builder.get("security") is not None
        assert builder.get("knowledge") is not None
        assert builder.get("user_session") is not None
        assert builder.get("tools") is not None
        assert builder.get("output") is not None
        assert builder.get("behavior") is not None

    def test_default_has_eight_layers(self):
        builder = PromptBuilder.default()
        assert len(builder.layer_names) == 8

    def test_minimal_has_three_layers(self):
        builder = PromptBuilder.minimal()
        assert builder.get("identity") is not None
        assert builder.get("security") is not None
        assert builder.get("user_session") is not None
        assert builder.get("tools") is None
        assert builder.get("knowledge") is None
        assert builder.get("behavior") is None

    def test_voice_has_voice_behavior(self):
        builder = PromptBuilder.voice()
        behavior = builder.get("behavior")
        assert behavior is not None
        assert "concise" in behavior.template.lower()
        assert "conversational" in behavior.template.lower()

    def test_voice_has_standard_layers(self):
        builder = PromptBuilder.voice()
        assert builder.get("identity") is not None
        assert builder.get("security") is not None
        assert builder.get("user_session") is not None
        assert builder.get("tools") is not None

    def test_agent_has_strict_grounding(self):
        builder = PromptBuilder.agent()
        grounding = builder.get("strict_grounding")
        assert grounding is not None
        assert "<grounding_policy>" in grounding.template

    def test_agent_extends_default(self):
        builder = PromptBuilder.agent()
        assert builder.get("identity") is not None
        assert builder.get("security") is not None
        assert builder.get("tools") is not None


# ── Mutation API tests ─────────────────────────────────────────


class TestPromptBuilderMutations:

    def test_add_new_layer(self):
        builder = PromptBuilder.default()
        custom = PromptLayer(
            name="custom",
            priority=LayerPriority.CUSTOM,
            template="<custom>$val</custom>",
        )
        result = builder.add(custom)
        assert result is builder  # returns self
        assert builder.get("custom") is custom

    def test_add_replaces_existing_layer(self):
        builder = PromptBuilder.default()
        new_behavior = PromptLayer(
            name="behavior",
            priority=LayerPriority.BEHAVIOR,
            template="<response_style>New style</response_style>",
        )
        builder.add(new_behavior)
        assert builder.get("behavior") is new_behavior

    def test_remove_existing_layer(self):
        builder = PromptBuilder.default()
        result = builder.remove("tools")
        assert result is builder  # returns self
        assert builder.get("tools") is None

    def test_remove_nonexistent_is_noop(self):
        builder = PromptBuilder.default()
        count_before = len(builder.layer_names)
        builder.remove("nonexistent")
        assert len(builder.layer_names) == count_before

    def test_replace_existing_layer(self):
        builder = PromptBuilder.default()
        new_security = PromptLayer(
            name="security",
            priority=LayerPriority.SECURITY,
            template="<security_policy>Custom rules</security_policy>",
        )
        result = builder.replace("security", new_security)
        assert result is builder
        assert builder.get("security") is new_security

    def test_replace_nonexistent_raises_keyerror(self):
        builder = PromptBuilder.default()
        custom = PromptLayer(
            name="custom",
            priority=LayerPriority.CUSTOM,
            template="<custom></custom>",
        )
        with pytest.raises(KeyError, match="Layer 'custom' not found"):
            builder.replace("custom", custom)

    def test_get_returns_none_for_missing(self):
        builder = PromptBuilder.default()
        assert builder.get("nonexistent") is None

    def test_clone_produces_independent_copy(self):
        original = PromptBuilder.default()
        cloned = original.clone()
        cloned.remove("tools")
        assert original.get("tools") is not None
        assert cloned.get("tools") is None

    def test_clone_preserves_configured_state(self):
        builder = PromptBuilder.default()
        builder.configure(CONFIGURE_CTX)
        cloned = builder.clone()
        assert cloned.is_configured is True

    def test_clone_mutation_doesnt_affect_original(self):
        original = PromptBuilder.default()
        cloned = original.clone()
        custom = PromptLayer(
            name="custom",
            priority=LayerPriority.CUSTOM,
            template="<custom>test</custom>",
        )
        cloned.add(custom)
        assert original.get("custom") is None


# ── Two-phase rendering tests ──────────────────────────────────


class TestTwoPhaseRendering:

    def test_configure_sets_configured_flag(self):
        builder = PromptBuilder.default()
        assert builder.is_configured is False
        builder.configure(CONFIGURE_CTX)
        assert builder.is_configured is True

    def test_configure_resolves_static_vars(self):
        builder = PromptBuilder.default()
        builder.configure(CONFIGURE_CTX)
        # Identity layer should now have name baked in
        identity = builder.get("identity")
        assert "TestBot" in identity.template
        assert "helpful assistant" in identity.template

    def test_configure_preserves_request_vars(self):
        builder = PromptBuilder.default()
        builder.configure(CONFIGURE_CTX)
        # Knowledge layer is REQUEST phase — should be unchanged
        knowledge = builder.get("knowledge")
        assert "$knowledge_content" in knowledge.template

    def test_build_after_configure_resolves_dynamic_vars(self):
        builder = PromptBuilder.default()
        builder.configure(CONFIGURE_CTX)
        prompt = builder.build(REQUEST_CTX)
        assert "TestBot" in prompt  # from configure
        assert "Some knowledge facts" in prompt  # from build
        assert "User prefers JSON" in prompt  # from build

    def test_build_produces_priority_ordered_output(self):
        builder = PromptBuilder.default()
        builder.configure({**CONFIGURE_CTX, "has_tools": True, "rationale": "Be helpful"})
        prompt = builder.build(REQUEST_CTX)
        # Identity should come before security, security before knowledge, etc.
        # Use closing tags to avoid matching mentions within other layers
        # (e.g. security layer mentions "<user_session>" in its text)
        identity_pos = prompt.index("</agent_identity>")
        security_pos = prompt.index("</security_policy>")
        knowledge_pos = prompt.index("</knowledge_context>")
        session_pos = prompt.index("</user_session>")
        tools_pos = prompt.index("</tool_policy>")
        behavior_pos = prompt.index("</response_style>")
        assert identity_pos < security_pos < knowledge_pos < session_pos
        assert session_pos < tools_pos < behavior_pos

    def test_conditional_layers_omitted_when_false(self):
        builder = PromptBuilder.default()
        # has_tools=False, rationale="" -> tools and behavior layers skipped
        builder.configure(CONFIGURE_CTX)
        prompt = builder.build({"knowledge_content": "", "user_context": "",
                                "chat_history": "", "output_instructions": ""})
        assert "<tool_policy>" not in prompt
        assert "<response_style>" not in prompt
        assert "<knowledge_context>" not in prompt

    def test_conditional_layers_included_when_true(self):
        builder = PromptBuilder.default()
        builder.configure({**CONFIGURE_CTX, "has_tools": True, "rationale": "Be concise"})
        prompt = builder.build({"knowledge_content": "facts", "user_context": "",
                                "chat_history": "", "output_instructions": "Use JSON"})
        assert "<tool_policy>" in prompt
        assert "<response_style>" in prompt
        assert "<knowledge_context>" in prompt
        assert "<output_format>" in prompt


# ── Single-phase fallback tests ────────────────────────────────


class TestSinglePhaseFallback:

    def test_build_without_configure_renders_all(self):
        builder = PromptBuilder.default()
        prompt = builder.build(FULL_CTX)
        assert "<agent_identity>" in prompt
        assert "TestBot" in prompt
        assert "<security_policy>" in prompt
        assert "<user_session>" in prompt

    def test_build_without_configure_resolves_all_vars(self):
        builder = PromptBuilder.default()
        prompt = builder.build(FULL_CTX)
        assert "TestBot" in prompt
        assert "helpful assistant" in prompt
        assert "Some knowledge facts" in prompt


# ── Edge cases ─────────────────────────────────────────────────


class TestEdgeCases:

    def test_empty_builder(self):
        builder = PromptBuilder()
        assert builder.build({}) == ""

    def test_builder_with_all_conditions_false(self):
        cond_layer = PromptLayer(
            name="cond",
            priority=LayerPriority.CUSTOM,
            template="<cond>test</cond>",
            condition=lambda ctx: False,
        )
        builder = PromptBuilder([cond_layer])
        assert builder.build({}) == ""

    def test_builder_with_single_layer(self):
        layer = PromptLayer(
            name="only",
            priority=LayerPriority.IDENTITY,
            template="<only>Hello $name</only>",
        )
        builder = PromptBuilder([layer])
        result = builder.build({"name": "World"})
        assert result == "<only>Hello World</only>"

    def test_multiple_builds_with_different_contexts(self):
        builder = PromptBuilder.default()
        builder.configure(CONFIGURE_CTX)
        prompt1 = builder.build({**REQUEST_CTX, "knowledge_content": "facts1"})
        prompt2 = builder.build({**REQUEST_CTX, "knowledge_content": "facts2"})
        assert "facts1" in prompt1
        assert "facts2" in prompt2
        assert "facts1" not in prompt2

    def test_parts_joined_with_double_newline(self):
        layer1 = PromptLayer(name="a", priority=10, template="<a>first</a>")
        layer2 = PromptLayer(name="b", priority=20, template="<b>second</b>")
        builder = PromptBuilder([layer1, layer2])
        result = builder.build({})
        assert result == "<a>first</a>\n\n<b>second</b>"

    def test_empty_rendered_layers_skipped(self):
        """Layers that render to empty/whitespace should be omitted."""
        empty_layer = PromptLayer(name="empty", priority=10, template="   ")
        content_layer = PromptLayer(name="content", priority=20, template="<a>hello</a>")
        builder = PromptBuilder([empty_layer, content_layer])
        result = builder.build({})
        assert result == "<a>hello</a>"

    def test_configure_idempotent(self):
        """Calling configure twice should not break the builder."""
        builder = PromptBuilder.default()
        builder.configure(CONFIGURE_CTX)
        prompt1 = builder.build(REQUEST_CTX)
        builder.configure(CONFIGURE_CTX)
        prompt2 = builder.build(REQUEST_CTX)
        assert "TestBot" in prompt1
        assert "TestBot" in prompt2

    def test_build_skips_layers_with_false_condition_after_configure(self):
        """Conditional CONFIGURE layers that evaluated false remain unchanged."""
        builder = PromptBuilder.default()
        # has_tools=False → tools layer condition is false during configure
        builder.configure({**CONFIGURE_CTX, "has_tools": False})
        prompt = builder.build(REQUEST_CTX)
        assert "<tool_policy>" not in prompt

    def test_partial_render_overlapping_var_names(self):
        """Variables present in both CONFIGURE and REQUEST contexts."""
        layer = PromptLayer(
            name="overlap",
            priority=LayerPriority.IDENTITY,
            phase=RenderPhase.CONFIGURE,
            template="<test>$name and $user_context</test>",
        )
        builder = PromptBuilder([layer])
        # configure resolves $name; $user_context survives as placeholder
        builder.configure({"name": "Bot"})
        prompt = builder.build({"user_context": "user info"})
        assert "Bot" in prompt
        assert "user info" in prompt

    def test_builder_layer_names_after_mutations(self):
        builder = PromptBuilder.default()
        original_count = len(builder.layer_names)
        custom = PromptLayer(name="custom", priority=90, template="<c>x</c>")
        builder.add(custom)
        assert len(builder.layer_names) == original_count + 1
        builder.remove("custom")
        assert len(builder.layer_names) == original_count

    def test_builder_with_all_conditions_false_after_configure(self):
        """All layers have false conditions → empty prompt."""
        layer1 = PromptLayer(
            name="a", priority=10, template="<a>x</a>",
            phase=RenderPhase.CONFIGURE,
            condition=lambda ctx: False,
        )
        layer2 = PromptLayer(
            name="b", priority=20, template="<b>y</b>",
            condition=lambda ctx: False,
        )
        builder = PromptBuilder([layer1, layer2])
        builder.configure({})
        assert builder.build({}) == ""

    def test_method_chaining(self):
        """add/remove/replace return self for chaining."""
        builder = PromptBuilder.default()
        custom = PromptLayer(name="extra", priority=90, template="<e>x</e>")
        result = builder.remove("tools").add(custom)
        assert result is builder
        assert builder.get("tools") is None
        assert builder.get("extra") is not None

    def test_clone_after_add_does_not_share(self):
        """Cloned builder should not share mutable state with original after add."""
        original = PromptBuilder.default()
        cloned = original.clone()
        new_layer = PromptLayer(name="new", priority=90, template="<n>x</n>")
        original.add(new_layer)
        assert cloned.get("new") is None

    def test_build_with_large_context(self):
        """Builder should handle large context values without issues."""
        builder = PromptBuilder.default()
        large_knowledge = "fact " * 10000
        builder.configure(CONFIGURE_CTX)
        prompt = builder.build({
            "knowledge_content": large_knowledge,
            "user_context": "",
            "chat_history": "",
            "output_instructions": "",
        })
        assert "fact " in prompt
        assert "<knowledge_context>" in prompt
