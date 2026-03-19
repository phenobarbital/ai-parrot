"""Unit tests for PromptLayer dataclass and built-in layers."""
import pytest
from parrot.bots.prompts.layers import (
    PromptLayer,
    LayerPriority,
    RenderPhase,
    IDENTITY_LAYER,
    PRE_INSTRUCTIONS_LAYER,
    SECURITY_LAYER,
    KNOWLEDGE_LAYER,
    USER_SESSION_LAYER,
    TOOLS_LAYER,
    OUTPUT_LAYER,
    BEHAVIOR_LAYER,
)


# ── LayerPriority tests ────────────────────────────────────────


class TestLayerPriority:

    def test_priority_values(self):
        assert LayerPriority.IDENTITY == 10
        assert LayerPriority.PRE_INSTRUCTIONS == 15
        assert LayerPriority.SECURITY == 20
        assert LayerPriority.KNOWLEDGE == 30
        assert LayerPriority.USER_SESSION == 40
        assert LayerPriority.TOOLS == 50
        assert LayerPriority.OUTPUT == 60
        assert LayerPriority.BEHAVIOR == 70
        assert LayerPriority.CUSTOM == 80

    def test_priority_ordering(self):
        assert LayerPriority.IDENTITY < LayerPriority.PRE_INSTRUCTIONS
        assert LayerPriority.PRE_INSTRUCTIONS < LayerPriority.SECURITY
        assert LayerPriority.SECURITY < LayerPriority.KNOWLEDGE
        assert LayerPriority.KNOWLEDGE < LayerPriority.USER_SESSION
        assert LayerPriority.USER_SESSION < LayerPriority.TOOLS
        assert LayerPriority.TOOLS < LayerPriority.OUTPUT
        assert LayerPriority.OUTPUT < LayerPriority.BEHAVIOR
        assert LayerPriority.BEHAVIOR < LayerPriority.CUSTOM

    def test_all_nine_levels(self):
        assert len(LayerPriority) == 9


# ── RenderPhase tests ──────────────────────────────────────────


class TestRenderPhase:

    def test_configure_value(self):
        assert RenderPhase.CONFIGURE == "configure"

    def test_request_value(self):
        assert RenderPhase.REQUEST == "request"

    def test_two_phases(self):
        assert len(RenderPhase) == 2


# ── PromptLayer.render() tests ─────────────────────────────────


class TestPromptLayerRender:

    def test_render_with_context(self):
        layer = PromptLayer(
            name="test",
            priority=LayerPriority.CUSTOM,
            template="<test>Hello $name, you are $role.</test>",
        )
        result = layer.render({"name": "Bot", "role": "helper"})
        assert result == "<test>Hello Bot, you are helper.</test>"

    def test_render_safe_substitute_leaves_unknown_vars(self):
        layer = PromptLayer(
            name="test",
            priority=LayerPriority.CUSTOM,
            template="<test>$known and $unknown</test>",
        )
        result = layer.render({"known": "value"})
        assert "value" in result
        assert "$unknown" in result

    def test_render_condition_true(self):
        layer = PromptLayer(
            name="test",
            priority=LayerPriority.CUSTOM,
            template="<test>$val</test>",
            condition=lambda ctx: ctx.get("active", False),
        )
        result = layer.render({"active": True, "val": "hello"})
        assert result is not None
        assert "hello" in result

    def test_render_condition_false_returns_none(self):
        layer = PromptLayer(
            name="test",
            priority=LayerPriority.CUSTOM,
            template="<test>$val</test>",
            condition=lambda ctx: ctx.get("active", False),
        )
        result = layer.render({"active": False, "val": "hello"})
        assert result is None

    def test_render_no_condition_always_renders(self):
        layer = PromptLayer(
            name="test",
            priority=LayerPriority.CUSTOM,
            template="<test>static</test>",
        )
        result = layer.render({})
        assert result == "<test>static</test>"

    def test_render_empty_context(self):
        layer = PromptLayer(
            name="test",
            priority=LayerPriority.CUSTOM,
            template="<test>$var</test>",
        )
        result = layer.render({})
        assert "$var" in result


# ── PromptLayer.partial_render() tests ─────────────────────────


