"""Unit tests for FEAT-301 RuleEvaluator.

Tests cover:
- All ConditionOperator values × 3 condition variants.
- and/or logic combinations.
- Key-missing semantics (RESUELTO §8).
- Hidden-field exclusion from downstream inputs.
- evaluate_form() covers all fields with depends_on; omits those without.
"""

from __future__ import annotations

import pytest

from parrot_formdesigner.core.constraints import (
    ConditionOperator,
    DependencyRule,
    FieldRefCondition,
    LocationVarCondition,
    VisitContextCondition,
)
from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.services.rule_evaluator import EvaluationContext, RuleEvaluator


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def evaluator() -> RuleEvaluator:
    """Return a fresh RuleEvaluator (stateless, reusable)."""
    return RuleEvaluator()


@pytest.fixture
def location_var_rule() -> DependencyRule:
    """DependencyRule: show field only when store_type == 'flagship'."""
    return DependencyRule(
        conditions=[
            LocationVarCondition(
                source="location_variable",
                key="store_type",
                operator=ConditionOperator.EQ,
                value="flagship",
            )
        ],
        logic="and",
        effect="show",
    )


@pytest.fixture
def flagship_context() -> EvaluationContext:
    """Context with store_type=flagship."""
    return EvaluationContext(
        answers={},
        location_vars={"store_type": "flagship"},
        visit_context={},
    )


@pytest.fixture
def non_flagship_context() -> EvaluationContext:
    """Context with store_type=regional (not flagship)."""
    return EvaluationContext(
        answers={},
        location_vars={"store_type": "regional"},
        visit_context={},
    )


def _simple_form(*fields: FormField) -> FormSchema:
    """Build a minimal FormSchema with the given fields in a single section."""
    return FormSchema(
        form_id="test-form",
        title={"en": "Test Form"},
        sections=[FormSection(section_id="s1", title={"en": "S1"}, fields=list(fields))],
    )


def _field(fid: str, rule: DependencyRule | None = None) -> FormField:
    """Build a simple text FormField."""
    return FormField(
        field_id=fid,
        field_type=FieldType.TEXT,
        label={"en": fid},
        depends_on=rule,
    )


# ---------------------------------------------------------------------------
# FieldRefCondition — basic EQ / NEQ
# ---------------------------------------------------------------------------

