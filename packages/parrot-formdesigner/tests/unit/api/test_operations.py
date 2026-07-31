"""Unit tests for ``parrot_formdesigner.api.operations`` (FEAT-393: UID addressing)."""

from __future__ import annotations

import uuid

import pytest

from parrot_formdesigner.api.operations import (
    AddField,
    AddSection,
    DuplicateField,
    MoveField,
    OperationError,
    OperationsEnvelope,
    RemoveField,
    UpdateField,
    UpdateFormMeta,
    UpdateSectionMeta,
    _apply_add_field,
    _apply_add_section,
    _apply_duplicate_field,
    _apply_move_field,
    _apply_remove_field,
    _apply_update_field,
    _apply_update_form_meta,
    _apply_update_section_meta,
)
from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection, FormSubsection
from parrot_formdesigner.core.types import FieldType


@pytest.fixture
def form() -> FormSchema:
    return FormSchema(
        form_id="t",
        version="1.0",
        title={"en": "T"},
        sections=[
            FormSection(
                section_id="s1",
                fields=[
                    FormField(
                        field_id="name",
                        field_type=FieldType.TEXT,
                        label={"en": "N"},
                    ),
                ],
            )
        ],
    )


# ---------------------------------------------------------------------------
# Discriminator
# ---------------------------------------------------------------------------


def test_envelope_discriminates_add_section():
    env = OperationsEnvelope.model_validate({
        "operations": [
            {
                "op": "add_section",
                "section": {"section_id": "s2", "fields": []},
                "position": 0,
            },
        ],
    })
    assert isinstance(env.operations[0], AddSection)


def test_envelope_discriminates_move_field_with_alias():
    section_uid = str(uuid.uuid4())
    field_uid = str(uuid.uuid4())
    env = OperationsEnvelope.model_validate({
        "operations": [
            {
                "op": "move_field",
                "from": {"section_uid": section_uid, "field_uid": field_uid},
                "to": {"section_uid": str(uuid.uuid4()), "position": 0},
            },
        ],
    })
    assert isinstance(env.operations[0], MoveField)
    assert env.operations[0].from_["section_uid"] == section_uid


def test_envelope_discriminates_all_ops(form):
    section_uid = str(form.sections[0].section_uid)
    field_uid = str(form.sections[0].fields[0].field_uid)
    payload = {
        "operations": [
            {
                "op": "add_section",
                "section": {"section_id": "s2", "fields": []},
            },
            {
                "op": "add_field",
                "section_uid": section_uid,
                "field": {
                    "field_id": "x",
                    "field_type": "text",
                    "label": {"en": "X"},
                },
            },
            {
                "op": "remove_field",
                "section_uid": section_uid,
                "field_uid": field_uid,
            },
            {
                "op": "update_field",
                "section_uid": section_uid,
                "field_uid": field_uid,
                "patch": {"required": True},
            },
            {
                "op": "update_section_meta",
                "section_uid": section_uid,
                "patch": {"x": 1},
            },
            {
                "op": "update_form_meta",
                "patch": {"x": 1},
            },
            {
                "op": "duplicate_field",
                "from": {"section_uid": section_uid, "field_uid": field_uid},
                "as_field_id": "name_copy",
            },
        ]
    }
    env = OperationsEnvelope.model_validate(payload)
    assert isinstance(env.operations[0], AddSection)
    assert isinstance(env.operations[1], AddField)
    assert isinstance(env.operations[2], RemoveField)
    assert isinstance(env.operations[3], UpdateField)
    assert isinstance(env.operations[4], UpdateSectionMeta)
    assert isinstance(env.operations[5], UpdateFormMeta)
    assert isinstance(env.operations[6], DuplicateField)


def test_operations_envelope_rejects_unknown_keys():
    with pytest.raises(Exception):  # noqa: B017 — Pydantic ValidationError (extra="forbid")
        OperationsEnvelope.model_validate({
            "operations": [],
            "unexpected_extra_key": True,
        })


# ---------------------------------------------------------------------------
# Per-op apply
# ---------------------------------------------------------------------------


def test_add_field_succeeds(form):
    op = AddField.model_validate({
        "op": "add_field",
        "section_uid": str(form.sections[0].section_uid),
        "field": {
            "field_id": "email",
            "field_type": "email",
            "label": {"en": "E"},
        },
    })
    out = _apply_add_field(form, op)
    assert {f.field_id for f in out.sections[0].fields} == {"name", "email"}


