"""Unit tests for parrot-formdesigner renderers."""
import pytest
from parrot_formdesigner.core import FormSchema, FormSection
from parrot_formdesigner.core.schema import FormField
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.renderers import HTML5Renderer, JsonSchemaRenderer, AdaptiveCardRenderer
from parrot_formdesigner.renderers.base import FieldRenderer, FallbackRenderer
from parrot_formdesigner.core.style import StyleSchema


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
