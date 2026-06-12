"""Regression tests for the FEAT-301 code-review fixes.

- H-1 — data-depends-on stays byte-identical for legacy forms (no "source" key).
- H-2 — AdaptiveCard render_section (wizard mode) embeds logic_state.
- M-1 — /evaluate returns 400 (not 422) for non-dict input fields.
- M-3 — YAML extractor builds explicit models for the new variants.
- M-4 — cycle detection survives dependency chains deeper than the
        Python recursion limit.
"""

from __future__ import annotations

import json

from parrot_formdesigner.core.constraints import (
    ConditionOperator,
    DependencyRule,
    FieldRefCondition,
    LocationVarCondition,
)
from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.renderers.html5 import HTML5Renderer, _depends_on_attr_json
from parrot_formdesigner.services.logic_graph import LogicGraph
from parrot_formdesigner.services.rule_evaluator import EvaluationContext


def _legacy_rule() -> DependencyRule:
    """A rule as a pre-FEAT-301 form would have stored it."""
    return DependencyRule.model_validate(
        {
            "conditions": [{"field_id": "q1", "operator": "eq", "value": "yes"}],
            "logic": "and",
            "effect": "show",
        }
    )


def _conditional_form() -> FormSchema:
    return FormSchema(
        form_id="f1",
        title="F",
        tenant="t1",
        sections=[
            FormSection(
                section_id="s1",
                fields=[
                    FormField(field_id="q1", field_type=FieldType.TEXT, label="Q1"),
                    FormField(
                        field_id="q2",
                        field_type=FieldType.TEXT,
                        label="Q2",
                        depends_on=_legacy_rule(),
                    ),
                ],
            )
        ],
    )


# ---------------------------------------------------------------------------
# H-1 — byte-identity of data-depends-on for legacy forms
# ---------------------------------------------------------------------------


class TestH1DependsOnByteIdentity:
    def test_no_source_key_for_field_conditions(self):
        payload = json.loads(_depends_on_attr_json(_legacy_rule()))
        assert payload["conditions"][0] == {
            "field_id": "q1",
            "operator": "eq",
            "value": "yes",
        }
        assert "source" not in payload["conditions"][0]

    def test_new_variants_keep_source(self):
        rule = DependencyRule(
            conditions=[
                LocationVarCondition(
                    source="location_variable",
                    key="store_type",
                    operator=ConditionOperator.EQ,
                    value="flagship",
                )
            ]
        )
        payload = json.loads(_depends_on_attr_json(rule))
        assert payload["conditions"][0]["source"] == "location_variable"

    async def test_rendered_attribute_has_no_source(self):
        rendered = await HTML5Renderer().render(_conditional_form())
        assert "data-depends-on" in rendered.content
        assert "&quot;source&quot;: &quot;field&quot;" not in rendered.content
        assert '"source": "field"' not in rendered.content


# ---------------------------------------------------------------------------
# H-2 — wizard render_section embeds logic_state
# ---------------------------------------------------------------------------


class TestH2WizardLogicState:
    async def test_render_section_embeds_logic_state(self):
        from parrot_formdesigner.renderers.adaptive_card import AdaptiveCardRenderer

        rendered = await AdaptiveCardRenderer().render_section(
            _conditional_form(), 0
        )
        card = rendered.content
        assert "logic_state" in card.get("data", {})
        assert "q2" in card["data"]["logic_state"]

    async def test_render_section_accepts_context(self):
        from parrot_formdesigner.renderers.adaptive_card import AdaptiveCardRenderer

        ctx = EvaluationContext(answers={"q1": "yes"})
        rendered = await AdaptiveCardRenderer().render_section(
            _conditional_form(), 0, evaluation_context=ctx
        )
        state = rendered.content["data"]["logic_state"]
        assert state["q2"]["matched"] is True


# ---------------------------------------------------------------------------
# M-1 — /evaluate 400 for non-dict fields
# ---------------------------------------------------------------------------


class TestM1EvaluateBadTypes:
    async def test_non_dict_answers_returns_400(self):
        from tests.unit.test_api_feat300 import _make_handler, _make_request
        from parrot_formdesigner.services.registry import FormRegistry

        registry = FormRegistry()
        await registry.register(_conditional_form(), tenant="t1")
        handler = _make_handler(registry)

        resp = await handler.evaluate_form(
            _make_request(method="POST", form_id="f1", body={"answers": "nope"})
        )
        assert resp.status == 400


# ---------------------------------------------------------------------------
# M-3 — YAML explicit variant dispatch
# ---------------------------------------------------------------------------


class TestM3YamlDispatch:
    def test_location_variable_from_yaml_dict(self):
        from parrot_formdesigner.extractors.yaml import YamlExtractor

        rule = YamlExtractor()._parse_dependency_rule(
            {
                "conditions": [
                    {
                        "source": "location_variable",
                        "key": "store_type",
                        "operator": "eq",
                        "value": "flagship",
                    }
                ],
                "logic": "and",
                "effect": "show",
            }
        )
        assert isinstance(rule.conditions[0], LocationVarCondition)
        assert rule.conditions[0].key == "store_type"

    def test_missing_key_skipped_not_crash(self):
        from parrot_formdesigner.extractors.yaml import YamlExtractor

        rule = YamlExtractor()._parse_dependency_rule(
            {
                "conditions": [
                    {"source": "location_variable", "operator": "eq", "value": "x"},
                    {"field_id": "q1", "operator": "eq", "value": 1},
                ],
            }
        )
        assert len(rule.conditions) == 1
        assert isinstance(rule.conditions[0], FieldRefCondition)


# ---------------------------------------------------------------------------
# M-4 — deep chains do not hit the recursion limit
# ---------------------------------------------------------------------------


class TestM4DeepChains:
    def _deep_cyclic_form(self, depth: int) -> FormSchema:
        fields = []
        for i in range(depth):
            nxt = (i + 1) % depth  # last points back to first → one big cycle
            fields.append(
                FormField(
                    field_id=f"q{i}",
                    field_type=FieldType.TEXT,
                    label=f"Q{i}",
                    depends_on=DependencyRule(
                        conditions=[
                            FieldRefCondition(
                                field_id=f"q{nxt}",
                                operator=ConditionOperator.EQ,
                                value="x",
                            )
                        ]
                    ),
                )
            )
        return FormSchema(
            form_id="deep",
            title="Deep",
            sections=[FormSection(section_id="s1", fields=fields)],
        )

    def test_cycle_detection_at_depth_2000(self):
        form = self._deep_cyclic_form(2000)
        graph = LogicGraph.build(form)
        cycles = graph.detect_cycles()  # would RecursionError before M-4 fix
        assert cycles