class TestFieldRefEvaluation:
    """Tests for FieldRefCondition evaluation."""

    def test_eq_match(self, evaluator: RuleEvaluator) -> None:
        """Rule fires when field answer equals expected value."""
        rule = DependencyRule(
            conditions=[FieldRefCondition(field_id="q1", operator=ConditionOperator.EQ, value="yes")],
        )
        ctx = EvaluationContext(answers={"q1": "yes"})
        assert evaluator.evaluate(rule, ctx) == "show"

    def test_eq_no_match(self, evaluator: RuleEvaluator) -> None:
        """Rule returns None when answer does not match."""
        rule = DependencyRule(
            conditions=[FieldRefCondition(field_id="q1", operator=ConditionOperator.EQ, value="yes")],
        )
        ctx = EvaluationContext(answers={"q1": "no"})
        assert evaluator.evaluate(rule, ctx) is None

    def test_neq_match(self, evaluator: RuleEvaluator) -> None:
        """NEQ fires when values differ."""
        rule = DependencyRule(
            conditions=[FieldRefCondition(field_id="q1", operator=ConditionOperator.NEQ, value="yes")],
        )
        ctx = EvaluationContext(answers={"q1": "no"})
        assert evaluator.evaluate(rule, ctx) == "show"

    def test_gt_numeric(self, evaluator: RuleEvaluator) -> None:
        """GT fires when actual > expected (numeric)."""
        rule = DependencyRule(
            conditions=[FieldRefCondition(field_id="q1", operator=ConditionOperator.GT, value=5)],
        )
        ctx = EvaluationContext(answers={"q1": 10})
        assert evaluator.evaluate(rule, ctx) == "show"
        ctx2 = EvaluationContext(answers={"q1": 3})
        assert evaluator.evaluate(rule, ctx2) is None

    def test_gte_numeric(self, evaluator: RuleEvaluator) -> None:
        """GTE fires when actual >= expected."""
        rule = DependencyRule(
            conditions=[FieldRefCondition(field_id="q1", operator=ConditionOperator.GTE, value=5)],
        )
        assert evaluator.evaluate(rule, EvaluationContext(answers={"q1": 5})) == "show"
        assert evaluator.evaluate(rule, EvaluationContext(answers={"q1": 6})) == "show"
        assert evaluator.evaluate(rule, EvaluationContext(answers={"q1": 4})) is None

    def test_lt_numeric(self, evaluator: RuleEvaluator) -> None:
        """LT fires when actual < expected."""
        rule = DependencyRule(
            conditions=[FieldRefCondition(field_id="q1", operator=ConditionOperator.LT, value=5)],
        )
        assert evaluator.evaluate(rule, EvaluationContext(answers={"q1": 3})) == "show"
        assert evaluator.evaluate(rule, EvaluationContext(answers={"q1": 5})) is None

    def test_lte_numeric(self, evaluator: RuleEvaluator) -> None:
        """LTE fires when actual <= expected."""
        rule = DependencyRule(
            conditions=[FieldRefCondition(field_id="q1", operator=ConditionOperator.LTE, value=5)],
        )
        assert evaluator.evaluate(rule, EvaluationContext(answers={"q1": 5})) == "show"
        assert evaluator.evaluate(rule, EvaluationContext(answers={"q1": 4})) == "show"
        assert evaluator.evaluate(rule, EvaluationContext(answers={"q1": 6})) is None

    def test_in_match(self, evaluator: RuleEvaluator) -> None:
        """IN fires when actual is in expected list."""
        rule = DependencyRule(
            conditions=[FieldRefCondition(field_id="q1", operator=ConditionOperator.IN, value=["a", "b", "c"])],
        )
        assert evaluator.evaluate(rule, EvaluationContext(answers={"q1": "b"})) == "show"
        assert evaluator.evaluate(rule, EvaluationContext(answers={"q1": "d"})) is None

    def test_not_in_match(self, evaluator: RuleEvaluator) -> None:
        """NOT_IN fires when actual is NOT in expected list."""
        rule = DependencyRule(
            conditions=[FieldRefCondition(field_id="q1", operator=ConditionOperator.NOT_IN, value=["a", "b"])],
        )
        assert evaluator.evaluate(rule, EvaluationContext(answers={"q1": "c"})) == "show"
        assert evaluator.evaluate(rule, EvaluationContext(answers={"q1": "a"})) is None

    def test_is_empty_match(self, evaluator: RuleEvaluator) -> None:
        """IS_EMPTY fires when answer is None, empty string, or empty list."""
        rule = DependencyRule(
            conditions=[FieldRefCondition(field_id="q1", operator=ConditionOperator.IS_EMPTY)],
        )
        assert evaluator.evaluate(rule, EvaluationContext(answers={"q1": None})) == "show"
        assert evaluator.evaluate(rule, EvaluationContext(answers={"q1": ""})) == "show"
        assert evaluator.evaluate(rule, EvaluationContext(answers={"q1": []})) == "show"
        assert evaluator.evaluate(rule, EvaluationContext(answers={"q1": "text"})) is None

    def test_is_not_empty_match(self, evaluator: RuleEvaluator) -> None:
        """IS_NOT_EMPTY fires when answer has a value."""
        rule = DependencyRule(
            conditions=[FieldRefCondition(field_id="q1", operator=ConditionOperator.IS_NOT_EMPTY)],
        )
        assert evaluator.evaluate(rule, EvaluationContext(answers={"q1": "text"})) == "show"
        assert evaluator.evaluate(rule, EvaluationContext(answers={"q1": ""})) is None


# ---------------------------------------------------------------------------
# LocationVarCondition evaluation
# ---------------------------------------------------------------------------

