"""Unit tests for FormSchema.is_public field (FEAT-241 M4).

Tests cover:
- Default value is False
- Can be set to True
- Round-trips through model_dump / model_validate
- JSON round-trip
- Backward compatibility when field is absent in serialized data
"""
import pytest
from parrot_formdesigner.core.schema import FormSchema


@pytest.fixture
def minimal_schema_kwargs():
    """Minimal kwargs to construct a valid FormSchema."""
    return {"form_id": "test-form", "title": "Test Form", "sections": []}


class TestFormSchemaIsPublicField:
    def test_default_is_false(self, minimal_schema_kwargs):
        schema = FormSchema(**minimal_schema_kwargs)
        assert schema.is_public is False

    def test_can_set_true(self, minimal_schema_kwargs):
        schema = FormSchema(**minimal_schema_kwargs, is_public=True)
        assert schema.is_public is True

    def test_round_trips_model_dump(self, minimal_schema_kwargs):
        schema = FormSchema(**minimal_schema_kwargs, is_public=True)
        data = schema.model_dump()
        assert "is_public" in data
        assert data["is_public"] is True

    def test_round_trips_model_dump_false(self, minimal_schema_kwargs):
        schema = FormSchema(**minimal_schema_kwargs, is_public=False)
        data = schema.model_dump()
        assert "is_public" in data
        assert data["is_public"] is False

    def test_round_trips_model_validate(self, minimal_schema_kwargs):
        data = {**minimal_schema_kwargs, "is_public": True}
        schema = FormSchema.model_validate(data)
        assert schema.is_public is True

    def test_backward_compat_missing_is_public(self, minimal_schema_kwargs):
        """Old serialized forms without is_public must default to False."""
        schema = FormSchema.model_validate(minimal_schema_kwargs)
        assert schema.is_public is False

    def test_json_round_trip(self, minimal_schema_kwargs):
        schema = FormSchema(**minimal_schema_kwargs, is_public=True)
        json_str = schema.model_dump_json()
        restored = FormSchema.model_validate_json(json_str)
        assert restored.is_public is True

    def test_is_public_in_model_fields(self):
        """is_public must appear in FormSchema.model_fields."""
        assert "is_public" in FormSchema.model_fields

    def test_is_public_type_is_bool(self, minimal_schema_kwargs):
        """is_public must always be a bool (not None, not str)."""
        schema = FormSchema(**minimal_schema_kwargs)
        assert isinstance(schema.is_public, bool)

    def test_full_schema_with_is_public_true(self):
        """Construct a more complete FormSchema with is_public=True."""
        schema = FormSchema(
            form_id="contact",
            title="Contact Form",
            sections=[],
            is_public=True,
        )
        assert schema.is_public is True
        assert schema.form_id == "contact"
