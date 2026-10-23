"""Tests for FormValidator validation-trace plumbing (FEAT-732)."""

from __future__ import annotations

from parrot_formdesigner.core import DependencyRule, FieldCondition, resolve_rule_references
from parrot_formdesigner.core.audit_trail import AuditDetail, CheckId, CheckOutcome, SkipReason
from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.services.validation_trace import ValidationTraceCollector, schema_fingerprint
from parrot_formdesigner.services.validators import FormValidator
from parrot_formdesigner.version import __version__


def _field(field_id: str, **kwargs: object) -> FormField:
    """Build a text field used by the trace tests."""
    return FormField(field_id=field_id, field_type=FieldType.TEXT, label=field_id, **kwargs)


def _rule(field_id: str, value: str = "yes") -> DependencyRule:
    """Build a visibility rule controlled by a text field."""
    return DependencyRule(
        conditions=[FieldCondition(field_id=field_id, operator="eq", value=value)],
        logic="and",
        effect="show",
    )


def _form(*sections: FormSection) -> FormSchema:
    """Build and resolve a form with deterministic rule references."""
    return resolve_rule_references(FormSchema(form_id="trace", title="Trace", sections=list(sections)))


def _collector(detail: AuditDetail = AuditDetail.SUMMARY) -> ValidationTraceCollector:
    """Build the explicit collector passed to the validator."""
    return ValidationTraceCollector(detail=detail, locale="en")


def _basic_form() -> FormSchema:
    """Build a clean form containing a required answer."""
    return _form(FormSection(section_id="main", fields=[_field("answer", required=True)]))


async def test_no_collector_no_trace() -> None:
    """The original validation path has no trace handoff."""
    result = await FormValidator().validate(_basic_form(), {"answer": "ok"})

    assert result.is_valid
    assert result.trace is None


async def test_trace_sealed_with_fingerprint_and_version() -> None:
    """A collector is sealed onto the result with stable metadata."""
    form = _basic_form()
    result = await FormValidator().validate(form, {"answer": "ok"}, trace=_collector())

    assert result.trace is not None
    assert result.trace.schema_fingerprint == schema_fingerprint(form)
    assert result.trace.ruleset_version == __version__


async def test_clean_form_records_both_form_checks_pass() -> None:
    """Successful validation records both form-level checks."""
    result = await FormValidator().validate(_basic_form(), {"answer": "ok"}, trace=_collector())

    assert result.trace is not None
    assert [(record.check, record.outcome) for record in result.trace.form_checks] == [
        (CheckId.FORM_CIRCULAR_DEPENDENCIES, CheckOutcome.PASS),
        (CheckId.FORM_RULE_INTEGRITY, CheckOutcome.PASS),
    ]


async def test_circular_early_return_seals_trace() -> None:
    """Circular dependencies seal only form-level evidence before returning."""
    first = _field("first", depends_on=_rule("second"))
    second = _field("second", depends_on=_rule("first"))
    form = _form(FormSection(section_id="main", fields=[first, second]))

    result = await FormValidator().validate(form, {}, trace=_collector())

    assert result.trace is not None
    assert not result.is_valid
    assert "__circular__" in result.errors
    assert result.trace.fields == []
    assert [(record.check, record.outcome, record.skip_reason) for record in result.trace.form_checks] == [
        (CheckId.FORM_CIRCULAR_DEPENDENCIES, CheckOutcome.FAIL, None),
        (CheckId.FORM_RULE_INTEGRITY, CheckOutcome.SKIP, SkipReason.EARLY_RETURN),
    ]


async def test_rules_early_return_seals_trace() -> None:
    """Invalid rule ordering seals the failed form-level integrity check."""
    early = _field("early", depends_on=_rule("later"))
    form = FormSchema(
        form_id="invalid-rules",
        title="Invalid rules",
        sections=[FormSection(section_id="main", fields=[early, _field("later")])],
    )

    result = await FormValidator().validate(form, {}, trace=_collector())

    assert result.trace is not None
    assert "__rules__" in result.errors
    assert result.trace.fields == []
    assert result.trace.form_checks[-1].check is CheckId.FORM_RULE_INTEGRITY
    assert result.trace.form_checks[-1].outcome is CheckOutcome.FAIL


async def test_relaxed_required_is_recorded_summary() -> None:
    """A hidden required field exposes its resolved flags in a summary trace."""
    form = _form(
        FormSection(
            section_id="main", fields=[_field("driver"), _field("hidden", required=True, depends_on=_rule("driver"))]
        )
    )
    result = await FormValidator().validate(form, {"driver": "no"}, trace=_collector())

    assert result.trace is not None
    hidden = next(field for field in result.trace.fields if field.field_id == "hidden")
    assert not hidden.visible_effective
    assert not hidden.required_effective
    assert hidden.records == []


async def test_relaxed_required_is_recorded_full() -> None:
    """A full trace explains a hidden required field's requirement relaxation."""
    form = _form(
        FormSection(
            section_id="main", fields=[_field("driver"), _field("hidden", required=True, depends_on=_rule("driver"))]
        )
    )
    result = await FormValidator().validate(form, {"driver": "no"}, trace=_collector(AuditDetail.FULL))

    assert result.trace is not None
    hidden = next(field for field in result.trace.fields if field.field_id == "hidden")
    required = next(record for record in hidden.records if record.check is CheckId.FIELD_REQUIRED)
    assert required.outcome is CheckOutcome.SKIP
    assert required.skip_reason is SkipReason.NOT_DISPLAYED


async def test_every_visited_field_has_resolution_records() -> None:
    """Every field reached by validate has both rule-resolution records."""
    result = await FormValidator().validate(_basic_form(), {"answer": "ok"}, trace=_collector(AuditDetail.FULL))

    assert result.trace is not None
    for field in result.trace.fields:
        assert {record.check for record in field.records} >= {
            CheckId.RESOLUTION_VISIBLE,
            CheckId.RESOLUTION_REQUIRED,
        }


async def test_validate_field_signature_unchanged() -> None:
    """Adding the optional collector preserves validate_field's return type."""
    errors = await FormValidator().validate_field(_field("answer", required=True), None)

    assert errors == ["answer is required"]
