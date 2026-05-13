"""Unit tests for parrot-formdesigner core models (TASK-548, TASK-1033)."""

from datetime import datetime, timezone

import pytest

from parrot_formdesigner.core import FormSchema, FormField, FieldType, FormSection
from parrot_formdesigner.core.style import FormStyle, StyleSchema
from parrot_formdesigner.core.constraints import FieldConstraints
from parrot_formdesigner.core.options import FieldOption


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

    def test_form_schema_created_at_optional(self) -> None:
        """FormSchema without created_at parses correctly with created_at=None."""
        f = FormSchema(form_id="x", title="t", sections=[])
        assert f.created_at is None

    def test_form_schema_created_at_serializes_iso(self) -> None:
        """FormSchema with a tz-aware datetime serializes created_at as ISO-8601."""
        ts = datetime(2026, 4, 12, 10, 31, tzinfo=timezone.utc)
        f = FormSchema(form_id="x", title="t", sections=[], created_at=ts)
        js = f.model_dump_json()
        # Pydantic v2 may emit "Z" or "+00:00" suffix — both are valid ISO-8601.
        assert '"created_at":"2026-04-12T10:31:00' in js
        assert "created_at" in js
        f2 = FormSchema.model_validate_json(js)
        assert f2.created_at == ts


# TASK-1146: RenderWarning and RenderedForm.warnings tests
from parrot_formdesigner.core.schema import RenderedForm, RenderWarning


def test_rendered_form_warnings_default_empty():
    """RenderedForm defaults warnings to empty list."""
    rf = RenderedForm(content="<form/>", content_type="text/html")
    assert rf.warnings == []


def test_render_warning_model():
    """RenderWarning has all required fields."""
    w = RenderWarning(
        field_id="sig1",
        field_type="signature",
        renderer="pdf",
        reason="unsupported in PDF — rendered as placeholder",
    )
    assert w.field_id == "sig1"
    assert w.renderer == "pdf"


def test_rendered_form_with_warnings():
    """RenderedForm accepts and stores warnings."""
    w = RenderWarning(field_id="f1", field_type="nps", renderer="xforms", reason="fallback")
    rf = RenderedForm(content={}, content_type="application/json", warnings=[w])
    assert len(rf.warnings) == 1
    assert rf.warnings[0].field_type == "nps"

