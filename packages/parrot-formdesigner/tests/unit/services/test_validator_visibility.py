"""A field the form never displayed must not be required on submit.

`FormValidator.validate()` walked every field in every section and enforced
the schema's static `required` flag, with no notion of conditional
visibility — neither `FormField.depends_on` nor `FormSection.depends_on`.
On the imported Epson Visit Form that rejected a correctly-filled
submission with 177 errors naming questions the rep was never shown.
"""

import pytest

from parrot_formdesigner.core import (
    DependencyRule,
    FieldCondition,
    FieldType,
    FormField,
    FormSchema,
    FormSection,
    resolve_rule_references,
)
from parrot_formdesigner.services import FormValidator


def _field(field_id: str, **kwargs) -> FormField:
    return FormField(
        field_id=field_id, field_type=FieldType.TEXT, label=field_id, **kwargs
    )


def _rule(field_id: str, value: str = "yes", effect: str = "show") -> DependencyRule:
    return DependencyRule(
        conditions=[FieldCondition(field_id=field_id, operator="eq", value=value)],
        logic="and",
        effect=effect,
    )


def _form(*sections: FormSection) -> FormSchema:
    return resolve_rule_references(
        FormSchema(form_id="t", title="T", sections=list(sections))
    )


async def test_required_field_in_a_hidden_section_is_not_demanded() -> None:
    form = _form(
        FormSection(section_id="open", fields=[_field("driver")]),
        FormSection(
            section_id="gated",
            fields=[_field("inside", required=True)],
            depends_on=_rule("driver"),
        ),
    )

    result = await FormValidator().validate(form, {"driver": "no"})

    assert result.is_valid, result.errors


async def test_required_field_in_a_shown_section_is_still_demanded() -> None:
    form = _form(
        FormSection(section_id="open", fields=[_field("driver")]),
        FormSection(
            section_id="gated",
            fields=[_field("inside", required=True)],
            depends_on=_rule("driver"),
        ),
    )

    result = await FormValidator().validate(form, {"driver": "yes"})

    assert not result.is_valid
    assert "inside" in result.errors


async def test_field_hidden_by_its_own_rule_is_not_demanded() -> None:
    """The other half of the same bug — no section involved."""
    form = _form(FormSection(section_id="s", fields=[
        _field("driver"),
        _field("inside", required=True, depends_on=_rule("driver")),
    ]))

    result = await FormValidator().validate(form, {"driver": "no"})

    assert result.is_valid, result.errors


async def test_a_plain_required_field_still_errors() -> None:
    """No rules anywhere: behaviour must be exactly what it always was."""
    form = _form(FormSection(section_id="s", fields=[_field("plain", required=True)]))

    result = await FormValidator().validate(form, {})

    assert not result.is_valid
    assert "plain" in result.errors


async def test_a_hidden_field_that_did_arrive_is_still_validated() -> None:
    """Relaxing `required` must not become "skip validation entirely"."""
    form = _form(
        FormSection(section_id="open", fields=[_field("driver")]),
        FormSection(
            section_id="gated",
            fields=[FormField(
                field_id="num", field_type=FieldType.INTEGER, label="num",
                required=True,
            )],
            depends_on=_rule("driver"),
        ),
    )

    result = await FormValidator().validate(
        form, {"driver": "no", "num": "not-a-number"}
    )

    assert not result.is_valid
    assert "num" in result.errors