def test_add_field_client_uid_upsert_and_conflict(form):
    """add_field accepts a client-supplied field_uid (upsert origin);
    reusing an existing field_uid form-wide is rejected."""
    fresh_uid = uuid.uuid4()
    op = AddField.model_validate({
        "op": "add_field",
        "section_uid": str(form.sections[0].section_uid),
        "field": {
            "field_uid": str(fresh_uid),
            "field_id": "email",
            "field_type": "email",
            "label": {"en": "E"},
        },
    })
    out = _apply_add_field(form, op)
    added = next(f for f in out.sections[0].fields if f.field_id == "email")
    assert added.field_uid == fresh_uid

    # Reusing the same (now-registered) field_uid form-wide is a conflict.
    dup_op = AddField.model_validate({
        "op": "add_field",
        "section_uid": str(out.sections[0].section_uid),
        "field": {
            "field_uid": str(fresh_uid),
            "field_id": "phone",
            "field_type": "text",
            "label": {"en": "P"},
        },
    })
    with pytest.raises(OperationError):
        _apply_add_field(out, dup_op)


def test_add_field_duplicate_rejected(form):
    op = AddField.model_validate({
        "op": "add_field",
        "section_uid": str(form.sections[0].section_uid),
        "field": {
            "field_id": "name",
            "field_type": "text",
            "label": {"en": "Dup"},
        },
    })
    with pytest.raises(OperationError):
        _apply_add_field(form, op)


def test_add_field_unknown_section_rejected(form):
    op = AddField.model_validate({
        "op": "add_field",
        "section_uid": str(uuid.uuid4()),
        "field": {
            "field_id": "x",
            "field_type": "text",
            "label": {"en": "X"},
        },
    })
    with pytest.raises(OperationError):
        _apply_add_field(form, op)


def test_remove_field(form):
    section_uid = form.sections[0].section_uid
    field_uid = form.sections[0].fields[0].field_uid
    op = RemoveField(op="remove_field", section_uid=section_uid, field_uid=field_uid)
    out = _apply_remove_field(form, op)
    assert out.sections[0].fields == []


def test_remove_field_inside_subsection():
    """Regression test: fields inside a subsection are addressable
    (the old _field_index silently skipped FormSubsection items)."""
    inner_field = FormField(field_id="inner", field_type=FieldType.TEXT, label="Inner")
    subsection = FormSubsection(subsection_id="sub1", fields=[inner_field])
    form = FormSchema(
        form_id="t",
        title={"en": "T"},
        sections=[FormSection(section_id="s1", fields=[subsection])],
    )
    op = RemoveField(
        op="remove_field",
        section_uid=form.sections[0].section_uid,
        field_uid=inner_field.field_uid,
    )
    out = _apply_remove_field(form, op)
    assert out.sections[0].fields[0].fields == []


def test_remove_field_inside_group_children():
    """Regression test (code review follow-up): fields nested inside a
    GROUP's children are addressable by every batched operation, not just
    top-level section fields and one level into subsections. Mirrors the
    same fix already applied to EditToolkit's _replace_field_in_form —
    _locate_field previously could not reach a GROUP-child field at all,
    even though the field genuinely existed in the form."""
    child = FormField(field_id="child", field_type=FieldType.TEXT, label="Child")
    group = FormField(
        field_id="group", field_type=FieldType.GROUP, label="Group", children=[child]
    )
    form = FormSchema(
        form_id="t",
        title={"en": "T"},
        sections=[FormSection(section_id="s1", fields=[group])],
    )
    op = RemoveField(
        op="remove_field",
        section_uid=form.sections[0].section_uid,
        field_uid=child.field_uid,
    )
    out = _apply_remove_field(form, op)
    assert out.sections[0].fields[0].children == []


