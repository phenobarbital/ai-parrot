"""Golden + composition tests for Infographic/Report (TASK-1726)."""

import json
from pathlib import Path

import pytest

from parrot.outputs.a2ui.catalog import (
    CatalogValidationError,
    ProducerOrigin,
    get_component,
    validate_envelope,
)
from parrot.outputs.a2ui.catalog.components import infographic, report

# Ensure nested children (KPICard/Chart/DataTable) are registered for delegation.
from parrot.outputs.a2ui.catalog import components as _all_components  # noqa: F401
from parrot.outputs.a2ui.models import Component, CreateSurface

GOLDEN_DIR = Path(__file__).parent / "golden"


def _dump(tree) -> bytes:
    return json.dumps(tree.model_dump(), sort_keys=True).encode()


def _infographic() -> Component:
    return Component(
        id="blk-000",
        component="Infographic",
        properties={
            "title": "Q1 Overview",
            "subtitle": "Financials",
            "theme": "ocean",
            "sections": [
                {
                    "heading": "Highlights",
                    "components": [
                        {"component": "KPICard", "properties": {"label": "Revenue", "value": 100}},
                    ],
                },
                {
                    "heading": "Trend",
                    "text": "Growth continues.",
                    "components": [
                        {
                            "component": "Chart",
                            "properties": {
                                "type": "line",
                                "x": "month",
                                "y": ["revenue"],
                                "data": {"$bind": "/charts/blk-000"},
                            },
                        },
                    ],
                },
            ],
        },
    )


def _report() -> Component:
    return Component(
        id="blk-010",
        component="Report",
        properties={
            "title": "Annual Report",
            "metadata": {"year": 2026},
            "summary": "A good year.",
            "sections": [
                {"heading": "Intro", "text": "Welcome."},
                {"heading": "Results", "text": "Numbers up."},
            ],
        },
    )


class TestInfographicComponent:
    def test_infographic_registered_in_catalog(self):
        assert get_component("Infographic").definition.requires_actions is False

    def test_infographic_schema_accepts_sectioned_payload(self):
        assert "sections" in infographic.INFOGRAPHIC_SCHEMA["properties"]

    def test_infographic_lowering_golden(self):
        one = _dump(infographic.InfographicComponent().lower(_infographic(), {}))
        two = _dump(infographic.InfographicComponent().lower(_infographic(), {}))
        assert one == two == (GOLDEN_DIR / "infographic_lowered.json").read_bytes()

    def test_infographic_lowering_preserves_section_order(self):
        tree = infographic.InfographicComponent().lower(_infographic(), {})
        sections = [c for c in tree.children if c.properties.get("role") == "section"]
        headings = [s.children[0].properties["text"] for s in sections]
        assert headings == ["Highlights", "Trend"]


class TestReportComponent:
    def test_report_registered_in_catalog(self):
        assert get_component("Report").definition.requires_actions is False

    def test_report_lowering_golden(self):
        one = _dump(report.ReportComponent().lower(_report(), {}))
        two = _dump(report.ReportComponent().lower(_report(), {}))
        assert one == two == (GOLDEN_DIR / "report_lowered.json").read_bytes()

    def test_report_lowering_no_silent_drops(self):
        tree = report.ReportComponent().lower(_report(), {})
        blob = json.dumps(tree.model_dump())
        for survivor in ("Intro", "Welcome.", "Results", "Numbers up.", "A good year."):
            assert survivor in blob


class TestNestedComponentValidation:
    def _surface_with_nested(self, nested_component: str) -> CreateSurface:
        return CreateSurface(
            surfaceId="main",
            catalogId="https://parrot.dev/catalogs/v1",
            components=[
                Component(
                    id="blk-0",
                    component="Infographic",
                    properties={
                        "title": "T",
                        "sections": [
                            {"heading": "H", "components": [
                                {"component": nested_component, "properties": {}}
                            ]}
                        ],
                    },
                )
            ],
        )

    def test_nested_unknown_component_rejected(self):
        with pytest.raises(CatalogValidationError) as exc:
            validate_envelope(self._surface_with_nested("TotallyBogus"))
        assert "TotallyBogus" in exc.value.unknown_components

    def test_nested_requires_actions_rejected_for_llm(self):
        with pytest.raises(CatalogValidationError) as exc:
            validate_envelope(self._surface_with_nested("Form"), origin=ProducerOrigin.LLM)
        assert "Form" in exc.value.action_components

    def test_nested_known_display_component_passes(self):
        validate_envelope(self._surface_with_nested("KPICard"), origin=ProducerOrigin.LLM)

    def test_lower_child_raises_structured_error_on_unknown(self):
        comp = self._surface_with_nested("NopeComponent").components[0]
        with pytest.raises(CatalogValidationError):
            infographic.InfographicComponent().lower(comp, {})


class TestCompositeDelegation:
    def test_nested_child_lowered_via_registry(self):
        tree = infographic.InfographicComponent().lower(_infographic(), {})
        blob = json.dumps(tree.model_dump())
        # KPICard lowers to a Card variant="kpi"; Chart to variant="chart".
        assert '"kpi"' in blob and '"chart"' in blob

    def test_lowering_preserves_data_bindings(self):
        tree = infographic.InfographicComponent().lower(_infographic(), {})
        blob = json.dumps(tree.model_dump())
        assert "/charts/blk-000" in blob and "$bind" in blob
