"""Unit tests for FormValidator."""

import pytest
from parrot.forms import (
    ConditionOperator,
    DependencyRule,
    FieldCondition,
    FieldConstraints,
    FieldOption,
    FieldType,
    FormField,
    FormSchema,
    FormSection,
)
from parrot.forms.validators import FormValidator, ValidationResult


@pytest.fixture
def validator():
    """FormValidator instance."""
    return FormValidator()


@pytest.fixture
def simple_form():
    """Simple form with a single required TEXT field."""
    return FormSchema(
        form_id="test",
        title="Test Form",
        sections=[
            FormSection(
                section_id="s1",
                fields=[
                    FormField(
                        field_id="name",
                        field_type=FieldType.TEXT,
                        label="Name",
                        required=True,
                    )
                ],
            )
        ],
    )


class TestFormValidatorRequired:
    """Tests for required field validation."""

    async def test_required_field_missing(self, validator, simple_form):
        """Required field not in data triggers error."""
        result = await validator.validate(simple_form, {})
        assert not result.is_valid
        assert "name" in result.errors

    async def test_required_field_empty_string(self, validator, simple_form):
        """Required field with empty string triggers error."""
        result = await validator.validate(simple_form, {"name": ""})
        assert not result.is_valid
        assert "name" in result.errors

    async def test_required_field_whitespace(self, validator, simple_form):
        """Required field with whitespace-only string triggers error."""
        result = await validator.validate(simple_form, {"name": "   "})
        assert not result.is_valid
        assert "name" in result.errors

    async def test_required_field_provided(self, validator, simple_form):
        """Required field with valid value passes."""
        result = await validator.validate(simple_form, {"name": "Alice"})
        assert result.is_valid
        assert result.sanitized_data["name"] == "Alice"

    async def test_optional_field_missing(self, validator):
        """Optional field can be absent."""
        form = FormSchema(
            form_id="t",
            title="T",
            sections=[
                FormSection(
                    section_id="s",
                    fields=[
                        FormField(
                            field_id="phone",
                            field_type=FieldType.TEXT,
                            label="Phone",
                            required=False,
                        )
                    ],
                )
            ],
        )
        result = await validator.validate(form, {})
        assert result.is_valid


class TestFormValidatorConstraints:
    """Tests for FieldConstraints validation."""

    async def test_min_length(self, validator):
        """Value shorter than min_length fails."""
        form = FormSchema(
            form_id="t",
            title="T",
            sections=[
                FormSection(
                    section_id="s",
                    fields=[
                        FormField(
                            field_id="code",
                            field_type=FieldType.TEXT,
                            label="Code",
                            constraints=FieldConstraints(min_length=3, max_length=10),
                        )
                    ],
                )
            ],
        )
        result = await validator.validate(form, {"code": "ab"})
        assert not result.is_valid
        assert "code" in result.errors

    async def test_max_length(self, validator):
        """Value longer than max_length fails."""
        form = FormSchema(
            form_id="t",
            title="T",
            sections=[
                FormSection(
                    section_id="s",
                    fields=[
                        FormField(
                            field_id="code",
                            field_type=FieldType.TEXT,
                            label="Code",
                            constraints=FieldConstraints(max_length=5),
                        )
                    ],
                )
            ],
        )
        result = await validator.validate(form, {"code": "toolongvalue"})
        assert not result.is_valid

    async def test_pattern_validation(self, validator):
        """Value not matching pattern fails."""
        form = FormSchema(
            form_id="t",
            title="T",
            sections=[
                FormSection(
                    section_id="s",
                    fields=[
                        FormField(
                            field_id="zip",
                            field_type=FieldType.TEXT,
                            label="ZIP",
                            constraints=FieldConstraints(pattern=r"^\d{5}$"),
                        )
                    ],
                )
            ],
        )
        result = await validator.validate(form, {"zip": "abc"})
        assert not result.is_valid
        assert "zip" in result.errors

    async def test_pattern_valid(self, validator):
        """Value matching pattern passes."""
        form = FormSchema(
            form_id="t",
            title="T",
            sections=[
                FormSection(
                    section_id="s",
                    fields=[
                        FormField(
                            field_id="zip",
                            field_type=FieldType.TEXT,
                            label="ZIP",
                            constraints=FieldConstraints(pattern=r"^\d{5}$"),
                        )
                    ],
                )
            ],
        )
        result = await validator.validate(form, {"zip": "12345"})
        assert result.is_valid

    async def test_min_value(self, validator):
        """Value below min_value fails."""
        form = FormSchema(
            form_id="t",
            title="T",
            sections=[
                FormSection(
                    section_id="s",
                    fields=[
                        FormField(
                            field_id="age",
                            field_type=FieldType.NUMBER,
                            label="Age",
                            constraints=FieldConstraints(min_value=0, max_value=150),
                        )
                    ],
                )
            ],
        )
        result = await validator.validate(form, {"age": -5})
        assert not result.is_valid

    async def test_max_value(self, validator):
        """Value above max_value fails."""
        form = FormSchema(
            form_id="t",
            title="T",
            sections=[
                FormSection(
                    section_id="s",
                    fields=[
                        FormField(
                            field_id="age",
                            field_type=FieldType.NUMBER,
                            label="Age",
                            constraints=FieldConstraints(max_value=100),
                        )
                    ],
                )
            ],
        )
        result = await validator.validate(form, {"age": 200})
        assert not result.is_valid


