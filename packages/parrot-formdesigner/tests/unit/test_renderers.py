"""Unit tests for parrot-formdesigner renderers."""
import pytest
from parrot.formdesigner.core import FormSchema, FormSection
from parrot.formdesigner.core.schema import FormField
from parrot.formdesigner.core.types import FieldType
from parrot.formdesigner.renderers import HTML5Renderer, JsonSchemaRenderer, AdaptiveCardRenderer


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
