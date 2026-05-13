"""Unit tests for parrot-formdesigner renderers."""
import pytest
from parrot_formdesigner.core import FormSchema, FormSection
from parrot_formdesigner.core.schema import FormField
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.renderers import HTML5Renderer, JsonSchemaRenderer, AdaptiveCardRenderer
from parrot_formdesigner.renderers.base import FieldRenderer, FallbackRenderer
from parrot_formdesigner.core.style import StyleSchema


# TASK-1150: Validator branches for new field types
@pytest.mark.asyncio
async def test_validator_signature_accepts_dict():
    """SIGNATURE accepts dict with svg+png keys, rejects bare strings."""
    from parrot_formdesigner.services.validators import FormValidator
    from parrot_formdesigner.core.constraints import FieldConstraints

    validator = FormValidator()
    field = FormField(
        field_id="sig", field_type=FieldType.SIGNATURE, label="Sig",
        constraints=FieldConstraints(allowed_mime_types=["image/svg+xml", "image/png"])
    )
    errors = await validator.validate_field(field, {"svg": "<svg/>", "png": "data:image/png;base64,abc"})
    assert errors == [], f"Expected no errors, got: {errors}"

    errors_str = await validator.validate_field(field, "<svg/>")
    assert len(errors_str) > 0


@pytest.mark.asyncio
async def test_validator_nps_clamps_to_0_10():
    """NPS coerces string '5' → 5, rejects 11 and -1."""
    from parrot_formdesigner.services.validators import FormValidator
    from parrot_formdesigner.core.constraints import FieldConstraints

    validator = FormValidator()
    field = FormField(
        field_id="nps", field_type=FieldType.NPS, label="NPS",
        constraints=FieldConstraints(scale_min=0, scale_max=10)
    )
    errors = await validator.validate_field(field, "5")
    assert errors == [], f"NPS 5 should be valid, got: {errors}"

    errors_high = await validator.validate_field(field, 11)
    assert len(errors_high) > 0

    errors_low = await validator.validate_field(field, -1)
    assert len(errors_low) > 0


@pytest.mark.asyncio
async def test_validator_tags_returns_list_of_strings():
    """TAGS accepts 'a,b,c' and ['a','b','c'], both yield valid."""
    from parrot_formdesigner.services.validators import FormValidator

    validator = FormValidator()
    field = FormField(field_id="tags", field_type=FieldType.TAGS, label="Tags")
    errors_str = await validator.validate_field(field, "a,b,c")
    assert errors_str == []

    errors_list = await validator.validate_field(field, ["a", "b", "c"])
    assert errors_list == []


@pytest.mark.asyncio
async def test_validator_location_rejects_unknown_iso_code():
    """LOCATION with 'XX' raises; 'ES', 'VE', 'US' pass (when pycountry installed)."""
    import importlib.util
    from parrot_formdesigner.services.validators import FormValidator, _HAS_PYCOUNTRY

    validator = FormValidator()
    field = FormField(field_id="loc", field_type=FieldType.LOCATION, label="Country")
    if _HAS_PYCOUNTRY:
        errors_valid = await validator.validate_field(field, "US")
        assert errors_valid == []
        errors_invalid = await validator.validate_field(field, "XX")
        assert len(errors_invalid) > 0
    else:
        errors = await validator.validate_field(field, "US")
        assert errors == []  # skips when pycountry not available


@pytest.mark.asyncio
async def test_xforms_registry_dispatch_existing_types():
    """All 20 existing FieldType values have registry entries in XFormsRenderer."""
    pytest.importorskip("lxml", reason="lxml not installed")
    from parrot_formdesigner.renderers.xforms import XFormsRenderer
    from parrot_formdesigner.renderers.base import FieldRenderer

    renderer = XFormsRenderer()
    for ft in FieldType:
        assert ft in renderer._registry, f"XFormsRenderer registry missing {ft}"
        assert isinstance(renderer._registry[ft], FieldRenderer), f"Invalid renderer for {ft}"


