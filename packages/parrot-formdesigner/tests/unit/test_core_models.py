"""Unit tests for parrot-formdesigner core models (TASK-548)."""

import pytest
from parrot.formdesigner.core import FormSchema, FormField, FieldType, FormSection
from parrot.formdesigner.core.style import FormStyle, StyleSchema
from parrot.formdesigner.core.constraints import FieldConstraints
from parrot.formdesigner.core.options import FieldOption


@pytest.fixture
def sample_form_schema() -> FormSchema:
    """Create a sample FormSchema for testing."""
    return FormSchema(
        form_id="test-form",
        title="Test Form",
        sections=[
            FormSection(
                section_id="main",
                fields=[
                    FormField(field_id="name", field_type=FieldType.TEXT, label="Name"),
                    FormField(field_id="email", field_type=FieldType.EMAIL, label="Email"),
                ],
            )
        ],
    )


class TestFormSchema:
    """Tests for the FormSchema model."""

    def test_initialization(self, sample_form_schema: FormSchema) -> None:
        """FormSchema should initialize with correct form_id and sections."""
        assert sample_form_schema.form_id == "test-form"
        assert len(sample_form_schema.sections) == 1

    def test_field_access(self, sample_form_schema: FormSchema) -> None:
        """Fields should be accessible through sections."""
        fields = sample_form_schema.sections[0].fields
        assert len(fields) == 2

    def test_field_types(self, sample_form_schema: FormSchema) -> None:
        """Field types should be correctly assigned."""
        fields = sample_form_schema.sections[0].fields
        assert fields[0].field_type == FieldType.TEXT
        assert fields[1].field_type == FieldType.EMAIL

    def test_style_default(self) -> None:
        """FormStyle should have defaults and be instantiable without arguments."""
        style = FormStyle()
        assert style is not None

    def test_style_schema_default(self) -> None:
        """StyleSchema should have defaults and be instantiable without arguments."""
        style = StyleSchema()
        assert style is not None

    def test_field_constraints(self) -> None:
        """FieldConstraints should be instantiable with defaults."""
        constraints = FieldConstraints()
        assert constraints is not None
        assert constraints.min_length is None
        assert constraints.max_length is None

    def test_field_option(self) -> None:
        """FieldOption should store value and label."""
        option = FieldOption(value="opt1", label="Option 1")
        assert option.value == "opt1"
        assert option.label == "Option 1"
        assert option.disabled is False

    def test_field_type_enum_values(self) -> None:
        """FieldType enum should contain expected values."""
        assert FieldType.TEXT == "text"
        assert FieldType.EMAIL == "email"
        assert FieldType.SELECT == "select"
        assert FieldType.BOOLEAN == "boolean"

