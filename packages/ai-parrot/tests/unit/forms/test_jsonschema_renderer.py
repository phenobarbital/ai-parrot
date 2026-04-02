"""Unit tests for JsonSchemaRenderer."""

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
    LayoutType,
    StyleSchema,
)
from parrot.forms.renderers.jsonschema import JsonSchemaRenderer


@pytest.fixture
def renderer():
    """JsonSchemaRenderer instance."""
    return JsonSchemaRenderer()


@pytest.fixture
def sample_form():
    """Sample form with text, integer, and email fields."""
    return FormSchema(
        form_id="test",
        title="Test Form",
        sections=[
            FormSection(
                section_id="s1",
                title="Section 1",
                fields=[
                    FormField(
                        field_id="name",
                        field_type=FieldType.TEXT,
                        label="Name",
                        required=True,
                        constraints=FieldConstraints(min_length=2, max_length=100),
                    ),
                    FormField(
                        field_id="age",
                        field_type=FieldType.INTEGER,
                        label="Age",
                        constraints=FieldConstraints(min_value=0, max_value=150),
                    ),
                    FormField(
                        field_id="email",
                        field_type=FieldType.EMAIL,
                        label="Email",
                    ),
                ],
            )
        ],
    )


class TestJsonSchemaRendererStructure:
    """Tests for basic JSON Schema structural output."""

    async def test_structural_output_type(self, renderer, sample_form):
        """Top-level schema is type=object."""
        result = await renderer.render(sample_form)
        assert result.content["type"] == "object"

    async def test_schema_keyword(self, renderer, sample_form):
        """$schema keyword is present."""
        result = await renderer.render(sample_form)
        assert "$schema" in result.content

    async def test_properties_present(self, renderer, sample_form):
        """All fields appear as properties."""
        result = await renderer.render(sample_form)
        props = result.content["properties"]
        assert "name" in props
        assert "age" in props
        assert "email" in props

    async def test_string_type(self, renderer, sample_form):
        """TEXT field maps to type=string."""
        result = await renderer.render(sample_form)
        assert result.content["properties"]["name"]["type"] == "string"

    async def test_integer_type(self, renderer, sample_form):
        """INTEGER field maps to type=integer."""
        result = await renderer.render(sample_form)
        assert result.content["properties"]["age"]["type"] == "integer"

    async def test_required_array(self, renderer, sample_form):
        """Required fields appear in top-level required array."""
        result = await renderer.render(sample_form)
        assert "name" in result.content.get("required", [])
        assert "age" not in result.content.get("required", [])

    async def test_content_type(self, renderer, sample_form):
        """Content type is application/schema+json."""
        result = await renderer.render(sample_form)
        assert result.content_type == "application/schema+json"


class TestJsonSchemaRendererConstraints:
    """Tests for constraint mapping to JSON Schema keywords."""

    async def test_min_max_length(self, renderer, sample_form):
        """min_length and max_length map to minLength/maxLength."""
        result = await renderer.render(sample_form)
        name_prop = result.content["properties"]["name"]
        assert name_prop["minLength"] == 2
        assert name_prop["maxLength"] == 100

    async def test_minimum_maximum(self, renderer, sample_form):
        """min_value and max_value map to minimum/maximum."""
        result = await renderer.render(sample_form)
        age_prop = result.content["properties"]["age"]
        assert age_prop["minimum"] == 0
        assert age_prop["maximum"] == 150

    async def test_pattern_constraint(self, renderer):
        """pattern constraint maps to JSON Schema pattern."""
        form = FormSchema(
            form_id="t",
            title="T",
            sections=[FormSection(section_id="s", fields=[
                FormField(
                    field_id="zip",
                    field_type=FieldType.TEXT,
                    label="ZIP",
                    constraints=FieldConstraints(pattern=r"^\d{5}$"),
                )
            ])]
        )
        result = await renderer.render(form)
        assert result.content["properties"]["zip"]["pattern"] == r"^\d{5}$"


class TestJsonSchemaRendererExtensions:
    """Tests for x- extension keywords."""

    async def test_x_field_type(self, renderer, sample_form):
        """x-field-type extension is present with FieldType value."""
        result = await renderer.render(sample_form)
        assert result.content["properties"]["name"]["x-field-type"] == "text"
        assert result.content["properties"]["email"]["x-field-type"] == "email"

    async def test_x_section(self, renderer, sample_form):
        """x-section extension contains section metadata."""
        result = await renderer.render(sample_form)
        section_meta = result.content["properties"]["name"]["x-section"]
        assert section_meta["section_id"] == "s1"
        assert section_meta["title"] == "Section 1"

    async def test_x_depends_on(self, renderer):
        """x-depends-on extension present when field has depends_on."""
        form = FormSchema(
            form_id="t",
            title="T",
            sections=[FormSection(section_id="s", fields=[
                FormField(
                    field_id="extra",
                    field_type=FieldType.TEXT,
                    label="Extra",
                    depends_on=DependencyRule(
                        conditions=[
                            FieldCondition(
                                field_id="toggle",
                                operator=ConditionOperator.EQ,
                                value=True,
                            )
                        ],
                        effect="show",
                    ),
                ),
            ])]
        )
        result = await renderer.render(form)
        prop = result.content["properties"]["extra"]
        assert "x-depends-on" in prop
        assert prop["x-field-type"] == "text"

    async def test_email_format(self, renderer, sample_form):
        """EMAIL field has format=email."""
        result = await renderer.render(sample_form)
        assert result.content["properties"]["email"]["format"] == "email"

    async def test_x_placeholder(self, renderer):
        """x-placeholder extension present when placeholder is set."""
        form = FormSchema(
            form_id="t",
            title="T",
            sections=[FormSection(section_id="s", fields=[
                FormField(
                    field_id="f",
                    field_type=FieldType.TEXT,
                    label="F",
                    placeholder="Type here...",
                )
            ])]
        )
        result = await renderer.render(form)
        assert result.content["properties"]["f"]["x-placeholder"] == "Type here..."

    async def test_x_read_only(self, renderer):
        """readOnly and x-read-only extensions present for read-only fields."""
        form = FormSchema(
            form_id="t",
            title="T",
            sections=[FormSection(section_id="s", fields=[
                FormField(
                    field_id="f",
                    field_type=FieldType.TEXT,
                    label="F",
                    read_only=True,
                )
            ])]
        )
        result = await renderer.render(form)
        prop = result.content["properties"]["f"]
        assert prop.get("readOnly") is True
        assert prop.get("x-read-only") is True


