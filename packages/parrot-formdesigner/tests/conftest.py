"""Package-wide shared fixtures for parrot-formdesigner tests (FEAT-393,
Module 15 / TASK-2009).

These three fixtures were originally created locally by earlier tasks in
this feature (TASK-1997's `tests/unit/core/test_resolution.py`, TASK-2008's
`tests/unit/migrations/test_feat393_migrations.py`) — this file
consolidates them here so any test in the suite can use them without a
local duplicate definition.
"""

from __future__ import annotations

import pytest
from parrot_formdesigner.core.constraints import (
    ConditionOperator,
    DependencyOperation,
    DependencyRule,
    FieldCondition,
    PostDependency,
)
from parrot_formdesigner.core.schema import (
    FormField,
    FormSchema,
    FormSection,
    FormSubsection,
)
from parrot_formdesigner.core.types import FieldType


def _field(fid: str, **kw) -> FormField:
    """Build a minimal FormField — shared helper for the fixtures below."""
    kw.setdefault("field_type", FieldType.TEXT)
    kw.setdefault("label", fid)
    return FormField(field_id=fid, **kw)


def _form(sections: list[FormSection], form_id: str = "f") -> FormSchema:
    """Build a minimal FormSchema — shared helper for the fixtures below."""
    return FormSchema(form_id=form_id, title="Test", sections=sections)


@pytest.fixture
def form_with_nested_fields() -> FormSchema:
    """FormSchema with sections, a subsection, a GROUP (children) and an
    ARRAY (item_template) — exercises the full-tree traversal (spec §4)."""
    group = _field(
        "group", field_type=FieldType.GROUP, children=[_field("child")]
    )
    array_field = _field(
        "arr", field_type=FieldType.ARRAY, item_template=_field("item")
    )
    subsection = FormSubsection(subsection_id="sub", fields=[_field("in_sub")])
    return _form([
        FormSection(section_id="s", fields=[group, array_field, subsection])
    ])


@pytest.fixture
def form_with_rules() -> FormSchema:
    """FormSchema whose depends_on / post_depends / operations reference
    fields by authored field_id, for resolution-pass tests (spec §4).

    Field order: a, b, c — b depends on a; b's post_depends and
    operations target c.
    """
    a = _field("a")
    b = _field(
        "b",
        depends_on=DependencyRule(
            conditions=[FieldCondition(field_id="a", operator=ConditionOperator.EQ, value="x")],
            operations=[DependencyOperation(op="copy", operands=["a"], target="c")],
        ),
        post_depends=[
            PostDependency(
                target="c",
                effect="calc",
                conditions=[FieldCondition(field_id="a", operator=ConditionOperator.EQ, value="x")],
                operation=DependencyOperation(op="copy", operands=["a"], target="c"),
            )
        ],
    )
    c = _field("c")
    return _form([FormSection(section_id="s", fields=[a, b, c])])


@pytest.fixture
def legacy_schema_json() -> dict:
    """Stored-form JSON WITHOUT uid fields and WITH field_id-keyed rules,
    for migration tests (spec §4).

    Two fields (country, state); state's depends_on references country by
    authored field_id — exercises both element-UID injection and
    rule-reference rewriting in a single fixture.
    """
    return {
        "form_id": "legacy-form",
        "title": "Legacy Form",
        "sections": [
            {
                "section_id": "s1",
                "fields": [
                    {
                        "field_id": "country",
                        "field_type": "select",
                        "label": "Country",
                    },
                    {
                        "field_id": "state",
                        "field_type": "text",
                        "label": "State",
                        "depends_on": {
                            "conditions": [
                                {
                                    "field_id": "country",
                                    "operator": "eq",
                                    "value": "US",
                                }
                            ],
                            "logic": "and",
                            "effect": "show",
                        },
                    },
                ],
            }
        ],
    }
