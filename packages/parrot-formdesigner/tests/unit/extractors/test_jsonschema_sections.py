"""JsonSchemaRenderer to JsonSchemaExtractor fidelity tests for FEAT-650."""

from __future__ import annotations

import pytest

from parrot_formdesigner.core import (
    ConditionOperator,
    DependencyRule,
    FieldCondition,
    FieldType,
    FormField,
    FormSchema,
    FormSection,
    FormSubsection,
)
from parrot_formdesigner.extractors import JsonSchemaExtractor
from parrot_formdesigner.renderers import JsonSchemaRenderer


@pytest.fixture
def form() -> FormSchema:
    """Build a form covering section, subsection, and field extensions."""
    return FormSchema(
        form_id="rt",
        title={"en": "RT"},
        tenant="navigator",
        sections=[
            FormSection(
                section_id="s1",
                title={"en": "One"},
                description={"en": "d1"},
                fields=[
                    FormField(
                        field_id="name",
                        field_type=FieldType.TEXT,
                        label={"en": "Name"},
                        placeholder={"en": "ph"},
                        default="x",
                        description={"en": "fd"},
                    ),
                    FormField(
                        field_id="ro",
                        field_type=FieldType.NUMBER,
                        label={"en": "RO"},
                        read_only=True,
                    ),
                    FormSubsection(
                        subsection_id="s1a",
                        title={"en": "Sub"},
                        fields=[
                            FormField(
                                field_id="tags",
                                field_type=FieldType.MULTI_SELECT,
                                label={"en": "Tags"},
                                options=[
                                    {"value": "a", "label": "A"},
                                    {"value": "b", "label": "B", "disabled": True},
                                ],
                            )
                        ],
                    ),
                ],
            ),
            FormSection(
                section_id="s2",
                title={"en": "Two"},
                fields=[
                    FormField(
                        field_id="color",
                        field_type=FieldType.SELECT,
                        label={"en": "Color"},
                        options=[{"value": "r", "label": "Red"}],
                    )
                ],
            ),
        ],
    )


async def _roundtrip(form: FormSchema) -> FormSchema:
    """Render and extract a form through the JSON Schema dialect."""
    rendered = await JsonSchemaRenderer().render(form)
    return JsonSchemaExtractor().extract(rendered.content, form_id=form.form_id)


@pytest.mark.asyncio
async def test_section_tree_rebuilt(form: FormSchema) -> None:
    """Recover section and subsection order from renderer metadata."""
    back = await _roundtrip(form)
    assert [section.section_id for section in back.sections] == ["s1", "s2"]
    section = back.sections[0]
    assert [getattr(item, "field_id", getattr(item, "subsection_id", None)) for item in section.fields] == [
        "name",
        "ro",
        "s1a",
    ]
    subsection = section.fields[2]
    assert isinstance(subsection, FormSubsection)
    assert [field.field_id for field in subsection.fields] == ["tags"]


@pytest.mark.asyncio
async def test_field_attributes_recovered(form: FormSchema) -> None:
    """Recover placeholder, default, description, read-only, and options metadata."""
    back = {field.field_id: field for field in (await _roundtrip(form)).iter_fields_recursive()}
    assert back["name"].placeholder == "ph"
    assert back["name"].default == "x"
    assert back["name"].description == "fd"
    assert back["ro"].read_only is True
    assert back["color"].options is not None
    assert [option.label for option in back["color"].options] == ["Red"]
    assert back["tags"].field_type == FieldType.MULTI_SELECT
    assert back["tags"].options is not None
    assert len(back["tags"].options) == 2
    assert back["tags"].options[1].disabled is True


@pytest.mark.asyncio
async def test_section_depends_on_roundtrips() -> None:
    """Recover a section dependency emitted as a model and validated as JSON."""
    form = FormSchema(
        form_id="dependent",
        title="Dependent",
        sections=[
            FormSection(
                section_id="details",
                title="Details",
                depends_on=DependencyRule(
                    conditions=[
                        FieldCondition(
                            field_id="enabled",
                            operator=ConditionOperator.EQ,
                            value=True,
                        )
                    ]
                ),
                fields=[
                    FormField(field_id="enabled", field_type=FieldType.BOOLEAN, label="Enabled"),
                    FormField(field_id="details_value", field_type=FieldType.TEXT, label="Value"),
                ],
            )
        ],
    )
    back = await _roundtrip(form)
    dependency = back.sections[0].depends_on
    assert dependency is not None
    assert dependency.conditions[0].field_id == "enabled"
    assert dependency.conditions[0].operator == ConditionOperator.EQ
    assert dependency.conditions[0].value is True


def test_pydantic_input_keeps_single_fields_section() -> None:
    """Keep schemas without x-section metadata on the legacy fields section."""
    from pydantic import BaseModel

    class Model(BaseModel):
        a: str
        b: int = 1

    back = JsonSchemaExtractor().extract(Model.model_json_schema())
    assert [section.section_id for section in back.sections] == ["fields"]
    assert [field.field_id for field in back.iter_all_fields()] == ["a", "b"]