class TestJsonSchemaRendererSelectField:
    """Tests for SELECT and MULTI_SELECT field rendering."""

    async def test_select_with_enum(self, renderer):
        """SELECT field produces enum array."""
        form = FormSchema(
            form_id="t",
            title="T",
            sections=[FormSection(section_id="s", fields=[
                FormField(
                    field_id="color",
                    field_type=FieldType.SELECT,
                    label="Color",
                    options=[
                        FieldOption(value="red", label="Red"),
                        FieldOption(value="blue", label="Blue"),
                    ],
                )
            ])]
        )
        result = await renderer.render(form)
        prop = result.content["properties"]["color"]
        assert "enum" in prop
        assert set(prop["enum"]) == {"red", "blue"}

    async def test_multi_select_items(self, renderer):
        """MULTI_SELECT field produces array with items.enum."""
        form = FormSchema(
            form_id="t",
            title="T",
            sections=[FormSection(section_id="s", fields=[
                FormField(
                    field_id="tags",
                    field_type=FieldType.MULTI_SELECT,
                    label="Tags",
                    options=[
                        FieldOption(value="a", label="A"),
                        FieldOption(value="b", label="B"),
                    ],
                )
            ])]
        )
        result = await renderer.render(form)
        prop = result.content["properties"]["tags"]
        assert prop["type"] == "array"
        assert "items" in prop
        assert set(prop["items"]["enum"]) == {"a", "b"}


class TestJsonSchemaRendererStyleOutput:
    """Tests for style_output."""

    async def test_style_output_present(self, renderer, sample_form):
        """style_output is None when no StyleSchema provided."""
        result = await renderer.render(sample_form)
        assert result.style_output is None

    async def test_style_output_with_style(self, renderer, sample_form):
        """style_output contains serialized StyleSchema."""
        style = StyleSchema(layout=LayoutType.TWO_COLUMN, submit_label="Send")
        result = await renderer.render(sample_form, style)
        assert result.style_output is not None
        assert result.style_output["layout"] == "two_column"
        assert result.style_output["submit_label"] == "Send"


class TestJsonSchemaRendererI18n:
    """Tests for i18n label resolution."""

    async def test_i18n_title_es(self, renderer):
        """Spanish locale resolves title to Spanish."""
        form = FormSchema(
            form_id="t",
            title={"en": "Test Form", "es": "Formulario de Prueba"},
            sections=[FormSection(section_id="s", fields=[
                FormField(field_id="f", field_type=FieldType.TEXT, label="F")
            ])]
        )
        result = await renderer.render(form, locale="es")
        assert result.content["title"] == "Formulario de Prueba"

    async def test_i18n_field_label(self, renderer):
        """Spanish locale resolves field labels to Spanish."""
        form = FormSchema(
            form_id="t",
            title="T",
            sections=[FormSection(section_id="s", fields=[
                FormField(
                    field_id="name",
                    field_type=FieldType.TEXT,
                    label={"en": "Name", "es": "Nombre"},
                )
            ])]
        )
        result_es = await renderer.render(form, locale="es")
        result_en = await renderer.render(form, locale="en")
        assert result_es.content["properties"]["name"]["title"] == "Nombre"
        assert result_en.content["properties"]["name"]["title"] == "Name"


class TestJsonSchemaRendererPrefilled:
    """Tests for pre-filled default values."""

    async def test_prefilled_as_default(self, renderer, sample_form):
        """Prefilled values appear as property default."""
        result = await renderer.render(sample_form, prefilled={"name": "Alice"})
        assert result.content["properties"]["name"]["default"] == "Alice"

    async def test_field_default_preserved(self, renderer):
        """Field default value appears as property default."""
        form = FormSchema(
            form_id="t",
            title="T",
            sections=[FormSection(section_id="s", fields=[
                FormField(
                    field_id="count",
                    field_type=FieldType.INTEGER,
                    label="Count",
                    default=5,
                )
            ])]
        )
        result = await renderer.render(form)
        assert result.content["properties"]["count"]["default"] == 5
