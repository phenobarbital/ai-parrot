"""Integration test: MS Teams integration imports are unaffected by parrot-formdesigner."""
import pytest
from pathlib import Path

# Path to worktree root (4 levels up from this file)
_WORKTREE_ROOT = Path(__file__).parents[4]


class TestMSTeamsIntegrationImports:
    def test_adaptive_card_renderer_import(self):
        from parrot.forms.renderers.adaptive_card import AdaptiveCardRenderer
        assert AdaptiveCardRenderer is not None

    def test_form_schema_import(self):
        from parrot.forms import FormSchema, FieldType, FormField, FormSection
        schema = FormSchema(
            form_id="msteams-dialog",
            title="MS Teams Dialog",
            sections=[
                FormSection(
                    section_id="main",
                    title="Main",
                    fields=[
                        FormField(field_id="choice", field_type=FieldType.TEXT, label="Choice"),
                    ],
                )
            ],
        )
        assert schema.form_id == "msteams-dialog"

    def test_registry_import(self):
        from parrot.forms import FormRegistry
        registry = FormRegistry()
        assert registry is not None

    def test_validator_import(self):
        from parrot.forms import FormValidator
        validator = FormValidator()
        assert validator is not None

    def test_example_form_server_is_short(self):
        """form_server.py must be under 50 lines as per spec acceptance criterion."""
        form_server = _WORKTREE_ROOT / "examples" / "forms" / "form_server.py"
        with open(form_server) as f:
            lines = [line for line in f.readlines() if line.strip()]
        assert len(lines) < 50, f"form_server.py has {len(lines)} non-empty lines, expected < 50"

    def test_example_uses_setup_form_routes(self):
        """Simplified form_server.py must use setup_form_routes."""
        form_server = _WORKTREE_ROOT / "examples" / "forms" / "form_server.py"
        with open(form_server) as f:
            content = f.read()
        assert "setup_form_routes" in content
        assert "parrot.formdesigner" in content
