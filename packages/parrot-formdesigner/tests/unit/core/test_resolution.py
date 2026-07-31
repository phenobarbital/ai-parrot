"""Unit tests for build-time rule-reference resolution (FEAT-393, TASK-1997
— Module 3): ``resolve_rule_references``, ``find_field_by_uid``, and
``resolve_answer``.
"""
from __future__ import annotations

import uuid

import pytest
from parrot_formdesigner.core.constraints import (
    ConditionOperator,
    DependencyRule,
    FieldCondition,
)
from parrot_formdesigner.core.resolution import (
    find_field_by_uid,
    resolve_answer,
    resolve_rule_references,
)
from parrot_formdesigner.core.schema import (
    FormField,
    FormSchema,
    FormSection,
)
from parrot_formdesigner.core.types import FieldType


def _field(fid: str, **kw) -> FormField:
    kw.setdefault("field_type", FieldType.TEXT)
    kw.setdefault("label", fid)
    return FormField(field_id=fid, **kw)


def _form(sections: list[FormSection], form_id: str = "f") -> FormSchema:
    return FormSchema(form_id=form_id, title="Test", sections=sections)


# form_with_rules / form_with_nested_fields fixtures moved to the
# package-wide tests/conftest.py (FEAT-393, TASK-2009 — Module 15 fixture
# consolidation). Referenced below as normal pytest fixture parameters.


def test_resolves_depends_on_condition(form_with_rules: FormSchema):
    a = form_with_rules.sections[0].fields[0]
    b = form_with_rules.sections[0].fields[1]
    resolve_rule_references(form_with_rules)
    assert b.depends_on.conditions[0].field_uid == a.field_uid


def test_resolves_operands_and_targets(form_with_rules: FormSchema):
    a, b, c = form_with_rules.sections[0].fields
    resolve_rule_references(form_with_rules)
    op = b.depends_on.operations[0]
    assert op.operands == [str(a.field_uid)]
    assert op.target == str(c.field_uid)


def test_resolves_post_depends(form_with_rules: FormSchema):
    a, b, c = form_with_rules.sections[0].fields
    resolve_rule_references(form_with_rules)
    post = b.post_depends[0]
    assert post.target == str(c.field_uid)
    assert post.conditions[0].field_uid == a.field_uid
    assert post.operation.operands == [str(a.field_uid)]
    assert post.operation.target == str(c.field_uid)


def test_unknown_reference_errors(form_with_rules: FormSchema):
    b = form_with_rules.sections[0].fields[1]
    b.depends_on.conditions[0].field_id = "zzz"
    with pytest.raises(ValueError, match="references unknown field_id"):
        resolve_rule_references(form_with_rules)


def test_empty_reference_errors():
    field = _field(
        "a",
        depends_on=DependencyRule(
            conditions=[FieldCondition(field_id="", operator=ConditionOperator.EQ, value="x")],
        ),
    )
    form = _form([FormSection(section_id="s", fields=[field])])
    with pytest.raises(ValueError, match="empty field reference"):
        resolve_rule_references(form)


def test_duplicate_field_id_blocks_resolution():
    field_a = _field("dup")
    field_b = _field("dup")
    # model_copy bypasses the FormSchema-level uniqueness validator, but
    # resolve_rule_references does its own duplicate check independently.
    form = _form([FormSection(section_id="s", fields=[field_a])]).model_copy(
        update={"sections": [FormSection(section_id="s", fields=[field_a, field_b])]}
    )
    with pytest.raises(ValueError, match="duplicate field_id"):
        resolve_rule_references(form)


def test_resolution_idempotent(form_with_rules: FormSchema):
    resolve_rule_references(form_with_rules)
    b = form_with_rules.sections[0].fields[1]
    before_cond_uid = b.depends_on.conditions[0].field_uid
    before_op_operands = list(b.depends_on.operations[0].operands)
    before_op_target = b.depends_on.operations[0].target

    resolve_rule_references(form_with_rules)

    assert b.depends_on.conditions[0].field_uid == before_cond_uid
    assert b.depends_on.operations[0].operands == before_op_operands
    assert b.depends_on.operations[0].target == before_op_target


def test_non_field_sources_skipped():
    """source='location_variable' conditions keep key-based addressing, untouched."""
    field = _field(
        "a",
        depends_on=DependencyRule(
            conditions=[
                FieldCondition(
                    operator=ConditionOperator.EQ,
                    value="x",
                    source="location_variable",
                    key="geofence_status",
                )
            ],
        ),
    )
    form = _form([FormSection(section_id="s", fields=[field])])
    resolve_rule_references(form)
    cond = form.sections[0].fields[0].depends_on.conditions[0]
    assert cond.field_uid is None
    assert cond.key == "geofence_status"


def test_find_field_by_uid_nested(form_with_nested_fields: FormSchema):
    child = next(
        f for f in form_with_nested_fields.iter_fields_recursive() if f.field_id == "child"
    )
    item = next(
        f for f in form_with_nested_fields.iter_fields_recursive() if f.field_id == "item"
    )
    in_sub = next(
        f for f in form_with_nested_fields.iter_fields_recursive() if f.field_id == "in_sub"
    )

    found_child = find_field_by_uid(form_with_nested_fields, child.field_uid)
    found_item = find_field_by_uid(form_with_nested_fields, item.field_uid)
    found_sub = find_field_by_uid(form_with_nested_fields, in_sub.field_uid)

    assert found_child is not None and found_child[0].field_id == "child"
    assert found_item is not None and found_item[0].field_id == "item"
    assert found_sub is not None and found_sub[0].field_id == "in_sub"


def test_find_field_by_uid_unknown_returns_none(form_with_nested_fields: FormSchema):
    assert find_field_by_uid(form_with_nested_fields, uuid.uuid4()) is None


def test_resolve_answer_reads_by_field_id(form_with_rules: FormSchema):
    a = form_with_rules.sections[0].fields[0]
    answers = {"a": "hello", "b": "world"}
    assert resolve_answer(form_with_rules, a.field_uid, answers) == "hello"


def test_resolve_answer_unknown_field_returns_none(form_with_rules: FormSchema):
    assert resolve_answer(form_with_rules, uuid.uuid4(), {"a": "hello"}) is None
