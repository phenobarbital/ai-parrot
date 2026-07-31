"""Unit tests for core model UIDs + canonical traversal + uniqueness
validator (FEAT-393, TASK-1996 — Module 2).

Covers ``FormField.field_uid``, ``FormSubsection.subsection_uid``,
``FormSection.section_uid``, the module-level ``walk_fields()`` /
``FormSchema.iter_fields_recursive()`` canonical traversal, the
``FormSchema._validate_unique_identity`` model validator, and
``RenderWarning.field_uid``.
"""
from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from parrot_formdesigner.core.schema import (
    FormField,
    FormSchema,
    FormSection,
    FormSubsection,
    RenderWarning,
    walk_fields,
)
from parrot_formdesigner.core.types import FieldType


def _field(fid: str, **kw) -> FormField:
    """Build a minimal FormField with sane defaults for label/type."""
    kw.setdefault("field_type", FieldType.TEXT)
    kw.setdefault("label", fid)
    return FormField(field_id=fid, **kw)


def _form(sections: list[FormSection], form_id: str = "f") -> FormSchema:
    return FormSchema(form_id=form_id, title="Test", sections=sections)


# ---------------------------------------------------------------------------
# field_uid / section_uid / subsection_uid — generation & acceptance
# ---------------------------------------------------------------------------


def test_field_uid_auto_generated():
    field = _field("a")
    assert isinstance(field.field_uid, uuid.UUID)


def test_field_uid_client_supplied_accepted():
    uid = uuid.uuid4()
    field = _field("a", field_uid=uid)
    assert field.field_uid == uid


def test_field_uid_client_supplied_string_coerced():
    uid = uuid.uuid4()
    field = _field("a", field_uid=str(uid))
    assert field.field_uid == uid


def test_section_subsection_uids_unique():
    section = FormSection(section_id="s1", fields=[_field("a")])
    subsection = FormSubsection(subsection_id="sub1", fields=[_field("b")])
    assert isinstance(section.section_uid, uuid.UUID)
    assert isinstance(subsection.subsection_uid, uuid.UUID)

    other_section = FormSection(section_id="s2", fields=[])
    assert section.section_uid != other_section.section_uid


# ---------------------------------------------------------------------------
# Duplicate rejection
# ---------------------------------------------------------------------------


def test_duplicate_field_uid_rejected():
    uid = uuid.uuid4()
    with pytest.raises(ValidationError, match="Duplicate field_uid"):
        _form([
            FormSection(
                section_id="s",
                fields=[_field("a", field_uid=uid), _field("b", field_uid=uid)],
            )
        ])


def test_duplicate_field_id_rejected():
    with pytest.raises(ValidationError, match="Duplicate field_id"):
        _form([
            FormSection(section_id="s", fields=[_field("dup"), _field("dup")])
        ])


def test_duplicate_section_uid_rejected():
    uid = uuid.uuid4()
    with pytest.raises(ValidationError, match="Duplicate section_uid"):
        _form([
            FormSection(section_id="s1", fields=[], section_uid=uid),
            FormSection(section_id="s2", fields=[], section_uid=uid),
        ])


def test_duplicate_subsection_uid_rejected():
    uid = uuid.uuid4()
    with pytest.raises(ValidationError, match="Duplicate subsection_uid"):
        _form([
            FormSection(
                section_id="s",
                fields=[
                    FormSubsection(subsection_id="sub1", fields=[], subsection_uid=uid),
                    FormSubsection(subsection_id="sub2", fields=[], subsection_uid=uid),
                ],
            )
        ])


def test_uniqueness_covers_nested_fields():
    """Duplicates hidden inside GROUP children AND inside a subsection are caught."""
    uid = uuid.uuid4()
    group = _field(
        "group",
        field_type=FieldType.GROUP,
        children=[_field("child", field_uid=uid)],
    )
    subsection = FormSubsection(
        subsection_id="sub1",
        fields=[_field("in_subsection", field_uid=uid)],
    )
    with pytest.raises(ValidationError, match="Duplicate field_uid"):
        _form([FormSection(section_id="s", fields=[group, subsection])])


def test_uniqueness_covers_array_item_template():
    uid = uuid.uuid4()
    array_field = _field(
        "arr",
        field_type=FieldType.ARRAY,
        item_template=_field("item", field_uid=uid),
    )
    other = _field("other", field_uid=uid)
    with pytest.raises(ValidationError, match="Duplicate field_uid"):
        _form([FormSection(section_id="s", fields=[array_field, other])])


def test_no_duplicates_validates_cleanly():
    """A form with distinct UIDs and field_ids everywhere validates fine."""
    group = _field(
        "group",
        field_type=FieldType.GROUP,
        children=[_field("child")],
    )
    subsection = FormSubsection(subsection_id="sub1", fields=[_field("in_sub")])
    form = _form([FormSection(section_id="s", fields=[group, subsection])])
    assert form is not None


# ---------------------------------------------------------------------------
# Canonical traversal — walk_fields() / iter_fields_recursive()
# ---------------------------------------------------------------------------


def test_walk_fields_order_deterministic():
    """Parent GROUP yields before its children; subsection fields in
    declaration order."""
    group = _field(
        "group",
        field_type=FieldType.GROUP,
        children=[_field("child1"), _field("child2")],
    )
    section = FormSection(section_id="s", fields=[group])
    ids = [f.field_id for f in walk_fields(section.fields)]
    assert ids == ["group", "child1", "child2"]


def test_walk_fields_recurses_subsections_group_and_array():
    subsection = FormSubsection(subsection_id="sub", fields=[_field("in_sub")])
    group = _field("group", field_type=FieldType.GROUP, children=[_field("child")])
    array_field = _field(
        "arr", field_type=FieldType.ARRAY, item_template=_field("item")
    )
    section = FormSection(section_id="s", fields=[subsection, group, array_field])
    ids = {f.field_id for f in walk_fields(section.fields)}
    assert ids == {"in_sub", "group", "child", "arr", "item"}


def test_iter_fields_recursive_matches_walk_fields():
    group = _field("group", field_type=FieldType.GROUP, children=[_field("child")])
    form = _form([FormSection(section_id="s", fields=[group])])
    ids = [f.field_id for f in form.iter_fields_recursive()]
    assert ids == ["group", "child"]


def test_iter_all_fields_does_not_recurse_nested():
    """iter_all_fields() (layout order) stays shallow — it must NOT see
    GROUP children or ARRAY item_template (that's iter_fields_recursive's job)."""
    group = _field("group", field_type=FieldType.GROUP, children=[_field("child")])
    form = _form([FormSection(section_id="s", fields=[group])])
    ids = [f.field_id for f in form.iter_all_fields()]
    assert ids == ["group"]


# ---------------------------------------------------------------------------
# RenderWarning.field_uid
# ---------------------------------------------------------------------------


def test_render_warning_field_uid_defaults_none():
    warning = RenderWarning(
        field_id="a", field_type="signature", renderer="pdf", reason="unsupported"
    )
    assert warning.field_uid is None


def test_render_warning_field_uid_accepted():
    uid = uuid.uuid4()
    warning = RenderWarning(
        field_id="a",
        field_uid=uid,
        field_type="signature",
        renderer="pdf",
        reason="unsupported",
    )
    assert warning.field_uid == uid
