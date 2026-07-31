"""Tests for FEAT-234 TASK-1526: rule-integrity pass + extended cycle detection."""

import uuid

import pytest

from parrot_formdesigner.core import (
    ConditionOperator,
    DependencyOperation,
    DependencyRule,
    FieldCondition,
    FieldType,
    FormField,
    FormSchema,
    FormSection,
    FormSubsection,
    PostDependency,
    resolve_rule_references,
)
from parrot_formdesigner.services import FormValidator


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _field(
    field_id: str,
    field_type: FieldType = FieldType.TEXT,
    *,
    depends_on: DependencyRule | None = None,
    post_depends: list[PostDependency] | None = None,
) -> FormField:
    return FormField(
        field_id=field_id,
        field_type=field_type,
        label=field_id,
        depends_on=depends_on,
        post_depends=post_depends,
    )


def _form(*fields: FormField) -> FormSchema:
    """Build a FormSchema and resolve its rule references (FEAT-393).

    FormValidator reads conditions/operations via field_uid — every test
    form must go through resolve_rule_references() before validation, same
    as any real build boundary.
    """
    form = FormSchema(
        form_id="test",
        title="Test",
        sections=[FormSection(section_id="s1", fields=list(fields))],
    )
    return resolve_rule_references(form)


def _cond(field_id: str, op: ConditionOperator = ConditionOperator.EQ, value: str = "x") -> FieldCondition:
    return FieldCondition(field_id=field_id, operator=op, value=value)


@pytest.fixture
def validator() -> FormValidator:
    return FormValidator()


# ---------------------------------------------------------------------------
# TASK-1526 — rule-integrity: unknown references
# ---------------------------------------------------------------------------


class TestUnknownReferences:
    def test_depends_on_references_unknown_field(self, validator: FormValidator) -> None:
        """A resolved condition whose field_uid matches no field in the
        form (e.g. orphaned by a later edit) is caught by validate_rules
        itself. Genuinely dangling AUTHORED field_id references are instead
        caught earlier, at resolve_rule_references() time (FEAT-393) — see
        test_resolution.py::test_unknown_reference_errors — so this test
        constructs an already-"resolved" (field_uid-only) condition
        directly rather than going through the auto-resolving _form()."""
        orphan_uid = uuid.uuid4()
        cond = FieldCondition(field_uid=orphan_uid, operator=ConditionOperator.EQ, value="x")
        f = _field("f1", depends_on=DependencyRule(conditions=[cond]))
        form = FormSchema(
            form_id="test", title="Test", sections=[FormSection(section_id="s1", fields=[f])]
        )
        errors = validator.validate_rules(form)
        assert any("unknown field" in e for e in errors), errors

    def test_post_depends_targets_unknown_field(self, validator: FormValidator) -> None:
        """A dangling ``target`` (never resolved to a real field_uid) is
        caught by validate_rules itself. Built without the auto-resolving
        _form() — resolve_rule_references() would already raise for a
        genuinely-authored dangling target (FEAT-393)."""
        f = _field("f1", post_depends=[PostDependency(target="ghost", effect="show")])
        form = FormSchema(
            form_id="test", title="Test", sections=[FormSection(section_id="s1", fields=[f])]
        )
        errors = validator.validate_rules(form)
        assert any("ghost" in e for e in errors)

    def test_operation_references_unknown_operand(self, validator: FormValidator) -> None:
        """Same as above, for an operation operand — built without the
        auto-resolving _form() (FEAT-393)."""
        f1 = _field("f1", field_type=FieldType.NUMBER)
        f2 = _field(
            "f2",
            depends_on=DependencyRule(
                conditions=[FieldCondition(field_uid=f1.field_uid, operator=ConditionOperator.EQ, value="x")],
                operations=[DependencyOperation(op="copy", operands=["phantom"], target="f2")],
            ),
        )
        form = FormSchema(
            form_id="test", title="Test", sections=[FormSection(section_id="s1", fields=[f1, f2])]
        )
        errors = validator.validate_rules(form)
        assert any("phantom" in e for e in errors)

    def test_post_depends_condition_references_unknown(self, validator: FormValidator) -> None:
        """Same orphaned-field_uid scenario as
        test_depends_on_references_unknown_field, for a post_depends
        condition (FEAT-393 — see that test's docstring for why this
        constructs a "resolved" condition directly)."""
        orphan_uid = uuid.uuid4()
        cond = FieldCondition(field_uid=orphan_uid, operator=ConditionOperator.EQ, value="x")
        f1 = _field("f1")
        f2 = _field(
            "f2",
            post_depends=[
                PostDependency(target="f3", effect="show", conditions=[cond])
            ],
        )
        f3 = _field("f3")
        form = resolve_rule_references(
            FormSchema(
                form_id="test",
                title="Test",
                sections=[FormSection(section_id="s1", fields=[f1, f2, f3])],
            )
        )
        errors = validator.validate_rules(form)
        assert any("unknown field" in e for e in errors), errors


