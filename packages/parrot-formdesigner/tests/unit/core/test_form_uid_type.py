"""Unit tests for the FormSchema.form_uid str -> uuid.UUID retrofit.

FEAT-393 (TASK-1995), Module 1: FEAT-389 shipped ``form_uid`` as a plain
``str``; this feature standardizes all identity fields (``form_uid``,
``field_uid``, ``section_uid``, ``subsection_uid``) on ``uuid.UUID``. These
tests cover the ``form_uid`` half of that retrofit — the type itself,
client-supplied values, and JSON wire-shape stability.
"""
import uuid

import pytest
from pydantic import ValidationError

from parrot_formdesigner.core.schema import FormSchema


@pytest.fixture
def minimal_form_kwargs():
    """Minimal kwargs to construct a valid FormSchema."""
    return {"form_id": "test-form", "title": "Test Form", "sections": []}


def test_form_uid_is_uuid_type(minimal_form_kwargs):
    form = FormSchema(**minimal_form_kwargs)
    assert isinstance(form.form_uid, uuid.UUID)


def test_form_uid_auto_generated_and_unique(minimal_form_kwargs):
    form_a = FormSchema(**minimal_form_kwargs)
    form_b = FormSchema(**minimal_form_kwargs)
    assert form_a.form_uid != form_b.form_uid


def test_form_uid_json_roundtrip(minimal_form_kwargs):
    form = FormSchema(**minimal_form_kwargs)
    dumped = form.model_dump_json()
    restored = FormSchema.model_validate_json(dumped)
    assert restored.form_uid == form.form_uid


def test_form_uid_wire_shape_is_canonical_string(minimal_form_kwargs):
    """JSON wire shape must be unchanged: UUID serializes to a canonical
    string, not an object or list."""
    form = FormSchema(**minimal_form_kwargs)
    data = form.model_dump(mode="json")
    assert data["form_uid"] == str(form.form_uid)


def test_client_supplied_form_uid_accepted(minimal_form_kwargs):
    uid = uuid.uuid4()
    form = FormSchema(form_uid=str(uid), **minimal_form_kwargs)
    assert form.form_uid == uid


def test_client_supplied_form_uid_as_uuid_object(minimal_form_kwargs):
    uid = uuid.uuid4()
    form = FormSchema(form_uid=uid, **minimal_form_kwargs)
    assert form.form_uid == uid


def test_invalid_form_uid_rejected(minimal_form_kwargs):
    with pytest.raises(ValidationError):
        FormSchema(form_uid="not-a-uuid", **minimal_form_kwargs)
