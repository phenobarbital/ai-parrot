"""Verify that old parrot.forms import paths remain functional after parrot-formdesigner extraction."""
import pytest


class TestBackwardCompatImports:
    def test_import_form_schema(self):
        from parrot.forms import FormSchema
        assert FormSchema is not None

    def test_import_create_form_tool(self):
        from parrot.forms import CreateFormTool
        assert CreateFormTool is not None

    def test_import_form_registry(self):
        from parrot.forms import FormRegistry
        assert FormRegistry is not None

    def test_import_form_validator(self):
        from parrot.forms import FormValidator
        assert FormValidator is not None

    def test_import_html5_renderer(self):
        from parrot.forms.renderers.html5 import HTML5Renderer
        assert HTML5Renderer is not None

    def test_import_style_schema(self):
        from parrot.forms import StyleSchema
        assert StyleSchema is not None

    def test_import_field_type(self):
        from parrot.forms import FieldType
        assert FieldType is not None

    def test_import_form_cache(self):
        from parrot.forms import FormCache
        assert FormCache is not None

    def test_import_database_form_tool(self):
        from parrot.forms import DatabaseFormTool
        assert DatabaseFormTool is not None

    def test_no_circular_import(self):
        import parrot.formdesigner  # noqa: F401
        import parrot.forms  # noqa: F401

    def test_form_schema_is_same_class(self):
        """Both imports refer to the same class."""
        from parrot.formdesigner import FormSchema as FD
        from parrot.forms import FormSchema as FS
        assert FD is FS


class TestMSTeamsCompatibility:
    def test_form_schema_construction(self):
        from parrot.forms import FormSchema, FieldType, FormField, FormSection
        schema = FormSchema(
            form_id="msteams-test",
            title="Test",
            sections=[
                FormSection(
                    section_id="main",
                    title="Main",
                    fields=[FormField(field_id="q", field_type=FieldType.TEXT, label="Q")],
                )
            ],
        )
        assert schema.form_id == "msteams-test"

    def test_adaptive_card_renderer_import(self):
        from parrot.forms.renderers.adaptive_card import AdaptiveCardRenderer
        assert AdaptiveCardRenderer is not None