def test_move_field_duplicate_uid_nested_in_group_rejected():
    """Regression test (code review follow-up): _apply_move_field's
    destination-collision check must catch a duplicate field_uid nested
    inside a GROUP/ARRAY in the destination section, not just top-level
    fields — it now walks the full tree (walk_fields), not iter_fields()
    (subsection-flattening only)."""
    moving_field = FormField(field_id="moving", field_type=FieldType.TEXT, label="Moving")
    src_section = FormSection(section_id="src", fields=[moving_field])
    # Destination section has a GROUP whose child shares moving_field's UID
    # (simulating a client-forged duplicate — upsert-origin duplication).
    # model_copy bypasses FormSchema._validate_unique_identity so the
    # fixture itself can hold the (otherwise-rejected) duplicate — the
    # move_field collision check under test is what's expected to catch it.
    dup_child = moving_field.model_copy(update={"field_id": "dup"})
    group = FormField(
        field_id="group", field_type=FieldType.GROUP, label="Group", children=[dup_child]
    )
    dst_section = FormSection(section_id="dst", fields=[group])
    form = FormSchema(
        form_id="t",
        title={"en": "T"},
        sections=[src_section, FormSection(section_id="other", fields=[])],
    ).model_copy(update={"sections": [src_section, dst_section]})
    op = MoveField.model_validate({
        "op": "move_field",
        "from": {"section_uid": str(src_section.section_uid), "field_uid": str(moving_field.field_uid)},
        "to": {"section_uid": str(dst_section.section_uid)},
    })
    with pytest.raises(OperationError, match="duplicate field_uid"):
        _apply_move_field(form, op)
    # Rolled back — the field is still in its original location.
    assert form.sections[0].fields[0].field_id == "moving"


def test_remove_field_unknown_id(form):
    op = RemoveField(
        op="remove_field",
        section_uid=form.sections[0].section_uid,
        field_uid=uuid.uuid4(),
    )
    with pytest.raises(OperationError):
        _apply_remove_field(form, op)


def test_add_section_at_position(form):
    op = AddSection.model_validate({
        "op": "add_section",
        "section": {"section_id": "s0", "fields": []},
        "position": 0,
    })
    out = _apply_add_section(form, op)
    assert out.sections[0].section_id == "s0"
    assert out.sections[1].section_id == "s1"


def test_add_section_duplicate_rejected(form):
    op = AddSection.model_validate({
        "op": "add_section",
        "section": {"section_id": "s1", "fields": []},
    })
    with pytest.raises(OperationError):
        _apply_add_section(form, op)


def test_move_field_across_sections():
    form = FormSchema(
        form_id="t",
        title={"en": "T"},
        sections=[
            FormSection(
                section_id="s1",
                fields=[
                    FormField(field_id="x", field_type=FieldType.TEXT, label={"en": "X"}),
                ],
            ),
            FormSection(
                section_id="s2",
                fields=[],
            ),
        ],
    )
    op = MoveField.model_validate({
        "op": "move_field",
        "from": {
            "section_uid": str(form.sections[0].section_uid),
            "field_uid": str(form.sections[0].fields[0].field_uid),
        },
        "to": {"section_uid": str(form.sections[1].section_uid), "position": 0},
    })
    out = _apply_move_field(form, op)
    assert [f.field_id for f in out.sections[0].fields] == []
    assert [f.field_id for f in out.sections[1].fields] == ["x"]


def test_move_field_duplicate_destination_rolls_back():
    """Moving into a section that already has the same field_uid is
    rejected, and the source section is left untouched (rollback)."""
    shared_uid = uuid.uuid4()
    existing_field = FormField(
        field_uid=shared_uid, field_id="x", field_type=FieldType.TEXT, label="X (dst)"
    )
    form = FormSchema(
        form_id="t",
        title={"en": "T"},
        sections=[
            FormSection(
                section_id="s1",
                fields=[FormField(field_id="y", field_type=FieldType.TEXT, label="Y")],
            ),
            FormSection(section_id="s2", fields=[existing_field]),
        ],
    )
    # Directly mutating the field list (not FormSchema.model_validate)
    # bypasses the construction-time uniqueness validator — simulates a
    # pre-existing duplicate field_uid reaching the operations layer.
    form.sections[0].fields[0] = FormField(
        field_uid=shared_uid, field_id="y", field_type=FieldType.TEXT, label="Y"
    )
    op = MoveField.model_validate({
        "op": "move_field",
        "from": {
            "section_uid": str(form.sections[0].section_uid),
            "field_uid": str(form.sections[0].fields[0].field_uid),
        },
        "to": {"section_uid": str(form.sections[1].section_uid), "position": 0},
    })
    with pytest.raises(OperationError):
        _apply_move_field(form, op)
    # Rollback: source section still has its field.
    assert len(form.sections[0].fields) == 1


def test_update_field_merges(form):
    op = UpdateField.model_validate({
        "op": "update_field",
        "section_uid": str(form.sections[0].section_uid),
        "field_uid": str(form.sections[0].fields[0].field_uid),
        "patch": {"required": True, "label": {"es": "Nombre"}},
    })
    out = _apply_update_field(form, op)
    field = out.sections[0].fields[0]
    assert field.required is True
    # Label is RFC 7396 merged
    assert field.label["es"] == "Nombre"
    assert field.label["en"] == "N"  # original preserved


