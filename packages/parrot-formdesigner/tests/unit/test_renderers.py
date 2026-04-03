"""Unit tests for parrot-formdesigner renderers."""
import pytest
from parrot.formdesigner.core import FormSchema, FormSection
from parrot.formdesigner.core.schema import FormField
from parrot.formdesigner.core.types import FieldType
from parrot.formdesigner.renderers import HTML5Renderer, JsonSchemaRenderer, AdaptiveCardRenderer
from parrot.formdesigner.core.style import StyleSchema


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


class TestAdaptiveCardRenderer:
    async def test_renders_adaptive_card(self, sample_schema):
        renderer = AdaptiveCardRenderer()
        result = await renderer.render(sample_schema)
        assert result is not None
