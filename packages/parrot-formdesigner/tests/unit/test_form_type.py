"""Unit tests for FormType enum and FormSchema extensions (FEAT-300 TASK-001)."""

import pytest
from parrot_formdesigner.core.schema import FormSchema, FormSection, FormField, FormType
from parrot_formdesigner.core.types import FieldType


def _minimal_form(**kw):
    """Build a minimal valid FormSchema with one section and one field."""
    return FormSchema(
        form_id="t1",
        title="T",
        sections=[
            FormSection(
                section_id="s1",
                fields=[
                    FormField(field_id="q1", field_type=FieldType.TEXT, label="Q1")
                ],
            )
        ],
        **kw,
    )


def test_form_schema_form_type_default():
    """form_type defaults to FormType.SIMPLE."""
    assert _minimal_form().form_type == FormType.SIMPLE


def test_form_schema_form_type_survey():
    """form_type can be set to SURVEY."""
    f = _minimal_form(form_type=FormType.SURVEY)
    assert f.form_type == FormType.SURVEY


def test_form_schema_product_bindings():
    """product_bindings is stored and returned correctly."""
    f = _minimal_form(form_type=FormType.PRODUCT, product_bindings=["p1", "p2"])
    assert f.product_bindings == ["p1", "p2"]


def test_form_schema_product_bindings_default():
    """product_bindings defaults to None."""
    assert _minimal_form().product_bindings is None


def test_form_schema_published_version():
    """published_version defaults to None."""
    assert _minimal_form().published_version is None


def test_form_schema_published_version_set():
    """published_version can be set to a semver string."""
    f = _minimal_form(published_version="2.1")
    assert f.published_version == "2.1"


def test_form_type_values():
    """FormType enum values match expected strings."""
    assert FormType.SIMPLE.value == "simple"
    assert FormType.PRODUCT.value == "product"
    assert FormType.SURVEY.value == "survey"


def test_form_type_importable_from_core():
    """FormType is importable from the core package."""
    from parrot_formdesigner.core import FormType as FT  # noqa: PLC0415

    assert FT is FormType


def test_backward_compat_existing_fields():
    """Existing FormSchema construction (without new fields) still validates."""
    f = _minimal_form()
    # Core existing fields unchanged
    assert f.form_id == "t1"
    assert f.version == "1.0"
    assert f.title == "T"


def test_form_type_str_enum():
    """FormType is a str enum so values compare equal to plain strings."""
    assert FormType.SIMPLE == "simple"
    assert FormType.SURVEY == "survey"
    assert FormType.PRODUCT == "product"
