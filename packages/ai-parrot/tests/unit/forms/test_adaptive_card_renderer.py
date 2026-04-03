"""Unit tests for AdaptiveCardRenderer."""

import pytest
from parrot.forms import (
    FieldType,
    FieldOption,
    FormField,
    FormSchema,
    FormSection,
    LayoutType,
    StyleSchema,
)
from parrot.forms.renderers.adaptive_card import AdaptiveCardRenderer


@pytest.fixture
def renderer():
    """AdaptiveCardRenderer instance."""
    return AdaptiveCardRenderer()


@pytest.fixture
def sample_form():
    """A sample form with two fields."""
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
                    ),
                    FormField(
                        field_id="role",
                        field_type=FieldType.SELECT,
                        label="Role",
                        options=[
                            FieldOption(value="admin", label="Admin"),
                            FieldOption(value="user", label="User"),
                        ],
                    ),
                ],
            )
        ],
    )


class TestAdaptiveCardRendererComplete:
    """Tests for complete form rendering."""

    async def test_complete_form_structure(self, renderer, sample_form):
        """Full form renders as valid Adaptive Card v1.5."""
        result = await renderer.render(sample_form)
        card = result.content
        assert card["type"] == "AdaptiveCard"
        assert card["version"] == "1.5"
        assert card["$schema"] == "http://adaptivecards.io/schemas/adaptive-card.json"

    async def test_body_present(self, renderer, sample_form):
        """Card has a body list."""
        result = await renderer.render(sample_form)
        assert isinstance(result.content["body"], list)
        assert len(result.content["body"]) > 0

    async def test_actions_present(self, renderer, sample_form):
        """Card has actions (submit, cancel)."""
        result = await renderer.render(sample_form)
        assert "actions" in result.content
        action_types = [a["type"] for a in result.content["actions"]]
        assert "Action.Submit" in action_types

    async def test_content_type(self, renderer, sample_form):
        """Content type is the Adaptive Card MIME type."""
        result = await renderer.render(sample_form)
        assert result.content_type == "application/vnd.microsoft.card.adaptive"

    async def test_form_title_in_body(self, renderer, sample_form):
        """Form title appears in the card body."""
        result = await renderer.render(sample_form)
        body_text = str(result.content["body"])
        assert "Test Form" in body_text


class TestAdaptiveCardRendererWizard:
    """Tests for wizard section rendering."""

    async def test_wizard_mode_section_card(self, renderer, sample_form):
        """render_section produces a valid Adaptive Card."""
        style = StyleSchema(layout=LayoutType.WIZARD)
        result = await renderer.render_section(sample_form, 0, style)
        assert result.content["type"] == "AdaptiveCard"

    async def test_wizard_single_section_no_progress(self, renderer, sample_form):
        """Single-section form does not show progress indicator."""
        result = await renderer.render_section(sample_form, 0)
        # Progress indicator only shown when total > 1
        body_text = str(result.content["body"])
        assert "Step" not in body_text

    async def test_wizard_multi_section_progress(self, renderer):
        """Multi-section form shows progress in wizard step."""
        form = FormSchema(
            form_id="t",
            title="T",
            sections=[
                FormSection(section_id="s1", title="Step 1",
                            fields=[FormField(field_id="a", field_type=FieldType.TEXT, label="A")]),
                FormSection(section_id="s2", title="Step 2",
                            fields=[FormField(field_id="b", field_type=FieldType.TEXT, label="B")]),
            ],
        )
        result = await renderer.render_section(form, 0)
        body_text = str(result.content["body"])
        assert "Step" in body_text


class TestAdaptiveCardRendererPrefilled:
    """Tests for pre-filled values."""

    async def test_prefilled_values(self, renderer, sample_form):
        """Prefilled values appear in the card JSON."""
        result = await renderer.render(sample_form, prefilled={"name": "Alice"})
        card_json = str(result.content)
        assert "Alice" in card_json

    async def test_prefilled_select_value(self, renderer, sample_form):
        """Prefilled SELECT value appears in choices input."""
        result = await renderer.render(sample_form, prefilled={"role": "admin"})
        card_json = str(result.content)
        assert "admin" in card_json


class TestAdaptiveCardRendererErrors:
    """Tests for error display."""

    async def test_field_error_displayed(self, renderer, sample_form):
        """Field error message appears in the card body."""
        result = await renderer.render(sample_form, errors={"name": "Name is required"})
        body_text = str(result.content["body"])
        assert "Name is required" in body_text

    async def test_render_error_card(self, renderer):
        """render_error produces an error card with messages."""
        result = await renderer.render_error("Validation Failed", ["Field A is required", "Field B too long"])
        card = result.content
        assert card["type"] == "AdaptiveCard"
        body_text = str(card["body"])
        assert "Field A is required" in body_text


class TestAdaptiveCardRendererI18n:
    """Tests for i18n label resolution."""

    async def test_i18n_label(self, renderer):
        """i18n labels are resolved to the correct locale."""
        form = FormSchema(
            form_id="t",
            title={"en": "Test", "es": "Prueba"},
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
        result_es = await renderer.render(form, locale="es")
        assert "Name" in str(result_en.content)
        assert "Nombre" in str(result_es.content)
        assert "Test" in str(result_en.content)
        assert "Prueba" in str(result_es.content)


class TestAdaptiveCardRendererSummary:
    """Tests for summary card rendering."""

    async def test_summary_card(self, renderer, sample_form):
        """render_summary produces a confirmation card."""
        result = await renderer.render_summary(
            sample_form,
            {"name": "Alice", "role": "admin"},
        )
        card = result.content
        assert card["type"] == "AdaptiveCard"
        body_text = str(card["body"])
        assert "Alice" in body_text

    async def test_summary_actions(self, renderer, sample_form):
        """Summary card has confirm/edit/cancel actions."""
        result = await renderer.render_summary(sample_form, {})
        action_data = [a.get("data", {}).get("_action") for a in result.content.get("actions", [])]
        assert "confirm" in action_data
        assert "cancel" in action_data


class TestAdaptiveCardRendererFieldTypes:
    """Tests for various field type rendering."""

    async def test_boolean_field(self, renderer):
        """BOOLEAN field renders as Input.Toggle."""
        form = FormSchema(
            form_id="t",
            title="T",
            sections=[FormSection(section_id="s", fields=[
                FormField(field_id="active", field_type=FieldType.BOOLEAN, label="Active")
            ])]
        )
        result = await renderer.render(form)
        assert "Input.Toggle" in str(result.content)

    async def test_text_area_field(self, renderer):
        """TEXT_AREA field renders as multiline Input.Text."""
        form = FormSchema(
            form_id="t",
            title="T",
            sections=[FormSection(section_id="s", fields=[
                FormField(field_id="notes", field_type=FieldType.TEXT_AREA, label="Notes")
            ])]
        )
        result = await renderer.render(form)
        assert "isMultiline" in str(result.content)

    async def test_date_field(self, renderer):
        """DATE field renders as Input.Date."""
        form = FormSchema(
            form_id="t",
            title="T",
            sections=[FormSection(section_id="s", fields=[
                FormField(field_id="dob", field_type=FieldType.DATE, label="Date of Birth")
            ])]
        )
        result = await renderer.render(form)
        assert "Input.Date" in str(result.content)
