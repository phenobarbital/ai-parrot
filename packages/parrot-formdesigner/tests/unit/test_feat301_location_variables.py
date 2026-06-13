"""FEAT-301 reconciliation — location variables & visit context on main's RuleEvaluator.

This is the additive port of FEAT-301's location-variable / visit-context
support onto the conditional-sections ``RuleEvaluator`` that landed on main.
Main's evaluator previously conditioned only on field answers; FEAT-301 adds
two new condition sources, selected by ``FieldCondition.source``:

- ``"field"`` (default) → ``answers[field_id]`` (unchanged, backward compatible)
- ``"location_variable"`` → ``location_vars[key]`` (Org Graph, FEAT-302)
- ``"visit_context"`` → ``visit_context[key]`` (visit metadata)

These golden cases are the conformance contract for client-side evaluators
(JS/native) that must match the server. Backward compatibility (legacy
field conditions with no ``source``) is asserted explicitly.
"""

from __future__ import annotations

import pytest

from parrot_formdesigner.core.constraints import (
    ConditionOperator,
    DependencyRule,
    FieldCondition,
)
from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.services.rule_evaluator import RuleEvaluator


def _form_with_rule(rule: DependencyRule, target: str = "q_target") -> FormSchema:
    """A 2-field form where ``target`` has the given show-rule."""
    return FormSchema(
        form_id="f1",
        title="F",
        sections=[
            FormSection(
                section_id="s1",
                fields=[
                    FormField(field_id="q1", field_type=FieldType.TEXT, label="Q1"),
                    FormField(
                        field_id=target,
                        field_type=FieldType.TEXT,
                        label="Target",
                        depends_on=rule,
                    ),
                ],
            )
        ],
    )


def _show_rule(cond: FieldCondition) -> DependencyRule:
    return DependencyRule(conditions=[cond], logic="and", effect="show")


# ---------------------------------------------------------------------------
# Backward compatibility — legacy field conditions (no source)
# ---------------------------------------------------------------------------


class TestBackwardCompat:
    async def test_legacy_field_condition_no_source(self):
        """A condition dict with no `source` resolves as a field condition."""
        rule = DependencyRule.model_validate({
            "conditions": [{"field_id": "q1", "operator": "eq", "value": "yes"}],
            "logic": "and", "effect": "show",
        })
        assert rule.conditions[0].source == "field"  # default
        res = await RuleEvaluator().resolve(_form_with_rule(rule), {"q1": "yes"})
        assert res.visible["q_target"] is True

    async def test_legacy_field_condition_hides_when_no_match(self):
        rule = _show_rule(FieldCondition(field_id="q1", operator=ConditionOperator.EQ, value="yes"))
        res = await RuleEvaluator().resolve(_form_with_rule(rule), {"q1": "no"})
        assert res.visible["q_target"] is False


# ---------------------------------------------------------------------------
# Location variables
# ---------------------------------------------------------------------------