class TestFormValidatorTypeValidation:
    """Tests for built-in type-based validation."""

    async def test_email_validation_valid(self, validator):
        """Valid email passes."""
        form = FormSchema(
            form_id="t",
            title="T",
            sections=[
                FormSection(
                    section_id="s",
                    fields=[
                        FormField(
                            field_id="email",
                            field_type=FieldType.EMAIL,
                            label="Email",
                        )
                    ],
                )
            ],
        )
        result = await validator.validate(form, {"email": "user@example.com"})
        assert result.is_valid

    async def test_email_validation_invalid(self, validator):
        """Invalid email fails."""
        form = FormSchema(
            form_id="t",
            title="T",
            sections=[
                FormSection(
                    section_id="s",
                    fields=[
                        FormField(
                            field_id="email",
                            field_type=FieldType.EMAIL,
                            label="Email",
                        )
                    ],
                )
            ],
        )
        result = await validator.validate(form, {"email": "not-an-email"})
        assert not result.is_valid

    async def test_url_validation_valid(self, validator):
        """Valid URL passes."""
        form = FormSchema(
            form_id="t",
            title="T",
            sections=[
                FormSection(
                    section_id="s",
                    fields=[
                        FormField(
                            field_id="site",
                            field_type=FieldType.URL,
                            label="Site",
                        )
                    ],
                )
            ],
        )
        result = await validator.validate(form, {"site": "https://example.com"})
        assert result.is_valid

    async def test_boolean_coercion(self, validator):
        """Boolean strings are coerced correctly."""
        form = FormSchema(
            form_id="t",
            title="T",
            sections=[
                FormSection(
                    section_id="s",
                    fields=[
                        FormField(
                            field_id="active",
                            field_type=FieldType.BOOLEAN,
                            label="Active",
                        )
                    ],
                )
            ],
        )
        result = await validator.validate(form, {"active": "true"})
        assert result.is_valid
        assert result.sanitized_data["active"] is True


