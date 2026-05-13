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


# TASK-1148: FieldConstraints scale fields tests
from pydantic import ValidationError
from parrot_formdesigner.core.constraints import FieldConstraints


def test_field_constraints_scale_validator_rejects_inverted_range():
    """scale_max < scale_min raises ValidationError."""
    with pytest.raises(ValidationError, match="scale_max"):
        FieldConstraints(scale_min=5, scale_max=3)


def test_field_constraints_scale_equal_raises():
    """scale_max == scale_min raises ValidationError."""
    with pytest.raises(ValidationError):
        FieldConstraints(scale_min=5, scale_max=5)


def test_field_constraints_anchor_labels_in_bounds():
    """Anchor label keys outside [scale_min, scale_max] raise."""
    with pytest.raises(ValidationError, match="anchor_labels"):
        FieldConstraints(scale_min=0, scale_max=10, anchor_labels={11: "Extreme"})


def test_field_constraints_anchor_labels_valid():
    """Anchor labels within bounds are accepted."""
    fc = FieldConstraints(
        scale_min=0, scale_max=10,
        anchor_labels={0: "Not at all", 5: "Neutral", 10: "Extremely likely"}
    )
    assert len(fc.anchor_labels) == 3


def test_field_constraints_scale_none_is_ok():
    """scale_* fields default to None — existing usage unchanged."""
    fc = FieldConstraints()
    assert fc.scale_min is None
    assert fc.scale_max is None


# TASK-1147: New FieldType enum values tests
from parrot_formdesigner.core.types import FieldType


def test_field_type_enum_has_new_values():
    """All 10 new FieldType values are present with stable string aliases."""
    new_types = {
        FieldType.SIGNATURE: "signature",
        FieldType.DYNAMIC_SELECT: "dynamic_select",
        FieldType.TRANSFER_LIST: "transfer_list",
        FieldType.REMOTE_RESPONSE: "remote_response",
        FieldType.AVAILABILITY: "availability",
        FieldType.LOCATION: "location",
        FieldType.TAGS: "tags",
        FieldType.NPS: "nps",
        FieldType.LIKERT: "likert",
        FieldType.RANKING: "ranking",
    }
    for ft, expected_value in new_types.items():
        assert ft.value == expected_value, f"{ft} has wrong value"
        assert FieldType(expected_value) == ft, f"String alias broken for {expected_value}"


def test_field_type_enum_total_count():
    """FieldType now has exactly 30 values (20 existing + 10 new)."""
    assert len(FieldType) == 30


def test_field_type_existing_values_unchanged():
    """All original 20 FieldType values are unchanged."""
    assert FieldType.TEXT.value == "text"
    assert FieldType.ARRAY.value == "array"
    assert FieldType.GROUP.value == "group"


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