class TestLocationVarEvaluation:
    """Tests for LocationVarCondition evaluation."""

    def test_location_var_eq_match(
        self, evaluator: RuleEvaluator, location_var_rule: DependencyRule, flagship_context: EvaluationContext
    ) -> None:
        """LocationVarCondition fires when location var matches."""
        assert evaluator.evaluate(location_var_rule, flagship_context) == "show"

    def test_location_var_eq_no_match(
        self, evaluator: RuleEvaluator, location_var_rule: DependencyRule, non_flagship_context: EvaluationContext
    ) -> None:
        """LocationVarCondition returns None when var doesn't match."""
        assert evaluator.evaluate(location_var_rule, non_flagship_context) is None

    def test_location_var_in_operator(self, evaluator: RuleEvaluator) -> None:
        """IN operator on location var works correctly."""
        rule = DependencyRule(
            conditions=[LocationVarCondition(
                source="location_variable",
                key="store_tier",
                operator=ConditionOperator.IN,
                value=["gold", "platinum"],
            )],
        )
        assert evaluator.evaluate(rule, EvaluationContext(location_vars={"store_tier": "gold"})) == "show"
        assert evaluator.evaluate(rule, EvaluationContext(location_vars={"store_tier": "silver"})) is None

    def test_location_var_is_empty(self, evaluator: RuleEvaluator) -> None:
        """IS_EMPTY on location var works."""
        rule = DependencyRule(
            conditions=[LocationVarCondition(
                source="location_variable",
                key="optional_flag",
                operator=ConditionOperator.IS_EMPTY,
            )],
        )
        assert evaluator.evaluate(rule, EvaluationContext(location_vars={"optional_flag": ""})) == "show"
        assert evaluator.evaluate(rule, EvaluationContext(location_vars={"optional_flag": "set"})) is None


# ---------------------------------------------------------------------------
# VisitContextCondition evaluation
# ---------------------------------------------------------------------------

class TestVisitContextEvaluation:
    """Tests for VisitContextCondition evaluation."""

    def test_visit_context_in_match(self, evaluator: RuleEvaluator) -> None:
        """IN operator fires for visit_context match."""
        rule = DependencyRule(
            conditions=[VisitContextCondition(
                source="visit_context",
                key="visit_type",
                operator=ConditionOperator.IN,
                value=["audit", "merchandising"],
            )],
        )
        ctx = EvaluationContext(visit_context={"visit_type": "audit"})
        assert evaluator.evaluate(rule, ctx) == "show"
        ctx2 = EvaluationContext(visit_context={"visit_type": "sales"})
        assert evaluator.evaluate(rule, ctx2) is None

    def test_visit_context_eq_match(self, evaluator: RuleEvaluator) -> None:
        """EQ operator fires for visit_context match."""
        rule = DependencyRule(
            conditions=[VisitContextCondition(
                source="visit_context",
                key="visit_status",
                operator=ConditionOperator.EQ,
                value="active",
            )],
        )
        ctx = EvaluationContext(visit_context={"visit_status": "active"})
        assert evaluator.evaluate(rule, ctx) == "show"


# ---------------------------------------------------------------------------
# Key-missing semantics (RESUELTO §8)
# ---------------------------------------------------------------------------

class TestKeyMissingSemantics:
    """Tests for key-missing semantics (RESUELTO §8).

    Absent key → IS_EMPTY evaluates True, other operators evaluate False.
    Rules ALWAYS resolve, NEVER raise.
    """

    def test_key_missing_eq_false(
        self, evaluator: RuleEvaluator, location_var_rule: DependencyRule
    ) -> None:
        """EQ operator vs missing key → no match (None/False, not exception)."""
        ctx = EvaluationContext()  # empty — store_type missing
        assert evaluator.evaluate(location_var_rule, ctx) is None

    def test_key_missing_is_empty_true(self, evaluator: RuleEvaluator) -> None:
        """IS_EMPTY vs missing key → True (missing counts as empty)."""
        rule = DependencyRule(
            conditions=[LocationVarCondition(
                source="location_variable",
                key="absent_key",
                operator=ConditionOperator.IS_EMPTY,
            )],
        )
        assert evaluator.evaluate(rule, EvaluationContext()) == "show"

    def test_key_missing_is_not_empty_false(self, evaluator: RuleEvaluator) -> None:
        """IS_NOT_EMPTY vs missing key → False."""
        rule = DependencyRule(
            conditions=[LocationVarCondition(
                source="location_variable",
                key="absent_key",
                operator=ConditionOperator.IS_NOT_EMPTY,
            )],
        )
        assert evaluator.evaluate(rule, EvaluationContext()) is None

    def test_key_missing_gt_false(self, evaluator: RuleEvaluator) -> None:
        """GT vs missing key → False."""
        rule = DependencyRule(
            conditions=[FieldRefCondition(
                field_id="q_missing",
                operator=ConditionOperator.GT,
                value=0,
            )],
        )
        assert evaluator.evaluate(rule, EvaluationContext()) is None

    def test_key_missing_field_ref(self, evaluator: RuleEvaluator) -> None:
        """Missing field answer: EQ returns None, no exception."""
        rule = DependencyRule(
            conditions=[FieldRefCondition(
                field_id="absent_field",
                operator=ConditionOperator.EQ,
                value="yes",
            )],
        )
        # No exception — rule degrades gracefully
        result = evaluator.evaluate(rule, EvaluationContext(answers={}))
        assert result is None

    def test_key_missing_visit_context(self, evaluator: RuleEvaluator) -> None:
        """Missing visit_context key: IS_EMPTY → True."""
        rule = DependencyRule(
            conditions=[VisitContextCondition(
                source="visit_context",
                key="missing_key",
                operator=ConditionOperator.IS_EMPTY,
            )],
        )
        assert evaluator.evaluate(rule, EvaluationContext()) == "show"

    def test_empty_context_no_match(self, evaluator: RuleEvaluator) -> None:
        """Empty context: EQ operator always returns None."""
        rule = DependencyRule(
            conditions=[
                FieldRefCondition(field_id="q1", operator=ConditionOperator.EQ, value="yes"),
                LocationVarCondition(
                    source="location_variable", key="k", operator=ConditionOperator.EQ, value="v"
                ),
            ],
            logic="or",
        )
        assert evaluator.evaluate(rule, EvaluationContext()) is None


