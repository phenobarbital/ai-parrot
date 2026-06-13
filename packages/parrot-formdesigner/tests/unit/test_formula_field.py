"""Unit tests for FieldType.FORMULA and renderer fallbacks (FEAT-300 TASK-002)."""

from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection, RenderWarning
from parrot_formdesigner.core.types import FieldType


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _formula_form(**field_kw):
    """Build a minimal FormSchema containing one FORMULA field."""
    return FormSchema(
        form_id="f1",
        title="F",
        sections=[
            FormSection(
                section_id="s1",
                fields=[
                    FormField(
                        field_id="total",
                        field_type=FieldType.FORMULA,
                        label="Total",
                        **field_kw,
                    )
                ],
            )
        ],
    )


# ---------------------------------------------------------------------------
# Enum
# ---------------------------------------------------------------------------


def test_fieldtype_formula_exists():
    """FieldType.FORMULA resolves to the canonical string 'formula'."""
    assert FieldType.FORMULA.value == "formula"


def test_fieldtype_formula_is_string_enum():
    """FieldType inherits from str so FieldType.FORMULA == 'formula'."""
    assert FieldType.FORMULA == "formula"


def test_fieldtype_formula_round_trips():
    """FieldType('formula') round-trips correctly."""
    assert FieldType("formula") is FieldType.FORMULA


# ---------------------------------------------------------------------------
# HTML5 renderer
# ---------------------------------------------------------------------------


async def test_formula_field_fallback_html5_emits_warning():
    """Rendering a FORMULA field via HTML5Renderer emits a RenderWarning."""
    from parrot_formdesigner.renderers.html5 import HTML5Renderer

    form = _formula_form(meta={"expression": None})
    rendered = await HTML5Renderer().render(form)
    assert rendered.warnings, "Expected at least one RenderWarning"
    warning = rendered.warnings[0]
    assert isinstance(warning, RenderWarning)
    assert warning.field_id == "total"
    assert warning.field_type == "formula"
    assert warning.renderer == "html5"


async def test_formula_field_html5_no_exception():
    """Rendering a FORMULA field via HTML5Renderer must not raise."""
    from parrot_formdesigner.renderers.html5 import HTML5Renderer

    form = _formula_form()
    rendered = await HTML5Renderer().render(form)
    assert rendered.content  # non-empty HTML


async def test_formula_field_html5_placeholder_in_output():
    """HTML5 output for FORMULA contains a disabled input placeholder."""
    from parrot_formdesigner.renderers.html5 import HTML5Renderer

    form = _formula_form()
    rendered = await HTML5Renderer().render(form)
    assert "data-formula" in rendered.content


async def test_formula_field_html5_meta_none():
    """FORMULA field with meta=None must not crash HTML5Renderer."""
    from parrot_formdesigner.renderers.html5 import HTML5Renderer

    form = _formula_form(meta=None)
    rendered = await HTML5Renderer().render(form)
    assert rendered.warnings


# ---------------------------------------------------------------------------
# PDF renderer
# ---------------------------------------------------------------------------


async def test_formula_field_pdf_no_exception():
    """Rendering a FORMULA field via PdfRenderer must not raise."""
    from parrot_formdesigner.renderers.pdf import PdfRenderer

    form = _formula_form(meta={"expression": None})
    rendered = await PdfRenderer().render(form)
    assert rendered.warnings, "Expected at least one RenderWarning from PDF"
    warning = rendered.warnings[0]
    assert warning.field_type == "formula"
    assert warning.renderer == "pdf"


async def test_formula_field_pdf_emits_warning():
    """PDF rendering of a FORMULA field emits a RenderWarning (not an error)."""
    from parrot_formdesigner.renderers.pdf import PdfRenderer

    form = _formula_form()
    rendered = await PdfRenderer().render(form)
    field_types = [w.field_type for w in rendered.warnings]
    assert "formula" in field_types


# ---------------------------------------------------------------------------
# AdaptiveCard renderer
# ---------------------------------------------------------------------------


async def test_formula_field_adaptive_card_no_exception():
    """Rendering a FORMULA field via AdaptiveCardRenderer must not raise."""
    from parrot_formdesigner.renderers.adaptive_card import AdaptiveCardRenderer

    form = _formula_form()
    rendered = await AdaptiveCardRenderer().render(form)
    assert rendered.warnings
    assert any(w.field_type == "formula" for w in rendered.warnings)


# ---------------------------------------------------------------------------
# JSONSchema renderer
# ---------------------------------------------------------------------------


async def test_formula_field_jsonschema_no_exception():
    """Rendering a FORMULA field via JsonSchemaRenderer must not raise."""
    from parrot_formdesigner.renderers.jsonschema import JsonSchemaRenderer

    form = _formula_form()
    rendered = await JsonSchemaRenderer().render(form)
    # JSONSchema renderer maps FORMULA to "number" type — no exception expected
    assert rendered.content


async def test_formula_field_jsonschema_has_formula_format():
    """JSONSchema output for a FORMULA field includes x-parrot-type or format."""
    from parrot_formdesigner.renderers.jsonschema import JsonSchemaRenderer

    form = _formula_form()
    rendered = await JsonSchemaRenderer().render(form)
    schema_str = str(rendered.content)
    # The format entry for FORMULA should appear somewhere in the schema output
    assert "formula" in schema_str.lower()