@pytest.mark.asyncio
async def test_jsonschema_registry_dispatch_existing_types():
    """All 20 existing FieldType values have registry entries in JsonSchemaRenderer."""
    from parrot_formdesigner.renderers.jsonschema import JsonSchemaRenderer
    from parrot_formdesigner.renderers.base import FieldRenderer

    renderer = JsonSchemaRenderer()
    for ft in FieldType:
        assert ft in renderer._registry, f"JsonSchemaRenderer registry missing {ft}"
        assert isinstance(renderer._registry[ft], FieldRenderer), f"Invalid renderer for {ft}"


@pytest.mark.asyncio
async def test_telegram_registry_dispatch_existing_types():
    """All 20 existing FieldType values have registry entries in TelegramRenderer."""
    from parrot_formdesigner.renderers.telegram.renderer import TelegramRenderer
    from parrot_formdesigner.renderers.base import FieldRenderer

    renderer = TelegramRenderer()
    for ft in FieldType:
        assert ft in renderer._registry, f"TelegramRenderer registry missing {ft}"
        assert isinstance(renderer._registry[ft], FieldRenderer), f"Invalid renderer for {ft}"


def test_field_renderer_protocol_minimal():
    """FieldRenderer is a Protocol; FallbackRenderer satisfies it."""
    # FallbackRenderer must be a concrete, instantiable class
    fb = FallbackRenderer()
    assert fb is not None
    # FallbackRenderer must satisfy the FieldRenderer protocol (runtime-checkable)
    assert isinstance(fb, FieldRenderer)


@pytest.mark.asyncio
async def test_fallback_renderer_returns_none():
    """FallbackRenderer.render() returns None as placeholder."""
    fb = FallbackRenderer()
    field = FormField(field_id="x", field_type=FieldType.TEXT, label="X")
    result = await fb.render(field)
    assert result is None


@pytest.fixture
def sample_schema() -> FormSchema:
    return FormSchema(
        form_id="test",
        title="Test Form",
        sections=[
            FormSection(
                section_id="main",
                title="Main",
                fields=[
                    FormField(field_id="name", field_type=FieldType.TEXT, label="Name"),
                    FormField(field_id="email", field_type=FieldType.EMAIL, label="Email"),
                ],
            )
        ],
    )


@pytest.mark.asyncio
async def test_html5_registry_dispatch_existing_types():
    """All 20 existing FieldType values render via registry without error."""
    from parrot_formdesigner.renderers.html5 import HTML5Renderer

    renderer = HTML5Renderer()
    existing_types = [
        FieldType.TEXT, FieldType.TEXT_AREA, FieldType.NUMBER, FieldType.INTEGER,
        FieldType.BOOLEAN, FieldType.DATE, FieldType.DATETIME, FieldType.TIME,
        FieldType.SELECT, FieldType.MULTI_SELECT, FieldType.FILE, FieldType.IMAGE,
        FieldType.COLOR, FieldType.URL, FieldType.EMAIL, FieldType.PHONE,
        FieldType.PASSWORD, FieldType.HIDDEN, FieldType.GROUP, FieldType.ARRAY,
    ]
    for ft in existing_types:
        field = FormField(field_id="f1", field_type=ft, label="Test")
        form = FormSchema(
            form_id="test", title="T",
            sections=[FormSection(section_id="s1", fields=[field])]
        )
        result = await renderer.render(form)
        assert result.content is not None, f"Renderer returned None for {ft}"


