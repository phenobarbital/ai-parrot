"""Smoke test for the public API re-exports of parrot.outputs.cards."""


class TestPublicAPI:
    def test_all_imports(self):
        from parrot.outputs.cards import (
            ACAction, ACElement, ActionOpenUrl, ActionShowCard,
            ActionSubmit, ActionToggleVisibility, AutoCollapsePolicy,
            CardRenderError, CardSpec, CodeSection, Container,
            DetailField, DetailSection, FactSet, FormFieldSpec,
            FormSection, Image, ImageEntry, ImageSection,
            InputChoiceSet, InputText, MetricEntry, MetricsSection,
            RawElementsSection, StatusSection, Table, TableSection,
            TextBlock, TextSection, ToggleGroup, ToggleSection,
            build_attachment, markdown_to_sections, render, render_text,
        )
        # All importable without error
        assert CardSpec is not None