# ---------------------------------------------------------------------------
# TASK-1526 — rule-integrity: ordering violations
# ---------------------------------------------------------------------------


class TestOrderingViolations:
    def test_depends_on_referencing_later_field(self, validator: FormValidator) -> None:
        """depends_on must only reference fields declared earlier."""
        f1 = _field("f1")
        f2 = _field(
            "f2",
            depends_on=DependencyRule(conditions=[_cond("f3")]),
        )
        f3 = _field("f3")
        form = _form(f1, f2, f3)
        errors = validator.validate_rules(form)
        assert any("f3" in e and "earlier" in e.lower() for e in errors), errors

    def test_post_depends_targeting_earlier_field(self, validator: FormValidator) -> None:
        """post_depends.target must only reference fields declared later."""
        f1 = _field("f1")
        f2 = _field(
            "f2",
            post_depends=[PostDependency(target="f1", effect="show")],
        )
        f3 = _field("f3")
        form = _form(f1, f2, f3)
        errors = validator.validate_rules(form)
        assert any("f1" in e and "later" in e.lower() for e in errors), errors

    def test_valid_pre_post_ordering_passes(self, validator: FormValidator) -> None:
        """A form with correct pre+post ordering has no rule errors."""
        f1 = _field("f1", field_type=FieldType.TEXT)
        f2 = _field(
            "f2",
            depends_on=DependencyRule(conditions=[_cond("f1")]),
        )
        f3 = _field(
            "f3",
            post_depends=[PostDependency(target="f4", effect="cascade_clear")],
        )
        f4 = _field("f4")
        form = _form(f1, f2, f3, f4)
        errors = validator.validate_rules(form)
        assert errors == [], errors


# ---------------------------------------------------------------------------
# TASK-1526 — rule-integrity: operator/type compatibility
# ---------------------------------------------------------------------------


class TestOperatorTypeCompatibility:
    def test_numeric_operator_on_text_field_errors(self, validator: FormValidator) -> None:
        f1 = _field("f1", field_type=FieldType.TEXT)
        f2 = _field(
            "f2",
            depends_on=DependencyRule(
                conditions=[_cond("f1", ConditionOperator.GT, "5")]
            ),
        )
        form = _form(f1, f2)
        errors = validator.validate_rules(form)
        assert any("numeric operator" in e and "f1" in e for e in errors), errors

    def test_numeric_operator_on_number_field_passes(self, validator: FormValidator) -> None:
        f1 = _field("f1", field_type=FieldType.NUMBER)
        f2 = _field(
            "f2",
            depends_on=DependencyRule(
                conditions=[_cond("f1", ConditionOperator.GT, "5")]
            ),
        )
        form = _form(f1, f2)
        errors = validator.validate_rules(form)
        assert errors == [], errors

    def test_arithmetic_op_on_text_operand_errors(self, validator: FormValidator) -> None:
        f1 = _field("f1", field_type=FieldType.TEXT)
        f2 = _field("f2", field_type=FieldType.NUMBER)
        f3 = _field(
            "f3",
            depends_on=DependencyRule(
                conditions=[_cond("f2")],
                operations=[DependencyOperation(op="add", operands=["f1", "f2"], target="f3")],
            ),
        )
        form = _form(f1, f2, f3)
        errors = validator.validate_rules(form)
        assert any("arithmetic" in e and "f1" in e for e in errors), errors

    def test_eq_operator_on_text_field_passes(self, validator: FormValidator) -> None:
        """Non-numeric operators (eq/neq/in) on text fields are fine."""
        f1 = _field("f1", field_type=FieldType.TEXT)
        f2 = _field(
            "f2",
            depends_on=DependencyRule(
                conditions=[_cond("f1", ConditionOperator.EQ, "hello")]
            ),
        )
        form = _form(f1, f2)
        errors = validator.validate_rules(form)
        assert errors == [], errors