def test_update_field_renames_field_id(form):
    """field_id rename via patch succeeds (identity moved to field_uid)."""
    op = UpdateField.model_validate({
        "op": "update_field",
        "section_uid": str(form.sections[0].section_uid),
        "field_uid": str(form.sections[0].fields[0].field_uid),
        "patch": {"field_id": "renamed"},
    })
    out = _apply_update_field(form, op)
    assert out.sections[0].fields[0].field_id == "renamed"
    assert out.sections[0].fields[0].field_uid == form.sections[0].fields[0].field_uid


def test_update_field_rename_rejects_duplicate_field_id():
    """Renaming to a field_id already used elsewhere in the form is rejected."""
    f1 = FormField(field_id="a", field_type=FieldType.TEXT, label="A")
    f2 = FormField(field_id="b", field_type=FieldType.TEXT, label="B")
    form = FormSchema(
        form_id="t", title={"en": "T"},
        sections=[FormSection(section_id="s1", fields=[f1, f2])],
    )
    op = UpdateField.model_validate({
        "op": "update_field",
        "section_uid": str(form.sections[0].section_uid),
        "field_uid": str(f2.field_uid),
        "patch": {"field_id": "a"},
    })
    with pytest.raises(OperationError):
        _apply_update_field(form, op)


def test_update_field_rejects_field_uid_change(form):
    """A patch touching field_uid is explicitly rejected — the identity
    pin moved from field_id (pre-FEAT-393) to field_uid."""
    field_uid = form.sections[0].fields[0].field_uid
    op = UpdateField.model_validate({
        "op": "update_field",
        "section_uid": str(form.sections[0].section_uid),
        "field_uid": str(field_uid),
        "patch": {"field_uid": str(uuid.uuid4())},
    })
    with pytest.raises(OperationError):
        _apply_update_field(form, op)


def test_update_form_meta_merges(form):
    form.meta = {"a": 1, "b": {"c": 2}}
    op = UpdateFormMeta.model_validate({
        "op": "update_form_meta",
        "patch": {"b": {"d": 3}, "e": 4},
    })
    out = _apply_update_form_meta(form, op)
    assert out.meta == {"a": 1, "b": {"c": 2, "d": 3}, "e": 4}


def test_update_form_meta_null_removes_key(form):
    """RFC 7396: null deletes the key."""
    form.meta = {"a": 1, "b": 2}
    op = UpdateFormMeta.model_validate({
        "op": "update_form_meta",
        "patch": {"b": None},
    })
    out = _apply_update_form_meta(form, op)
    assert out.meta == {"a": 1}


def test_update_section_meta_merges(form):
    op = UpdateSectionMeta.model_validate({
        "op": "update_section_meta",
        "section_uid": str(form.sections[0].section_uid),
        "patch": {"x": 1},
    })
    out = _apply_update_section_meta(form, op)
    assert out.sections[0].meta == {"x": 1}


def test_duplicate_field(form):
    op = DuplicateField.model_validate({
        "op": "duplicate_field",
        "from": {
            "section_uid": str(form.sections[0].section_uid),
            "field_uid": str(form.sections[0].fields[0].field_uid),
        },
        "as_field_id": "name_copy",
    })
    out = _apply_duplicate_field(form, op)
    ids = [f.field_id for f in out.sections[0].fields]
    assert ids == ["name", "name_copy"]


def test_duplicate_field_mints_fresh_uid(form):
    src_uid = form.sections[0].fields[0].field_uid
    op = DuplicateField.model_validate({
        "op": "duplicate_field",
        "from": {
            "section_uid": str(form.sections[0].section_uid),
            "field_uid": str(src_uid),
        },
        "as_field_id": "name_copy",
    })
    out = _apply_duplicate_field(form, op)
    clone = out.sections[0].fields[1]
    assert clone.field_uid != src_uid


def test_duplicate_field_collision(form):
    op = DuplicateField.model_validate({
        "op": "duplicate_field",
        "from": {
            "section_uid": str(form.sections[0].section_uid),
            "field_uid": str(form.sections[0].fields[0].field_uid),
        },
        "as_field_id": "name",  # same id — collision
    })
    with pytest.raises(OperationError):
        _apply_duplicate_field(form, op)
