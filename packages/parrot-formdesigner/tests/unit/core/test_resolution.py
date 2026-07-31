"""Unit tests for build-time rule-reference resolution (FEAT-393, TASK-1997
— Module 3): ``resolve_rule_references``, ``find_field_by_uid``, and
``resolve_answer``.
"""
from __future__ import annotations

import uuid

import pytest
from parrot_formdesigner.core.constraints import (
    ConditionOperator,
    DependencyOperation,
    DependencyRule,
    FieldCondition,
    PostDependency,
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
    FormSubsection,
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


def test_preset_condition_field_uid_validated_against_known_uids():
    """FEAT-393 code review regression: a condition whose field_uid is
    ALREADY set (client-supplied, or a stale/foreign UID) must still be
    validated against the form's known UIDs — a bare
    `if cond.field_uid is not None: return` short-circuit previously let a
    dangling/foreign field_uid smuggle straight past resolution, unlike
    every other reference kind (operands/target), which always revalidate
    even when already UID-shaped."""
    dangling_uid = uuid.uuid4()
    field = _field(
        "a",
        depends_on=DependencyRule(
            conditions=[
                FieldCondition(field_uid=dangling_uid, operator=ConditionOperator.EQ, value="x")
            ],
        ),
    )
    form = _form([FormSection(section_id="s", fields=[field])])
    with pytest.raises(ValueError, match="references unknown field_uid"):
        resolve_rule_references(form)


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


def test_resolves_rules_owned_by_deeply_nested_fields():
    """Code review follow-up: resolve_rule_references must resolve rules
    owned by (or referencing) fields nested at every tree level the spec
    calls out — a GROUP's children, an ARRAY's item_template, and a
    subsection — not just top-level section fields. iter_fields_recursive()
    (which resolve_rule_references walks) is documented to reach the full
    tree, but no test previously exercised a depends_on/post_depends
    condition actually OWNED BY or REFERENCING a field at each of these
    nesting levels simultaneously."""
    trigger = _field("trigger")

    # A GROUP-child field's depends_on references the top-level trigger.
    group_child = _field(
        "group_child",
        depends_on=DependencyRule(
            conditions=[FieldCondition(field_id="trigger", operator=ConditionOperator.EQ, value="x")],
        ),
    )
    group = _field("group", field_type=FieldType.GROUP, children=[group_child])

    # An ARRAY's item_template field's depends_on references the GROUP child.
    item_template = _field(
        "item_field",
        depends_on=DependencyRule(
            conditions=[FieldCondition(field_id="group_child", operator=ConditionOperator.EQ, value="y")],
        ),
    )
    array_field = _field("arr", field_type=FieldType.ARRAY, item_template=item_template)

    # A subsection field's post_depends targets the ARRAY's item_template.
    sub_field = _field(
        "sub_field",
        post_depends=[
            PostDependency(
                target="item_field",
                effect="calc",
                operation=DependencyOperation(op="copy", operands=["trigger"], target="item_field"),
            )
        ],
    )
    subsection = FormSubsection(subsection_id="sub", fields=[sub_field])

    form = _form([
        FormSection(section_id="s", fields=[trigger, group, array_field, subsection])
    ])
    resolve_rule_references(form)

    fields_by_id = {f.field_id: f for f in form.iter_fields_recursive()}
    resolved_group_child = fields_by_id["group_child"]
    resolved_item_field = fields_by_id["item_field"]
    resolved_sub_field = fields_by_id["sub_field"]

    assert resolved_group_child.depends_on.conditions[0].field_uid == fields_by_id["trigger"].field_uid
    assert resolved_item_field.depends_on.conditions[0].field_uid == resolved_group_child.field_uid
    assert resolved_sub_field.post_depends[0].target == str(resolved_item_field.field_uid)
    assert resolved_sub_field.post_depends[0].operation.operands == [str(fields_by_id["trigger"].field_uid)]
    assert resolved_sub_field.post_depends[0].operation.target == str(resolved_item_field.field_uid)


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