class TestLocationVariables:
    async def test_locvar_eq_match_shows(self):
        rule = _show_rule(FieldCondition(
            field_id="", source="location_variable", key="store_type",
            operator=ConditionOperator.EQ, value="flagship",
        ))
        res = await RuleEvaluator().resolve(
            _form_with_rule(rule), {}, location_vars={"store_type": "flagship"}
        )
        assert res.visible["q_target"] is True

    async def test_locvar_eq_nomatch_hides(self):
        rule = _show_rule(FieldCondition(
            field_id="", source="location_variable", key="store_type",
            operator=ConditionOperator.EQ, value="flagship",
        ))
        res = await RuleEvaluator().resolve(
            _form_with_rule(rule), {}, location_vars={"store_type": "regional"}
        )
        assert res.visible["q_target"] is False

    async def test_locvar_key_missing_eq_false(self):
        """Key-missing semantics: EQ against an absent location var → no match."""
        rule = _show_rule(FieldCondition(
            field_id="", source="location_variable", key="store_type",
            operator=ConditionOperator.EQ, value="flagship",
        ))
        res = await RuleEvaluator().resolve(_form_with_rule(rule), {}, location_vars={})
        assert res.visible["q_target"] is False

    async def test_locvar_key_missing_is_empty_true(self):
        """Key-missing semantics: IS_EMPTY against an absent location var → fires."""
        rule = _show_rule(FieldCondition(
            field_id="", source="location_variable", key="store_type",
            operator=ConditionOperator.IS_EMPTY,
        ))
        res = await RuleEvaluator().resolve(_form_with_rule(rule), {}, location_vars={})
        assert res.visible["q_target"] is True

    @pytest.mark.parametrize("op,value,locvar,expected", [
        (ConditionOperator.NEQ, "flagship", "regional", True),
        (ConditionOperator.IN, ["flagship", "outlet"], "outlet", True),
        (ConditionOperator.NOT_IN, ["flagship"], "regional", True),
        (ConditionOperator.GT, 100, 250, True),
        (ConditionOperator.LT, 100, 50, True),
        (ConditionOperator.GTE, 100, 100, True),
        (ConditionOperator.LTE, 100, 100, True),
        (ConditionOperator.IS_NOT_EMPTY, None, "x", True),
    ])
    async def test_locvar_operator_sweep(self, op, value, locvar, expected):
        cond = FieldCondition(
            field_id="", source="location_variable", key="lv",
            operator=op, value=value,
        )
        res = await RuleEvaluator().resolve(
            _form_with_rule(_show_rule(cond)), {}, location_vars={"lv": locvar}
        )
        assert res.visible["q_target"] is expected


# ---------------------------------------------------------------------------
# Visit context
# ---------------------------------------------------------------------------


class TestVisitContext:
    async def test_visitctx_in_match(self):
        rule = _show_rule(FieldCondition(
            field_id="", source="visit_context", key="visit_type",
            operator=ConditionOperator.IN, value=["audit", "training"],
        ))
        res = await RuleEvaluator().resolve(
            _form_with_rule(rule), {}, visit_context={"visit_type": "audit"}
        )
        assert res.visible["q_target"] is True

    async def test_visitctx_key_missing_is_empty(self):
        rule = _show_rule(FieldCondition(
            field_id="", source="visit_context", key="visit_type",
            operator=ConditionOperator.IS_EMPTY,
        ))
        res = await RuleEvaluator().resolve(_form_with_rule(rule), {}, visit_context={})
        assert res.visible["q_target"] is True


# ---------------------------------------------------------------------------
# Mixed-source logic
# ---------------------------------------------------------------------------


class TestMixedSources:
    async def test_and_field_and_locvar(self):
        """AND across a field answer and a location variable — both must hold."""
        rule = DependencyRule(
            conditions=[
                FieldCondition(field_id="q1", operator=ConditionOperator.EQ, value="yes"),
                FieldCondition(field_id="", source="location_variable", key="store_type",
                               operator=ConditionOperator.EQ, value="flagship"),
            ],
            logic="and", effect="show",
        )
        form = _form_with_rule(rule)
        ev = RuleEvaluator()
        both = await ev.resolve(form, {"q1": "yes"}, location_vars={"store_type": "flagship"})
        assert both.visible["q_target"] is True
        one = await ev.resolve(form, {"q1": "yes"}, location_vars={"store_type": "regional"})
        assert one.visible["q_target"] is False

    async def test_or_field_or_visitctx(self):
        rule = DependencyRule(
            conditions=[
                FieldCondition(field_id="q1", operator=ConditionOperator.EQ, value="yes"),
                FieldCondition(field_id="", source="visit_context", key="visit_type",
                               operator=ConditionOperator.EQ, value="audit"),
            ],
            logic="or", effect="show",
        )
        form = _form_with_rule(rule)
        res = await RuleEvaluator().resolve(
            form, {"q1": "no"}, visit_context={"visit_type": "audit"}
        )
        assert res.visible["q_target"] is True