class TestHTML5Renderer:
    async def test_renders_html_string(self, sample_schema):
        renderer = HTML5Renderer()
        result = await renderer.render(sample_schema)
        html = result.output if hasattr(result, "output") else str(result)
        assert isinstance(html, str)
        assert len(html) > 0

    async def test_contains_form_fields(self, sample_schema):
        renderer = HTML5Renderer()
        result = await renderer.render(sample_schema)
        html = result.output if hasattr(result, "output") else str(result)
        assert "name" in html.lower() or "email" in html.lower()

    async def test_input_value_xss_escaped(self):
        """Input value with XSS payload must be HTML-escaped in the output."""
        schema = FormSchema(
            form_id="xss-test",
            title="XSS Test",
            sections=[
                FormSection(
                    section_id="s1",
                    title="Section",
                    fields=[
                        FormField(field_id="msg", field_type=FieldType.TEXT, label="Message"),
                    ],
                )
            ],
        )
        renderer = HTML5Renderer()
        result = await renderer.render(
            schema,
            prefilled={"msg": '<script>alert("xss")</script>'},
        )
        output = result.content if hasattr(result, "content") else str(result)
        # Raw script tag must NOT appear in output
        assert "<script>" not in output
        # Escaped form must be present
        assert "&lt;script&gt;" in output

    async def test_textarea_value_xss_escaped(self):
        """Textarea content with special HTML chars must be escaped."""
        schema = FormSchema(
            form_id="xss-textarea",
            title="XSS Textarea",
            sections=[
                FormSection(
                    section_id="s1",
                    title="Section",
                    fields=[
                        FormField(
                            field_id="notes",
                            field_type=FieldType.TEXT_AREA,
                            label="Notes",
                        ),
                    ],
                )
            ],
        )
        renderer = HTML5Renderer()
        result = await renderer.render(
            schema,
            prefilled={"notes": '<b>bold</b> & "quoted"'},
        )
        output = result.content if hasattr(result, "content") else str(result)
        assert "<b>" not in output
        assert "&lt;b&gt;" in output
        assert "&amp;" in output

    async def test_input_value_quotes_escaped(self):
        """Double-quotes in input value must be escaped to prevent attribute breakout."""
        schema = FormSchema(
            form_id="quote-test",
            title="Quote Test",
            sections=[
                FormSection(
                    section_id="s1",
                    title="Section",
                    fields=[
                        FormField(field_id="q", field_type=FieldType.TEXT, label="Q"),
                    ],
                )
            ],
        )
        renderer = HTML5Renderer()
        result = await renderer.render(
            schema,
            prefilled={"q": 'say "hello"'},
        )
        output = result.content if hasattr(result, "content") else str(result)
        # Raw unescaped double-quote inside attribute value must not appear
        assert 'value="say "hello""' not in output
        assert "&quot;" in output


class TestJsonSchemaRenderer:
    async def test_renders_schema(self, sample_schema):
        renderer = JsonSchemaRenderer()
        result = await renderer.render(sample_schema)
        assert result is not None

    async def test_returns_renderedform(self, sample_schema):
        renderer = JsonSchemaRenderer()
        result = await renderer.render(sample_schema)
        output = result.output if hasattr(result, "output") else result
        assert output is not None


@pytest.mark.asyncio
async def test_pdf_registry_dispatch_existing_types():
    """All 20 existing FieldType values have registry entries in PdfRenderer."""
    pytest.importorskip("reportlab", reason="reportlab not installed")
    from parrot_formdesigner.renderers.pdf import PdfRenderer
    from parrot_formdesigner.renderers.base import FieldRenderer

    renderer = PdfRenderer()
    existing_types = [
        FieldType.TEXT, FieldType.TEXT_AREA, FieldType.NUMBER, FieldType.INTEGER,
        FieldType.BOOLEAN, FieldType.DATE, FieldType.DATETIME, FieldType.TIME,
        FieldType.SELECT, FieldType.MULTI_SELECT, FieldType.FILE, FieldType.IMAGE,
        FieldType.COLOR, FieldType.URL, FieldType.EMAIL, FieldType.PHONE,
        FieldType.PASSWORD, FieldType.HIDDEN, FieldType.GROUP, FieldType.ARRAY,
    ]
    for ft in existing_types:
        assert ft in renderer._registry, f"PdfRenderer registry missing {ft}"
        assert isinstance(renderer._registry[ft], FieldRenderer), f"Invalid renderer for {ft}"