# ---------------------------------------------------------------------------
# AND / OR logic
# ---------------------------------------------------------------------------

class TestAndOrLogic:
    """Tests for AND/OR condition combining."""

    def test_and_logic_all_must_match(self, evaluator: RuleEvaluator) -> None:
        """AND: all conditions must fire."""
        rule = DependencyRule(
            conditions=[
                FieldRefCondition(field_id="q1", operator=ConditionOperator.EQ, value="yes"),
                FieldRefCondition(field_id="q2", operator=ConditionOperator.EQ, value="no"),
            ],
            logic="and",
        )
        # Both match
        assert evaluator.evaluate(
            rule, EvaluationContext(answers={"q1": "yes", "q2": "no"})
        ) == "show"
        # Only one matches
        assert evaluator.evaluate(
            rule, EvaluationContext(answers={"q1": "yes", "q2": "maybe"})
        ) is None

    def test_or_logic_one_enough(self, evaluator: RuleEvaluator) -> None:
        """OR: any one condition firing is sufficient."""
        rule = DependencyRule(
            conditions=[
                FieldRefCondition(field_id="q1", operator=ConditionOperator.EQ, value="yes"),
                FieldRefCondition(field_id="q2", operator=ConditionOperator.EQ, value="no"),
            ],
            logic="or",
        )
        # Only first matches
        assert evaluator.evaluate(
            rule, EvaluationContext(answers={"q1": "yes", "q2": "maybe"})
        ) == "show"
        # None match
        assert evaluator.evaluate(
            rule, EvaluationContext(answers={"q1": "nope", "q2": "nope"})
        ) is None

    def test_effect_is_preserved(self, evaluator: RuleEvaluator) -> None:
        """effect='hide' is returned when conditions fire."""
        rule = DependencyRule(
            conditions=[FieldRefCondition(field_id="q1", operator=ConditionOperator.EQ, value="y")],
            effect="hide",
        )
        assert evaluator.evaluate(rule, EvaluationContext(answers={"q1": "y"})) == "hide"

    def test_effect_require(self, evaluator: RuleEvaluator) -> None:
        """effect='require' is returned when conditions fire."""
        rule = DependencyRule(
            conditions=[FieldRefCondition(field_id="q1", operator=ConditionOperator.IS_NOT_EMPTY)],
            effect="require",
        )
        assert evaluator.evaluate(rule, EvaluationContext(answers={"q1": "something"})) == "require"

    def test_effect_disable(self, evaluator: RuleEvaluator) -> None:
        """effect='disable' is returned when conditions fire."""
        rule = DependencyRule(
            conditions=[FieldRefCondition(field_id="q1", operator=ConditionOperator.EQ, value="lock")],
            effect="disable",
        )
        assert evaluator.evaluate(rule, EvaluationContext(answers={"q1": "lock"})) == "disable"

    def test_empty_conditions_no_fire(self, evaluator: RuleEvaluator) -> None:
        """Empty conditions list → no fire (AND of nothing = False)."""
        rule = DependencyRule(conditions=[], logic="and")
        assert evaluator.evaluate(rule, EvaluationContext()) is None


# ---------------------------------------------------------------------------
# evaluate_form — form-level evaluation
# ---------------------------------------------------------------------------

