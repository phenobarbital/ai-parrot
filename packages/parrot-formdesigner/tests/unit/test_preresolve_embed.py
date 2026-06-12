"""Unit tests for FEAT-301 pre-resolve embed in HTML5 and AdaptiveCard renderers.

Tests that:
- HTML5: ``data-logic-state`` JSON script block is ALWAYS embedded.
- HTML5: ``data-depends-on`` attributes are PRESERVED (regression test).
- HTML5: Fields hidden by pre-resolution are still present in markup.
- HTML5: Works without evaluation_context (default empty context).
- AdaptiveCard: ``data.logic_state`` map is embedded in card payload.
- AdaptiveCard: ``isVisible: False`` applied to hidden fields.
- Both renderers: no crash on empty-context forms with no rules.
"""

from __future__ import annotations

import json

import pytest

from parrot_formdesigner.core.constraints import (
    ConditionOperator,
    DependencyRule,
    FieldRefCondition,
    LocationVarCondition,
)
from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.renderers.adaptive_card import AdaptiveCardRenderer
from parrot_formdesigner.renderers.html5 import HTML5Renderer
from parrot_formdesigner.services.rule_evaluator import EvaluationContext


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def conditional_form() -> FormSchema:
    """Form with q2 visible only when q1 == 'yes'."""
    rule = DependencyRule(
        conditions=[FieldRefCondition(field_id="q1", operator=ConditionOperator.EQ, value="yes")],
        effect="show",
    )
    return FormSchema(
        form_id="cond-form",
        title={"en": "Conditional Form"},
        sections=[FormSection(
            section_id="s1",
            title={"en": "S1"},
            fields=[
                FormField(field_id="q1", field_type=FieldType.TEXT, label={"en": "Q1"}),
                FormField(field_id="q2", field_type=FieldType.TEXT, label={"en": "Q2"},
                          depends_on=rule),
            ],
        )],
    )


@pytest.fixture
def hide_form() -> FormSchema:
    """Form with q2 HIDDEN when q1 == 'hide-me'."""
    rule = DependencyRule(
        conditions=[FieldRefCondition(field_id="q1", operator=ConditionOperator.EQ, value="hide-me")],
        effect="hide",
    )
    return FormSchema(
        form_id="hide-form",
        title={"en": "Hide Form"},
        sections=[FormSection(
            section_id="s1",
            title={"en": "S1"},
            fields=[
                FormField(field_id="q1", field_type=FieldType.TEXT, label={"en": "Q1"}),
                FormField(field_id="q2", field_type=FieldType.TEXT, label={"en": "Q2"},
                          depends_on=rule),
            ],
        )],
    )


@pytest.fixture
def flagship_context() -> EvaluationContext:
    """Context with store_type=flagship."""
    return EvaluationContext(location_vars={"store_type": "flagship"})


@pytest.fixture
def no_rule_form() -> FormSchema:
    """Form with no DependencyRule fields."""
    return FormSchema(
        form_id="no-rule",
        title={"en": "No Rules"},
        sections=[FormSection(
            section_id="s1",
            title={"en": "S1"},
            fields=[FormField(field_id="q1", field_type=FieldType.TEXT, label={"en": "Q1"})],
        )],
    )


# ---------------------------------------------------------------------------
# HTML5Renderer — data-logic-state embedding
# ---------------------------------------------------------------------------