@pytest.mark.asyncio
async def test_adaptive_card_registry_dispatch_existing_types():
    """All 20 existing FieldType values render via registry without error."""
    from parrot_formdesigner.renderers.adaptive_card import AdaptiveCardRenderer

    renderer = AdaptiveCardRenderer()
    existing_types = [
        FieldType.TEXT, FieldType.TEXT_AREA, FieldType.NUMBER, FieldType.INTEGER,
        FieldType.BOOLEAN, FieldType.DATE, FieldType.DATETIME, FieldType.TIME,
        FieldType.SELECT, FieldType.MULTI_SELECT, FieldType.FILE, FieldType.IMAGE,
        FieldType.COLOR, FieldType.URL, FieldType.EMAIL, FieldType.PHONE,
        FieldType.PASSWORD, FieldType.HIDDEN, FieldType.GROUP, FieldType.ARRAY,
    ]
    for ft in existing_types:
        field = FormField(field_id="f1", field_type=ft, label="Test")
        form = FormSchema(
            form_id="test", title="T",
            sections=[FormSection(section_id="s1", fields=[field])]
        )
        result = await renderer.render(form)
        assert result.content is not None, f"Adaptive Card returned None for {ft}"


class TestAdaptiveCardRenderer:
    async def test_renders_adaptive_card(self, sample_schema):
        renderer = AdaptiveCardRenderer()
        result = await renderer.render(sample_schema)
        assert result is not None


# TASK-1151: Per-type renderer coverage matrix and fallback warning tests

@pytest.mark.asyncio
async def test_renderer_fallback_emits_warning():
    """PDF rendering of SIGNATURE produces placeholder + appends RenderWarning."""
    pytest.importorskip("reportlab", reason="reportlab not installed")
    from parrot_formdesigner.renderers.pdf import PdfRenderer
    from parrot_formdesigner.core.schema import RenderWarning

    renderer = PdfRenderer()
    sig_field = FormField(
        field_id="sig1", field_type=FieldType.SIGNATURE, label="Signature"
    )
    form = FormSchema(
        form_id="t", title="T",
        sections=[FormSection(section_id="s", fields=[sig_field])]
    )
    result = await renderer.render(form)
    assert len(result.warnings) >= 1
    w = result.warnings[0]
    assert w.field_type == "signature"
    assert w.renderer == "pdf"
    assert "placeholder" in w.reason.lower() or "unsupported" in w.reason.lower()


@pytest.mark.asyncio
async def test_renderer_coverage_matrix():
    """Each (FieldType, renderer) pair produces output or a warning. No silent None."""
    from parrot_formdesigner.renderers.html5 import HTML5Renderer
    from parrot_formdesigner.renderers.jsonschema import JsonSchemaRenderer

    new_types = [
        FieldType.SIGNATURE, FieldType.DYNAMIC_SELECT, FieldType.TRANSFER_LIST,
        FieldType.REMOTE_RESPONSE, FieldType.AVAILABILITY, FieldType.LOCATION,
        FieldType.TAGS, FieldType.NPS, FieldType.LIKERT, FieldType.RANKING,
    ]
    for renderer in [HTML5Renderer(), JsonSchemaRenderer()]:
        for ft in new_types:
            field = FormField(field_id="f1", field_type=ft, label="Test")
            form = FormSchema(
                form_id="t", title="T",
                sections=[FormSection(section_id="s", fields=[field])]
            )
            result = await renderer.render(form)
            assert result is not None, f"{renderer.__class__.__name__} returned None for {ft}"
            assert result.content is not None, (
                f"{renderer.__class__.__name__} content is None for {ft}"
            )


@pytest.mark.asyncio
async def test_html5_new_types_render_without_error():
    """HTML5 renders all 10 new FieldType values without raising exceptions."""
    from parrot_formdesigner.renderers.html5 import HTML5Renderer

    renderer = HTML5Renderer()
    new_types = [
        FieldType.SIGNATURE, FieldType.DYNAMIC_SELECT, FieldType.TRANSFER_LIST,
        FieldType.REMOTE_RESPONSE, FieldType.AVAILABILITY, FieldType.LOCATION,
        FieldType.TAGS, FieldType.NPS, FieldType.LIKERT, FieldType.RANKING,
    ]
    for ft in new_types:
        field = FormField(field_id="f1", field_type=ft, label="Test")
        form = FormSchema(
            form_id="test", title="T",
            sections=[FormSection(section_id="s1", fields=[field])]
        )
        result = await renderer.render(form)
        assert result.content is not None, f"HTML5Renderer returned None content for {ft}"
        assert len(result.content) > 0, f"HTML5Renderer returned empty content for {ft}"