class TestPromptLayerPartialRender:

    def test_partial_render_resolves_known_vars(self):
        layer = PromptLayer(
            name="test",
            priority=LayerPriority.IDENTITY,
            phase=RenderPhase.CONFIGURE,
            template="<test>$name is $role with $dynamic_var</test>",
        )
        new_layer = layer.partial_render({"name": "Bot", "role": "helper"})
        assert "Bot" in new_layer.template
        assert "helper" in new_layer.template
        assert "$dynamic_var" in new_layer.template

    def test_partial_render_changes_phase_to_request(self):
        layer = PromptLayer(
            name="test",
            priority=LayerPriority.IDENTITY,
            phase=RenderPhase.CONFIGURE,
            template="<test>$name</test>",
        )
        new_layer = layer.partial_render({"name": "Bot"})
        assert new_layer.phase == RenderPhase.REQUEST

    def test_partial_render_preserves_name_and_priority(self):
        layer = PromptLayer(
            name="my_layer",
            priority=42,
            phase=RenderPhase.CONFIGURE,
            template="<test>$x</test>",
        )
        new_layer = layer.partial_render({"x": "val"})
        assert new_layer.name == "my_layer"
        assert new_layer.priority == 42

    def test_partial_render_clears_required_vars(self):
        layer = PromptLayer(
            name="test",
            priority=LayerPriority.IDENTITY,
            phase=RenderPhase.CONFIGURE,
            template="<test>$name</test>",
            required_vars=frozenset({"name"}),
        )
        new_layer = layer.partial_render({"name": "Bot"})
        assert new_layer.required_vars == frozenset()

    def test_partial_render_clears_condition_after_success(self):
        cond = lambda ctx: True
        layer = PromptLayer(
            name="test",
            priority=LayerPriority.IDENTITY,
            phase=RenderPhase.CONFIGURE,
            template="<test>$name</test>",
            condition=cond,
        )
        new_layer = layer.partial_render({"name": "Bot"})
        # Condition is cleared after successful partial_render so that
        # build() doesn't re-evaluate against REQUEST-only context
        assert new_layer.condition is None

    def test_partial_render_with_false_condition_returns_self(self):
        layer = PromptLayer(
            name="test",
            priority=LayerPriority.IDENTITY,
            phase=RenderPhase.CONFIGURE,
            template="<test>$name</test>",
            condition=lambda ctx: False,
        )
        new_layer = layer.partial_render({"name": "Bot"})
        assert new_layer is layer  # returns self unchanged


# ── PromptLayer immutability ───────────────────────────────────


class TestPromptLayerImmutability:

    def test_frozen_dataclass(self):
        layer = PromptLayer(
            name="test",
            priority=LayerPriority.CUSTOM,
            template="<test></test>",
        )
        with pytest.raises(AttributeError):
            layer.name = "changed"


# ── Built-in layer tests ──────────────────────────────────────


class TestIdentityLayer:

    def test_renders_with_identity_fields(self):
        ctx = {
            "name": "TestBot",
            "role": "assistant",
            "goal": "help users",
            "capabilities": "- Can search",
            "backstory": "Expert in AI",
        }
        result = IDENTITY_LAYER.render(ctx)
        assert "<agent_identity>" in result
        assert "</agent_identity>" in result
        assert "TestBot" in result
        assert "assistant" in result
        assert "help users" in result

    def test_phase_is_configure(self):
        assert IDENTITY_LAYER.phase == RenderPhase.CONFIGURE

    def test_priority_is_identity(self):
        assert IDENTITY_LAYER.priority == LayerPriority.IDENTITY

    def test_no_condition(self):
        assert IDENTITY_LAYER.condition is None

    def test_required_vars(self):
        assert "name" in IDENTITY_LAYER.required_vars
        assert "role" in IDENTITY_LAYER.required_vars


class TestPreInstructionsLayer:

    def test_renders_when_content_present(self):
        ctx = {"pre_instructions_content": "- Do this\n- Do that"}
        result = PRE_INSTRUCTIONS_LAYER.render(ctx)
        assert "<pre_instructions>" in result
        assert "Do this" in result

    def test_skipped_when_empty(self):
        assert PRE_INSTRUCTIONS_LAYER.render({"pre_instructions_content": ""}) is None

    def test_skipped_when_whitespace_only(self):
        assert PRE_INSTRUCTIONS_LAYER.render({"pre_instructions_content": "   "}) is None

    def test_skipped_when_missing(self):
        assert PRE_INSTRUCTIONS_LAYER.render({}) is None

    def test_phase_is_configure(self):
        assert PRE_INSTRUCTIONS_LAYER.phase == RenderPhase.CONFIGURE

    def test_priority_between_identity_and_security(self):
        assert LayerPriority.IDENTITY < PRE_INSTRUCTIONS_LAYER.priority < LayerPriority.SECURITY