# ---------------------------------------------------------------------------
# TASK-1526 — extended cycle detection
# ---------------------------------------------------------------------------


class TestExtendedCycleDetection:
    def test_classic_depends_on_cycle(self, validator: FormValidator) -> None:
        """Pre-dependency cycle (A depends on B, B depends on A) is detected."""
        f1 = _field(
            "f1",
            depends_on=DependencyRule(conditions=[_cond("f2")]),
        )
        f2 = _field(
            "f2",
            depends_on=DependencyRule(conditions=[_cond("f1")]),
        )
        form = _form(f1, f2)
        cycles = validator._detect_circular_dependencies(form)
        assert len(cycles) > 0
        assert any("f1" in c and "f2" in c for c in cycles)

    def test_cycle_via_post_depends(self, validator: FormValidator) -> None:
        """A cycle introduced via post_depends (f1 -> f2 -> f1) is detected."""
        f1 = _field(
            "f1",
            post_depends=[PostDependency(target="f2", effect="show")],
        )
        f2 = _field(
            "f2",
            post_depends=[PostDependency(target="f1", effect="show")],
        )
        form = _form(f1, f2)
        cycles = validator._detect_circular_dependencies(form)
        # A mutual post_depends creates a cycle in the extended graph
        assert len(cycles) > 0

    def test_no_cycle_clean_form(self, validator: FormValidator) -> None:
        """A clean form with no circular dependencies returns empty list."""
        f1 = _field("f1")
        f2 = _field("f2", depends_on=DependencyRule(conditions=[_cond("f1")]))
        f3 = _field("f3", post_depends=[PostDependency(target="f4", effect="cascade_clear")])
        f4 = _field("f4")
        form = _form(f1, f2, f3, f4)
        cycles = validator._detect_circular_dependencies(form)
        assert cycles == []

    def test_legacy_form_unchanged(self, validator: FormValidator) -> None:
        """An existing form using only depends_on (no post_depends) validates as before."""
        f1 = _field("f1")
        f2 = _field("f2", depends_on=DependencyRule(conditions=[_cond("f1")]))
        form = _form(f1, f2)
        cycles = validator._detect_circular_dependencies(form)
        assert cycles == []
        rule_errors = validator.validate_rules(form)
        assert rule_errors == []


# ---------------------------------------------------------------------------
# Integration: clean form passes full validate()
# ---------------------------------------------------------------------------


class TestCleanFormPassesValidate:
    @pytest.mark.asyncio
    async def test_clean_form_with_pre_post_rules_validates(
        self, validator: FormValidator
    ) -> None:
        """A clean form with valid pre+post rules validates with no errors."""
        f1 = _field("f1", field_type=FieldType.TEXT)
        f2 = _field(
            "f2",
            depends_on=DependencyRule(conditions=[_cond("f1")], logic="xor"),
        )
        f3 = _field(
            "f3",
            post_depends=[PostDependency(target="f4", effect="cascade_clear")],
        )
        f4 = _field("f4")
        form = _form(f1, f2, f3, f4)
        result = await validator.validate(form, {"f1": "hello", "f2": "world"})
        assert "__circular__" not in result.errors
        assert "__rules__" not in result.errors

    @pytest.mark.asyncio
    async def test_form_with_invalid_rule_fails_validate(
        self, validator: FormValidator
    ) -> None:
        """A form with an ordering violation surfaces __rules__ error key."""
        f1 = _field("f1")
        # f1 depends_on f2 which is declared LATER — ordering violation
        f2 = _field("f2")
        f1_bad = FormField(
            field_id="f1",
            field_type=FieldType.TEXT,
            label="f1",
            depends_on=DependencyRule(conditions=[_cond("f2")]),
        )
        form = FormSchema(
            form_id="bad",
            title="Bad",
            sections=[FormSection(section_id="s1", fields=[f1_bad, f2])],
        )
        result = await validator.validate(form, {})
        assert "__rules__" in result.errors