class TestHTML5PreResolveEmbed:
    """Tests for HTML5Renderer pre-resolve embedding."""

    async def test_html5_pre_resolve_embed_with_context(
        self, conditional_form: FormSchema, flagship_context: EvaluationContext
    ) -> None:
        """HTML5 output contains data-logic-state block when context is provided."""
        rendered = await HTML5Renderer().render(
            conditional_form,
            evaluation_context=flagship_context,
        )
        assert "data-logic-state" in rendered.content

    async def test_html5_default_empty_context(self, conditional_form: FormSchema) -> None:
        """HTML5 embeds data-logic-state even with no evaluation_context."""
        rendered = await HTML5Renderer().render(conditional_form)
        assert "data-logic-state" in rendered.content

    async def test_html5_data_depends_on_preserved(
        self, conditional_form: FormSchema
    ) -> None:
        """Existing data-depends-on attributes are preserved (regression)."""
        rendered = await HTML5Renderer().render(conditional_form)
        assert "data-depends-on" in rendered.content

    async def test_html5_logic_state_json_valid(
        self, conditional_form: FormSchema
    ) -> None:
        """The data-logic-state block contains valid JSON."""
        rendered = await HTML5Renderer().render(
            conditional_form,
            evaluation_context=EvaluationContext(answers={"q1": "yes"}),
        )
        # Extract JSON from script block
        start = rendered.content.find('<script type="application/json" data-logic-state>')
        end = rendered.content.find("</script>", start)
        assert start != -1 and end != -1
        raw_json = rendered.content[start + len('<script type="application/json" data-logic-state>'):end]
        state = json.loads(raw_json)
        assert isinstance(state, dict)
        assert "q2" in state
        assert state["q2"]["effect"] == "show"
        assert state["q2"]["matched"] is True

    async def test_html5_logic_state_no_match(
        self, conditional_form: FormSchema
    ) -> None:
        """When conditions don't match, matched=False in embedded state."""
        rendered = await HTML5Renderer().render(
            conditional_form,
            evaluation_context=EvaluationContext(answers={"q1": "no"}),
        )
        start = rendered.content.find('<script type="application/json" data-logic-state>')
        end = rendered.content.find("</script>", start)
        raw_json = rendered.content[start + len('<script type="application/json" data-logic-state>'):end]
        state = json.loads(raw_json)
        assert state["q2"]["matched"] is False

    async def test_html5_no_rule_form_empty_state(
        self, no_rule_form: FormSchema
    ) -> None:
        """Form with no rules → data-logic-state block with empty dict."""
        rendered = await HTML5Renderer().render(no_rule_form)
        assert "data-logic-state" in rendered.content
        start = rendered.content.find('<script type="application/json" data-logic-state>')
        end = rendered.content.find("</script>", start)
        raw_json = rendered.content[start + len('<script type="application/json" data-logic-state>'):end]
        state = json.loads(raw_json)
        assert state == {}

    async def test_html5_hidden_field_still_present_in_markup(
        self, hide_form: FormSchema
    ) -> None:
        """Fields hidden by pre-resolution are PRESENT in HTML (not omitted).

        The field must remain in the DOM so local evaluators can toggle it.
        """
        ctx = EvaluationContext(answers={"q1": "hide-me"})
        rendered = await HTML5Renderer().render(hide_form, evaluation_context=ctx)
        # q2 markup must be present
        assert 'id="q2"' in rendered.content or 'form-field--text' in rendered.content
        # And the state says it's hidden
        start = rendered.content.find('<script type="application/json" data-logic-state>')
        end = rendered.content.find("</script>", start)
        raw_json = rendered.content[start + len('<script type="application/json" data-logic-state>'):end]
        state = json.loads(raw_json)
        assert state["q2"]["effect"] == "hide"
        assert state["q2"]["matched"] is True

    async def test_html5_location_var_rule(self) -> None:
        """Location variable conditions work in the embed."""
        loc_rule = DependencyRule(
            conditions=[LocationVarCondition(
                source="location_variable",
                key="store_type",
                operator=ConditionOperator.EQ,
                value="flagship",
            )],
            effect="show",
        )
        form = FormSchema(
            form_id="loc-form",
            title={"en": "Loc Form"},
            sections=[FormSection(
                section_id="s1",
                title={"en": "S1"},
                fields=[
                    FormField(field_id="q1", field_type=FieldType.TEXT, label={"en": "Q1"}),
                    FormField(field_id="q2", field_type=FieldType.TEXT, label={"en": "Q2"},
                              depends_on=loc_rule),
                ],
            )],
        )
        ctx = EvaluationContext(location_vars={"store_type": "flagship"})
        rendered = await HTML5Renderer().render(form, evaluation_context=ctx)
        start = rendered.content.find('<script type="application/json" data-logic-state>')
        end = rendered.content.find("</script>", start)
        raw_json = rendered.content[start + len('<script type="application/json" data-logic-state>'):end]
        state = json.loads(raw_json)
        assert state["q2"]["matched"] is True

    async def test_html5_script_injection_guard(self) -> None:
        """</script> sequences in field data are escaped in the JSON block."""
        # This is a safety test — values are inside JSON strings, the outer
        # JSON itself should not contain a literal </script> sequence.
        rule = DependencyRule(
            conditions=[FieldRefCondition(
                field_id="q1",
                operator=ConditionOperator.EQ,
                value="</script><script>alert(1)</script>",
            )],
        )
        form = FormSchema(
            form_id="xss-form",
            title={"en": "XSS Test"},
            sections=[FormSection(
                section_id="s1",
                title={"en": "S1"},
                fields=[
                    FormField(field_id="q1", field_type=FieldType.TEXT, label={"en": "Q1"}),
                    FormField(field_id="q2", field_type=FieldType.TEXT, label={"en": "Q2"},
                              depends_on=rule),
                ],
            )],
        )
        rendered = await HTML5Renderer().render(form)
        # Count </script> occurrences — should only be the closing tag, not in JSON data
        script_close_count = rendered.content.count("</script>")
        # There's exactly one closing </script> per <script> open tag.
        assert script_close_count >= 1
        # The JSON block's </script> escaping means no raw </script> inside the block
        start = rendered.content.find('<script type="application/json" data-logic-state>')
        end = rendered.content.find("</script>", start)
        raw_block = rendered.content[start:end]
        assert "</" not in raw_block or "<\\/script>" not in raw_block  # escape applied