class TestFormValidatorCircularDependency:
    """Tests for circular dependency detection."""

    async def test_circular_dependency_detected(self, validator):
        """Fields A depends on B and B depends on A triggers cycle detection."""
        form = FormSchema(
            form_id="t",
            title="T",
            sections=[
                FormSection(
                    section_id="s",
                    fields=[
                        FormField(
                            field_id="a",
                            field_type=FieldType.TEXT,
                            label="A",
                            depends_on=DependencyRule(
                                conditions=[
                                    FieldCondition(
                                        field_id="b",
                                        operator=ConditionOperator.EQ,
                                        value="x",
                                    )
                                ]
                            ),
                        ),
                        FormField(
                            field_id="b",
                            field_type=FieldType.TEXT,
                            label="B",
                            depends_on=DependencyRule(
                                conditions=[
                                    FieldCondition(
                                        field_id="a",
                                        operator=ConditionOperator.EQ,
                                        value="y",
                                    )
                                ]
                            ),
                        ),
                    ],
                )
            ],
        )
        result = await validator.validate(form, {"a": "x", "b": "y"})
        assert not result.is_valid
        error_text = str(result.errors).lower()
        assert "circular" in error_text

    async def test_no_circular_dependency(self, validator):
        """Linear dependency (A depends on B, no cycle) does not trigger error."""
        form = FormSchema(
            form_id="t",
            title="T",
            sections=[
                FormSection(
                    section_id="s",
                    fields=[
                        FormField(field_id="b", field_type=FieldType.TEXT, label="B"),
                        FormField(
                            field_id="a",
                            field_type=FieldType.TEXT,
                            label="A",
                            depends_on=DependencyRule(
                                conditions=[
                                    FieldCondition(
                                        field_id="b",
                                        operator=ConditionOperator.EQ,
                                        value="yes",
                                    )
                                ]
                            ),
                        ),
                    ],
                )
            ],
        )
        # Detect cycles only — B has a valid value, no cycle present
        result = await validator.validate(form, {"b": "yes", "a": "hello"})
        assert result.is_valid


class TestFormValidatorValid:
    """Tests for successful validation scenarios."""

    async def test_valid_submission(self, validator, simple_form):
        """Valid submission returns is_valid=True."""
        result = await validator.validate(simple_form, {"name": "Alice"})
        assert result.is_valid

    async def test_sanitized_data_populated(self, validator, simple_form):
        """Sanitized data contains coerced values on success."""
        result = await validator.validate(simple_form, {"name": "  Bob  "})
        assert result.is_valid
        assert result.sanitized_data["name"] == "Bob"

    async def test_select_valid_option(self, validator):
        """SELECT field with valid option passes."""
        form = FormSchema(
            form_id="t",
            title="T",
            sections=[
                FormSection(
                    section_id="s",
                    fields=[
                        FormField(
                            field_id="color",
                            field_type=FieldType.SELECT,
                            label="Color",
                            options=[
                                FieldOption(value="red", label="Red"),
                                FieldOption(value="blue", label="Blue"),
                            ],
                        )
                    ],
                )
            ],
        )
        result = await validator.validate(form, {"color": "red"})
        assert result.is_valid

    async def test_select_invalid_option(self, validator):
        """SELECT field with invalid option fails."""
        form = FormSchema(
            form_id="t",
            title="T",
            sections=[
                FormSection(
                    section_id="s",
                    fields=[
                        FormField(
                            field_id="color",
                            field_type=FieldType.SELECT,
                            label="Color",
                            options=[
                                FieldOption(value="red", label="Red"),
                            ],
                        )
                    ],
                )
            ],
        )
        result = await validator.validate(form, {"color": "green"})
        assert not result.is_valid

    async def test_cross_field_validator(self, validator):
        """Cross-field validator in meta runs correctly."""
        def end_after_start(value, all_data):
            start = all_data.get("start_date", "")
            if value and start and value < start:
                return "End date must be after start date"
            return None

        form = FormSchema(
            form_id="t",
            title="T",
            sections=[
                FormSection(
                    section_id="s",
                    fields=[
                        FormField(
                            field_id="start_date",
                            field_type=FieldType.DATE,
                            label="Start",
                        ),
                        FormField(
                            field_id="end_date",
                            field_type=FieldType.DATE,
                            label="End",
                            meta={"cross_field_validators": [end_after_start]},
                        ),
                    ],
                )
            ],
        )
        # end_date before start_date
        result = await validator.validate(
            form, {"start_date": "2024-06-01", "end_date": "2024-01-01"}
        )
        assert not result.is_valid
        assert "end_date" in result.errors
