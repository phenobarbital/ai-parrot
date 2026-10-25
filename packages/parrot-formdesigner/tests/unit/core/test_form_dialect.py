"""FormSchema.dialect — FEAT-650 TASK-4191."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from parrot_formdesigner.api._utils import _deep_merge
from parrot_formdesigner.core import FormDialect
from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection
from parrot_formdesigner.core.types import FieldType


def _form(**kw: object) -> FormSchema:
    """Build a minimal valid form schema for dialect tests."""
    return FormSchema(
        form_id="f",
        title={"en": "F"},
        tenant="navigator",
        sections=[
            FormSection(
                section_id="s",
                fields=[FormField(field_id="a", field_type=FieldType.TEXT, label={"en": "A"})],
            )
        ],
        **kw,
    )


def test_default_is_json_schema() -> None:
    """The persisted dialect defaults to the legacy JSON Schema wire format."""
    assert _form().dialect is FormDialect.JSON_SCHEMA


def test_dump_emits_bare_string_and_roundtrips() -> None:
    """The A2UI string wire value round-trips through JSON serialization."""
    form = _form(dialect="a2ui")
    dumped = json.loads(form.model_dump_json())
    assert dumped["dialect"] == "a2ui"
    assert FormSchema.model_validate_json(form.model_dump_json()).dialect is FormDialect.A2UI


def test_legacy_dump_without_key_loads_as_default() -> None:
    """A persisted form without the new key remains a legacy JSON Schema form."""
    data = _form().model_dump(mode="json")
    data.pop("dialect")
    assert FormSchema.model_validate(data).dialect is FormDialect.JSON_SCHEMA


def test_patch_deep_merge_sets_dialect() -> None:
    """A JSON merge patch replaces the top-level persisted dialect field."""
    merged = _deep_merge(_form().model_dump(), {"dialect": "a2ui"})
    assert FormSchema.model_validate(merged).dialect is FormDialect.A2UI


def test_unknown_value_rejected() -> None:
    """Pydantic rejects unsupported wire dialect values without a custom validator."""
    with pytest.raises(ValidationError):
        _form(dialect="xml")
