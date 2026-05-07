"""Unit tests for ``parrot_formdesigner.api.operations``."""

from __future__ import annotations

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
from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection
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
    env = OperationsEnvelope.model_validate({
        "operations": [
            {
                "op": "move_field",
                "from": {"section_id": "s1", "field_id": "x"},
                "to": {"section_id": "s2", "position": 0},
            },
        ],
    })
    assert isinstance(env.operations[0], MoveField)
    assert env.operations[0].from_["section_id"] == "s1"


def test_envelope_discriminates_all_ops():
    payload = {
        "operations": [
            {
                "op": "add_section",
                "section": {"section_id": "s2", "fields": []},
            },
            {
                "op": "add_field",
                "section_id": "s1",
                "field": {
                    "field_id": "x",
                    "field_type": "text",
                    "label": {"en": "X"},
                },
            },
            {
                "op": "remove_field",
                "section_id": "s1",
                "field_id": "x",
            },
            {
                "op": "update_field",
                "section_id": "s1",
                "field_id": "name",
                "patch": {"required": True},
            },
            {
                "op": "update_section_meta",
                "section_id": "s1",
                "patch": {"x": 1},
            },
            {
                "op": "update_form_meta",
                "patch": {"x": 1},
            },
            {
                "op": "duplicate_field",
                "from": {"section_id": "s1", "field_id": "name"},
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


# ---------------------------------------------------------------------------
# Per-op apply
# ---------------------------------------------------------------------------


def test_add_field_succeeds(form):
    op = AddField.model_validate({
        "op": "add_field",
        "section_id": "s1",
        "field": {
            "field_id": "email",
            "field_type": "email",
            "label": {"en": "E"},
        },
    })
    out = _apply_add_field(form, op)
    assert {f.field_id for f in out.sections[0].fields} == {"name", "email"}


def test_add_field_duplicate_rejected(form):
    op = AddField.model_validate({
        "op": "add_field",
        "section_id": "s1",
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
        "section_id": "missing",
        "field": {
            "field_id": "x",
            "field_type": "text",
            "label": {"en": "X"},
        },
    })
    with pytest.raises(OperationError):
        _apply_add_field(form, op)


def test_remove_field(form):
    op = RemoveField(op="remove_field", section_id="s1", field_id="name")
    out = _apply_remove_field(form, op)
    assert out.sections[0].fields == []


def test_remove_field_unknown_id(form):
    op = RemoveField(op="remove_field", section_id="s1", field_id="missing")
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
        "from": {"section_id": "s1", "field_id": "x"},
        "to": {"section_id": "s2", "position": 0},
    })
    out = _apply_move_field(form, op)
    assert [f.field_id for f in out.sections[0].fields] == []
    assert [f.field_id for f in out.sections[1].fields] == ["x"]


def test_update_field_merges(form):
    op = UpdateField.model_validate({
        "op": "update_field",
        "section_id": "s1",
        "field_id": "name",
        "patch": {"required": True, "label": {"es": "Nombre"}},
    })
    out = _apply_update_field(form, op)
    field = out.sections[0].fields[0]
    assert field.required is True
    # Label is RFC 7396 merged
    assert field.label["es"] == "Nombre"
    assert field.label["en"] == "N"  # original preserved


def test_update_field_field_id_immutable(form):
    """Patching `field_id` is silently overridden — identity preserved."""
    op = UpdateField.model_validate({
        "op": "update_field",
        "section_id": "s1",
        "field_id": "name",
        "patch": {"field_id": "renamed"},
    })
    out = _apply_update_field(form, op)
    assert out.sections[0].fields[0].field_id == "name"


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
        "section_id": "s1",
        "patch": {"x": 1},
    })
    out = _apply_update_section_meta(form, op)
    assert out.sections[0].meta == {"x": 1}


def test_duplicate_field(form):
    op = DuplicateField.model_validate({
        "op": "duplicate_field",
        "from": {"section_id": "s1", "field_id": "name"},
        "as_field_id": "name_copy",
    })
    out = _apply_duplicate_field(form, op)
    ids = [f.field_id for f in out.sections[0].fields]
    assert ids == ["name", "name_copy"]


def test_duplicate_field_collision(form):
    op = DuplicateField.model_validate({
        "op": "duplicate_field",
        "from": {"section_id": "s1", "field_id": "name"},
        "as_field_id": "name",  # same id — collision
    })
    with pytest.raises(OperationError):
        _apply_duplicate_field(form, op)