class TestEvaluateForm:
    """Tests for RuleEvaluator.evaluate_form()."""

    def test_returns_all_fields_with_depends_on(self, evaluator: RuleEvaluator) -> None:
        """evaluate_form covers every field with a depends_on."""
        rule = DependencyRule(
            conditions=[FieldRefCondition(field_id="q1", operator=ConditionOperator.EQ, value="y")],
        )
        form = _simple_form(
            _field("q1"),
            _field("q2", rule),
            _field("q3", rule),
        )
        results = evaluator.evaluate_form(form, EvaluationContext(answers={"q1": "y"}))
        assert set(results.keys()) == {"q2", "q3"}

    def test_fields_without_depends_on_omitted(self, evaluator: RuleEvaluator) -> None:
        """Fields without depends_on are NOT in the result."""
        form = _simple_form(_field("q1"), _field("q2"))
        results = evaluator.evaluate_form(form, EvaluationContext())
        assert "q1" not in results
        assert "q2" not in results

    def test_hidden_field_excluded_from_inputs(self, evaluator: RuleEvaluator) -> None:
        """Hidden q2's answer is NOT available to q3's rule."""
        # q1 → q2 (hide when q1="yes")
        # q3 depends on q2="something" — but if q2 is hidden, its answer is absent.
        hide_q2_rule = DependencyRule(
            conditions=[FieldRefCondition(field_id="q1", operator=ConditionOperator.EQ, value="yes")],
            effect="hide",
        )
        show_q3_rule = DependencyRule(
            conditions=[FieldRefCondition(
                field_id="q2",
                operator=ConditionOperator.IS_NOT_EMPTY,
            )],
            effect="show",
        )
        form = _simple_form(
            _field("q1"),
            _field("q2", hide_q2_rule),
            _field("q3", show_q3_rule),
        )
        ctx = EvaluationContext(answers={"q1": "yes", "q2": "something"})
        results = evaluator.evaluate_form(form, ctx)

        # q2 is hidden
        assert results["q2"].effect == "hide"
        assert results["q2"].matched is True

        # q3: q2 is hidden → its answer is excluded → IS_NOT_EMPTY on q2 = False
        # So q3's rule doesn't fire → effect="show", matched=False
        assert results["q3"].effect == "show"
        assert results["q3"].matched is False

    def test_no_rule_fires_gives_show_default(self, evaluator: RuleEvaluator) -> None:
        """When a rule doesn't fire, the result is effect=show, matched=False."""
        rule = DependencyRule(
            conditions=[FieldRefCondition(field_id="q1", operator=ConditionOperator.EQ, value="yes")],
        )
        form = _simple_form(_field("q1"), _field("q2", rule))
        results = evaluator.evaluate_form(form, EvaluationContext(answers={"q1": "no"}))
        assert results["q2"].effect == "show"
        assert results["q2"].matched is False

    def test_matched_true_when_rule_fires(self, evaluator: RuleEvaluator) -> None:
        """matched=True when the rule conditions fire."""
        rule = DependencyRule(
            conditions=[FieldRefCondition(field_id="q1", operator=ConditionOperator.EQ, value="yes")],
            effect="hide",
        )
        form = _simple_form(_field("q1"), _field("q2", rule))
        results = evaluator.evaluate_form(form, EvaluationContext(answers={"q1": "yes"}))
        assert results["q2"].effect == "hide"
        assert results["q2"].matched is True

    def test_location_var_in_form_evaluation(
        self, evaluator: RuleEvaluator, location_var_rule: DependencyRule
    ) -> None:
        """evaluate_form works with LocationVarCondition rules."""
        form = _simple_form(_field("q1"), _field("q2", location_var_rule))
        results = evaluator.evaluate_form(
            form, EvaluationContext(location_vars={"store_type": "flagship"})
        )
        assert results["q2"].effect == "show"
        assert results["q2"].matched is True

    def test_empty_form_no_results(self, evaluator: RuleEvaluator) -> None:
        """Form with no depends_on fields → empty results dict."""
        form = _simple_form(_field("q1"), _field("q2"))
        results = evaluator.evaluate_form(form, EvaluationContext())
        assert results == {}

    def test_numeric_coercion_string_vs_number(self, evaluator: RuleEvaluator) -> None:
        """Numeric coercion: string "5" compared with number 5 via GT."""
        rule = DependencyRule(
            conditions=[FieldRefCondition(field_id="q1", operator=ConditionOperator.GT, value=3)],
        )
        ctx = EvaluationContext(answers={"q1": "5"})  # string answer
        assert evaluator.evaluate(rule, ctx) == "show"