@pytest.mark.asyncio
async def test_adaptive_card_fallback_types_emit_warnings():
    """SIGNATURE, REMOTE_RESPONSE, AVAILABILITY emit RenderWarning in AdaptiveCard."""
    from parrot_formdesigner.renderers.adaptive_card import AdaptiveCardRenderer

    renderer = AdaptiveCardRenderer()
    fallback_types = [
        FieldType.SIGNATURE,
        FieldType.REMOTE_RESPONSE,
        FieldType.AVAILABILITY,
    ]
    for ft in fallback_types:
        field = FormField(field_id="f1", field_type=ft, label="Test")
        form = FormSchema(
            form_id="t", title="T",
            sections=[FormSection(section_id="s", fields=[field])]
        )
        result = await renderer.render(form)
        assert result.content is not None
        assert len(result.warnings) >= 1, (
            f"AdaptiveCardRenderer should emit warning for {ft}"
        )
        w = result.warnings[0]
        assert w.field_type == ft.value
        assert w.renderer == "adaptive_card"


@pytest.mark.asyncio
async def test_jsonschema_new_types_have_format():
    """JsonSchemaRenderer emits 'format' keyword for all 10 new FieldTypes."""
    from parrot_formdesigner.renderers.jsonschema import JsonSchemaRenderer

    renderer = JsonSchemaRenderer()
    new_types = {
        FieldType.SIGNATURE: "signature",
        FieldType.DYNAMIC_SELECT: "dynamic-select",
        FieldType.TRANSFER_LIST: "transfer-list",
        FieldType.REMOTE_RESPONSE: "remote-response",
        FieldType.AVAILABILITY: "availability",
        FieldType.LOCATION: "iso-country",
        FieldType.TAGS: "tags",
        FieldType.NPS: "nps",
        FieldType.LIKERT: "likert",
        FieldType.RANKING: "ranking",
    }
    for ft, expected_format in new_types.items():
        field = FormField(field_id="f1", field_type=ft, label="Test")
        form = FormSchema(
            form_id="t", title="T",
            sections=[FormSection(section_id="s", fields=[field])]
        )
        result = await renderer.render(form)
        schema = result.content
        prop = schema["properties"]["f1"]
        assert prop.get("format") == expected_format, (
            f"JsonSchema format for {ft} should be {expected_format!r}, got {prop.get('format')!r}"
        )


@pytest.mark.asyncio
async def test_telegram_new_types_classified():
    """All 10 new FieldTypes appear in either _INLINE_FIELD_TYPES or _WEBAPP_FIELD_TYPES."""
    from parrot_formdesigner.renderers.telegram.renderer import (
        TelegramRenderer, _INLINE_FIELD_TYPES, _WEBAPP_FIELD_TYPES
    )

    new_types = [
        FieldType.SIGNATURE, FieldType.DYNAMIC_SELECT, FieldType.TRANSFER_LIST,
        FieldType.REMOTE_RESPONSE, FieldType.AVAILABILITY, FieldType.LOCATION,
        FieldType.TAGS, FieldType.NPS, FieldType.LIKERT, FieldType.RANKING,
    ]
    inline_expected = {
        FieldType.NPS, FieldType.LIKERT, FieldType.RANKING,
        FieldType.LOCATION, FieldType.DYNAMIC_SELECT,
    }
    webapp_expected = {
        FieldType.SIGNATURE, FieldType.TRANSFER_LIST, FieldType.REMOTE_RESPONSE,
        FieldType.AVAILABILITY, FieldType.TAGS,
    }
    for ft in new_types:
        in_inline = ft in _INLINE_FIELD_TYPES
        in_webapp = ft in _WEBAPP_FIELD_TYPES
        assert in_inline or in_webapp, f"{ft} not classified in either Telegram set"
        if ft in inline_expected:
            assert in_inline, f"{ft} should be in _INLINE_FIELD_TYPES"
        if ft in webapp_expected:
            assert in_webapp, f"{ft} should be in _WEBAPP_FIELD_TYPES"