class TestSecurityLayer:

    def test_renders_with_defaults(self):
        result = SECURITY_LAYER.render({"extra_security_rules": ""})
        assert "<security_policy>" in result
        assert "USER-PROVIDED DATA" in result

    def test_renders_with_extra_rules(self):
        result = SECURITY_LAYER.render({"extra_security_rules": "- No PII sharing"})
        assert "No PII sharing" in result

    def test_no_condition(self):
        assert SECURITY_LAYER.condition is None

    def test_phase_is_configure(self):
        assert SECURITY_LAYER.phase == RenderPhase.CONFIGURE


class TestKnowledgeLayer:

    def test_renders_when_content_present(self):
        result = KNOWLEDGE_LAYER.render({"knowledge_content": "some facts"})
        assert "<knowledge_context>" in result
        assert "some facts" in result

    def test_skipped_when_empty(self):
        assert KNOWLEDGE_LAYER.render({"knowledge_content": ""}) is None

    def test_skipped_when_missing(self):
        assert KNOWLEDGE_LAYER.render({}) is None

    def test_phase_is_request(self):
        assert KNOWLEDGE_LAYER.phase == RenderPhase.REQUEST


class TestUserSessionLayer:

    def test_renders_with_context_and_history(self):
        ctx = {"user_context": "user info", "chat_history": "prior msgs"}
        result = USER_SESSION_LAYER.render(ctx)
        assert "<user_session>" in result
        assert "<conversation_history>" in result
        assert "user info" in result
        assert "prior msgs" in result

    def test_no_condition(self):
        assert USER_SESSION_LAYER.condition is None

    def test_phase_is_request(self):
        assert USER_SESSION_LAYER.phase == RenderPhase.REQUEST


class TestToolsLayer:

    def test_renders_when_has_tools_true(self):
        result = TOOLS_LAYER.render({"has_tools": True, "extra_tool_instructions": ""})
        assert "<tool_policy>" in result
        assert "Prioritize answering" in result

    def test_skipped_when_has_tools_false(self):
        assert TOOLS_LAYER.render({"has_tools": False}) is None

    def test_skipped_when_has_tools_missing(self):
        assert TOOLS_LAYER.render({}) is None

    def test_phase_is_configure(self):
        assert TOOLS_LAYER.phase == RenderPhase.CONFIGURE


class TestOutputLayer:

    def test_renders_when_instructions_present(self):
        result = OUTPUT_LAYER.render({"output_instructions": "Use JSON format"})
        assert "<output_format>" in result
        assert "JSON format" in result

    def test_skipped_when_empty(self):
        assert OUTPUT_LAYER.render({"output_instructions": ""}) is None

    def test_skipped_when_missing(self):
        assert OUTPUT_LAYER.render({}) is None

    def test_phase_is_request(self):
        assert OUTPUT_LAYER.phase == RenderPhase.REQUEST


class TestBehaviorLayer:

    def test_renders_when_rationale_present(self):
        result = BEHAVIOR_LAYER.render({"rationale": "Be concise"})
        assert "<response_style>" in result
        assert "Be concise" in result

    def test_skipped_when_empty(self):
        assert BEHAVIOR_LAYER.render({"rationale": ""}) is None

    def test_skipped_when_missing(self):
        assert BEHAVIOR_LAYER.render({}) is None

    def test_phase_is_configure(self):
        assert BEHAVIOR_LAYER.phase == RenderPhase.CONFIGURE


# ── Cross-layer ordering test ─────────────────────────────────


