"""Golden + composition tests for Infographic/Report (TASK-1726)."""

import json
from pathlib import Path

from parrot.outputs.a2ui.catalog import get_component
from parrot.outputs.a2ui.catalog.components import infographic, report

# Ensure nested children (KPICard/Chart/DataTable) are registered for delegation.
from parrot.outputs.a2ui.catalog import components as _all_components  # noqa: F401
from parrot.outputs.a2ui.models import Component

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