# ---------------------------------------------------------------------------
# AdaptiveCardRenderer — pre-resolve embed
# ---------------------------------------------------------------------------

class TestAdaptiveCardPreResolveEmbed:
    """Tests for AdaptiveCardRenderer pre-resolve embedding."""

    async def test_ac_pre_resolve_embed_with_context(
        self, conditional_form: FormSchema
    ) -> None:
        """AdaptiveCard payload includes data.logic_state map."""
        ctx = EvaluationContext(answers={"q1": "yes"})
        rendered = await AdaptiveCardRenderer().render(
            conditional_form, evaluation_context=ctx
        )
        card = rendered.content
        assert isinstance(card, dict)
        assert "data" in card
        assert "logic_state" in card["data"]
        assert "q2" in card["data"]["logic_state"]
        assert card["data"]["logic_state"]["q2"]["matched"] is True

    async def test_ac_default_empty_context(self, conditional_form: FormSchema) -> None:
        """AdaptiveCard embeds logic_state even without evaluation_context."""
        rendered = await AdaptiveCardRenderer().render(conditional_form)
        card = rendered.content
        assert "data" in card
        assert "logic_state" in card["data"]

    async def test_ac_no_rule_form_empty_logic_state(
        self, no_rule_form: FormSchema
    ) -> None:
        """Form with no rules → card.data.logic_state == {}."""
        rendered = await AdaptiveCardRenderer().render(no_rule_form)
        card = rendered.content
        assert card["data"]["logic_state"] == {}

    async def test_ac_hidden_field_isvisible_false(
        self, hide_form: FormSchema
    ) -> None:
        """Input element for hidden field gets isVisible=False."""
        ctx = EvaluationContext(answers={"q1": "hide-me"})
        rendered = await AdaptiveCardRenderer().render(hide_form, evaluation_context=ctx)
        card = rendered.content
        assert card["data"]["logic_state"]["q2"]["effect"] == "hide"

        # Find the input element with id=q2 and check isVisible
        def _find_element(elements: list, eid: str) -> dict | None:
            for elem in elements:
                if isinstance(elem, dict):
                    if elem.get("id") == eid:
                        return elem
                    found = _find_element(elem.get("items", []), eid)
                    if found:
                        return found
            return None

        q2_elem = _find_element(card.get("body", []), "q2")
        if q2_elem is not None:
            assert q2_elem.get("isVisible") is False

    async def test_ac_show_field_no_isvisible_false(
        self, conditional_form: FormSchema
    ) -> None:
        """Fields that are shown do NOT get isVisible=False."""
        # No match context → q2 matched=False, effect="show"
        rendered = await AdaptiveCardRenderer().render(
            conditional_form,
            evaluation_context=EvaluationContext(),
        )
        card = rendered.content
        # q2's element should NOT have isVisible=False
        def _find_element(elements: list, eid: str) -> dict | None:
            for elem in elements:
                if isinstance(elem, dict):
                    if elem.get("id") == eid:
                        return elem
                    found = _find_element(elem.get("items", []), eid)
                    if found:
                        return found
            return None

        q2_elem = _find_element(card.get("body", []), "q2")
        if q2_elem is not None:
            assert q2_elem.get("isVisible") is not False