class TestLayerOrdering:

    def test_all_builtin_layers_have_distinct_priorities(self):
        layers = [
            IDENTITY_LAYER, PRE_INSTRUCTIONS_LAYER, SECURITY_LAYER,
            KNOWLEDGE_LAYER, USER_SESSION_LAYER, TOOLS_LAYER,
            OUTPUT_LAYER, BEHAVIOR_LAYER,
        ]
        priorities = [l.priority for l in layers]
        assert len(set(priorities)) == len(priorities), "Duplicate priorities found"

    def test_builtin_layers_sort_correctly(self):
        layers = [
            BEHAVIOR_LAYER, TOOLS_LAYER, IDENTITY_LAYER,
            KNOWLEDGE_LAYER, SECURITY_LAYER, USER_SESSION_LAYER,
            OUTPUT_LAYER, PRE_INSTRUCTIONS_LAYER,
        ]
        sorted_layers = sorted(layers, key=lambda l: l.priority)
        names = [l.name for l in sorted_layers]
        assert names == [
            "identity", "pre_instructions", "security",
            "knowledge", "user_session", "tools",
            "output", "behavior",
        ]


# ── Edge case tests ──────────────────────────────────────────


class TestPromptLayerEdgeCases:

    def test_render_with_dollar_sign_literal(self):
        """Template with $$ should produce a literal $."""
        layer = PromptLayer(
            name="test",
            priority=LayerPriority.CUSTOM,
            template="<test>Price: $$100</test>",
        )
        result = layer.render({})
        assert "$100" in result

    def test_render_with_braced_variable(self):
        """${var} syntax should work."""
        layer = PromptLayer(
            name="test",
            priority=LayerPriority.CUSTOM,
            template="<test>${name}_suffix</test>",
        )
        result = layer.render({"name": "Bot"})
        assert "Bot_suffix" in result

    def test_render_with_empty_template(self):
        layer = PromptLayer(
            name="test",
            priority=LayerPriority.CUSTOM,
            template="",
        )
        result = layer.render({})
        assert result == ""

    def test_render_with_multiline_template(self):
        layer = PromptLayer(
            name="test",
            priority=LayerPriority.CUSTOM,
            template="<test>\nline1\n$var\nline3\n</test>",
        )
        result = layer.render({"var": "line2"})
        assert "line1\nline2\nline3" in result

    def test_condition_that_raises_exception(self):
        """A condition that raises should propagate the exception."""
        layer = PromptLayer(
            name="test",
            priority=LayerPriority.CUSTOM,
            template="<test>hello</test>",
            condition=lambda ctx: ctx["missing_key"],
        )
        with pytest.raises(KeyError):
            layer.render({})

    def test_partial_render_with_no_matching_vars(self):
        """partial_render with no matching vars should leave template unchanged."""
        layer = PromptLayer(
            name="test",
            priority=LayerPriority.IDENTITY,
            phase=RenderPhase.CONFIGURE,
            template="<test>$name is $role</test>",
        )
        new_layer = layer.partial_render({"unrelated": "value"})
        assert "$name" in new_layer.template
        assert "$role" in new_layer.template
        assert new_layer.phase == RenderPhase.REQUEST

    def test_partial_render_condition_raises_propagates(self):
        """partial_render with a raising condition should propagate."""
        layer = PromptLayer(
            name="test",
            priority=LayerPriority.IDENTITY,
            phase=RenderPhase.CONFIGURE,
            template="<test>$name</test>",
            condition=lambda ctx: ctx["missing"],
        )
        with pytest.raises(KeyError):
            layer.partial_render({"name": "Bot"})

    def test_render_with_none_context_value(self):
        """Context values that are None should render as 'None'."""
        layer = PromptLayer(
            name="test",
            priority=LayerPriority.CUSTOM,
            template="<test>$val</test>",
        )
        result = layer.render({"val": None})
        assert "None" in result

    def test_render_with_numeric_context_value(self):
        layer = PromptLayer(
            name="test",
            priority=LayerPriority.CUSTOM,
            template="<test>Count: $val</test>",
        )
        result = layer.render({"val": 42})
        assert "42" in result

    def test_required_vars_is_frozen(self):
        """required_vars should be immutable frozenset."""
        layer = PromptLayer(
            name="test",
            priority=LayerPriority.CUSTOM,
            template="<test>$x</test>",
            required_vars=frozenset({"x"}),
        )
        assert isinstance(layer.required_vars, frozenset)
        with pytest.raises(AttributeError):
            layer.required_vars = frozenset()

    def test_layer_with_custom_int_priority(self):
        """Priority can be any int, not just LayerPriority enum."""
        layer = PromptLayer(
            name="test",
            priority=999,
            template="<test>hi</test>",
        )
        assert layer.priority == 999
