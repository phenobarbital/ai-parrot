"""Unit tests for parrot-formdesigner services."""
import pytest
from parrot.formdesigner.core.schema import FormSchema, FormSection, FormField
from parrot.formdesigner.core.types import FieldType
from parrot.formdesigner.services import FormValidator, FormRegistry, FormCache


@pytest.fixture
def sample_schema() -> FormSchema:
    return FormSchema(
        form_id="test-form",
        title="Test Form",
        sections=[
            FormSection(
                section_id="main",
                title="Main",
                fields=[
                    FormField(field_id="name", field_type=FieldType.TEXT, label="Name", required=True),
                    FormField(field_id="email", field_type=FieldType.EMAIL, label="Email"),
                ],
            )
        ],
    )


class TestFormRegistry:
    async def test_register_and_retrieve(self, sample_schema):
        registry = FormRegistry()
        await registry.register(sample_schema)
        retrieved = await registry.get("test-form")
        assert retrieved is not None
        assert retrieved.form_id == "test-form"

    async def test_list_forms(self, sample_schema):
        registry = FormRegistry()
        await registry.register(sample_schema)
        forms = await registry.list_forms()
        assert len(forms) >= 1

    async def test_get_nonexistent_form(self):
        registry = FormRegistry()
        result = await registry.get("nonexistent")
        assert result is None


class TestFormValidator:
    async def test_valid_submission(self, sample_schema):
        validator = FormValidator()
        result = await validator.validate(sample_schema, {"name": "John", "email": "john@example.com"})
        assert result.is_valid is True

    async def test_missing_required_field(self, sample_schema):
        validator = FormValidator()
        result = await validator.validate(sample_schema, {"email": "john@example.com"})
        assert result.is_valid is False


class TestFormCache:
    async def test_set_and_get(self, sample_schema):
        cache = FormCache()
        await cache.set(sample_schema)
        result = await cache.get("test-form")
        assert result is not None
        assert result.form_id == "test-form"

    async def test_get_missing_key(self):
        cache = FormCache()
        result = await cache.get("does-not-exist")
        assert result is None
