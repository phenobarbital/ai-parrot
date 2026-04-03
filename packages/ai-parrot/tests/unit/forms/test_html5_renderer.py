"""Unit tests for HTML5Renderer."""

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
    SubmitAction,
)
from parrot.forms.renderers.html5 import HTML5Renderer


@pytest.fixture
def renderer():
    """HTML5Renderer instance."""
    return HTML5Renderer()


@pytest.fixture
def sample_form():
    """Sample form with text and email fields, submit action."""
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
                        constraints=FieldConstraints(min_length=2, max_length=100),
                    ),
                    FormField(
                        field_id="email",
                        field_type=FieldType.EMAIL,
                        label="Email",
                    ),
                ],
            )
        ],
        submit=SubmitAction(action_type="endpoint", action_ref="/api/submit", method="POST"),
    )


class TestHTML5RendererStructure:
    """Tests for form structure."""

    async def test_renders_form_fragment(self, renderer, sample_form):
        """Output contains <form> and </form> tags."""
        result = await renderer.render(sample_form)
        assert "<form" in result.content
        assert "</form>" in result.content

    async def test_not_full_page(self, renderer, sample_form):
        """Output is a fragment, not a full HTML page."""
        result = await renderer.render(sample_form)
        assert "<html" not in result.content
        assert "<head" not in result.content
        assert "<body" not in result.content

    async def test_content_type(self, renderer, sample_form):
        """Content type is text/html."""
        result = await renderer.render(sample_form)
        assert result.content_type == "text/html"

    async def test_form_id_in_html(self, renderer, sample_form):
        """Form ID appears in the form element."""
        result = await renderer.render(sample_form)
        assert "test" in result.content


class TestHTML5RendererValidation:
    """Tests for HTML5 validation attributes."""

    async def test_required_attribute(self, renderer, sample_form):
        """Required fields have the 'required' attribute."""
        result = await renderer.render(sample_form)
        assert "required" in result.content

    async def test_minlength_attribute(self, renderer, sample_form):
        """min_length constraint maps to minlength attribute."""
        result = await renderer.render(sample_form)
        assert 'minlength="2"' in result.content

    async def test_maxlength_attribute(self, renderer, sample_form):
        """max_length constraint maps to maxlength attribute."""
        result = await renderer.render(sample_form)
        assert 'maxlength="100"' in result.content

    async def test_pattern_attribute(self, renderer):
        """pattern constraint maps to pattern attribute."""
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
        assert "pattern=" in result.content

    async def test_min_max_for_number(self, renderer):
        """min_value/max_value map to min/max attributes for NUMBER."""
        form = FormSchema(
            form_id="t",
            title="T",
            sections=[FormSection(section_id="s", fields=[
                FormField(
                    field_id="age",
                    field_type=FieldType.NUMBER,
                    label="Age",
                    constraints=FieldConstraints(min_value=0, max_value=150),
                )
            ])]
        )
        result = await renderer.render(form)
        assert 'min="0.0"' in result.content
        assert 'max="150.0"' in result.content


class TestHTML5RendererSubmitAction:
    """Tests for submit action rendering."""

    async def test_submit_action_action_attr(self, renderer, sample_form):
        """Submit action_ref appears as the form action attribute."""
        result = await renderer.render(sample_form)
        assert 'action="/api/submit"' in result.content

    async def test_submit_action_method_attr(self, renderer, sample_form):
        """Submit method appears as the form method attribute."""
        result = await renderer.render(sample_form)
        assert 'method="POST"' in result.content


class TestHTML5RendererDependsOn:
    """Tests for data-depends-on attribute."""

    async def test_depends_on_attribute(self, renderer):
        """Fields with depends_on have data-depends-on attribute."""
        form = FormSchema(
            form_id="t",
            title="T",
            sections=[
                FormSection(
                    section_id="s",
                    fields=[
                        FormField(
                            field_id="toggle",
                            field_type=FieldType.BOOLEAN,
                            label="Show extra",
                        ),
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
                    ],
                )
            ],
        )
        result = await renderer.render(form)
        assert "data-depends-on" in result.content


class TestHTML5RendererI18n:
    """Tests for i18n label resolution."""

    async def test_i18n_labels_es(self, renderer):
        """Spanish locale resolves to Spanish labels."""
        form = FormSchema(
            form_id="t",
            title="T",
            sections=[
                FormSection(
                    section_id="s",
                    fields=[
                        FormField(
                            field_id="f",
                            field_type=FieldType.TEXT,
                            label={"en": "Name", "es": "Nombre"},
                        )
                    ],
                )
            ],
        )
        result_es = await renderer.render(form, locale="es")
        assert "Nombre" in result_es.content

    async def test_i18n_labels_en(self, renderer):
        """English locale resolves to English labels."""
        form = FormSchema(
            form_id="t",
            title="T",
            sections=[
                FormSection(
                    section_id="s",
                    fields=[
                        FormField(
                            field_id="f",
                            field_type=FieldType.TEXT,
                            label={"en": "Name", "es": "Nombre"},
                        )
                    ],
                )
            ],
        )
        result_en = await renderer.render(form, locale="en")
        assert "Name" in result_en.content


class TestHTML5RendererPrefilled:
    """Tests for pre-filled values."""

    async def test_prefilled_text_value(self, renderer, sample_form):
        """Prefilled text value appears in the input element."""
        result = await renderer.render(sample_form, prefilled={"name": "Alice"})
        assert "Alice" in result.content

    async def test_errors_displayed(self, renderer, sample_form):
        """Error messages are displayed next to fields."""
        result = await renderer.render(sample_form, errors={"name": "Name is required"})
        assert "Name is required" in result.content


class TestHTML5RendererSelectField:
    """Tests for SELECT field rendering."""

    async def test_select_renders(self, renderer):
        """SELECT field produces a <select> element."""
        form = FormSchema(
            form_id="t",
            title="T",
            sections=[FormSection(section_id="s", fields=[
                FormField(
                    field_id="role",
                    field_type=FieldType.SELECT,
                    label="Role",
                    options=[
                        FieldOption(value="admin", label="Admin"),
                        FieldOption(value="user", label="User"),
                    ],
                )
            ])]
        )
        result = await renderer.render(form)
        assert "<select" in result.content
        assert "Admin" in result.content
        assert "User" in result.content

    async def test_multi_select_renders(self, renderer):
        """MULTI_SELECT field produces a multiple <select> element."""
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
        assert "multiple" in result.content
