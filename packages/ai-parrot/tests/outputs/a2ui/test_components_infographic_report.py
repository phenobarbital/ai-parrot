"""Golden + composition tests for Infographic/Report (FEAT-470 TASK-2539, v1.0)."""

import json
from pathlib import Path

import pytest
from parrot.outputs.a2ui.catalog import (
    CatalogValidationError,
    get_component,
    validate_envelope,
)

# Ensure nested children (KPICard/Chart/DataTable) are registered for delegation.
from parrot.outputs.a2ui.catalog import parrot as _all_parrot_components  # noqa: F401
from parrot.outputs.a2ui.catalog.base import to_components
from parrot.outputs.a2ui.catalog.parrot import infographic, report
from parrot.outputs.a2ui.models import Component, CreateSurface

GOLDEN_DIR = Path(__file__).parent / "golden"


def _dump(tree) -> bytes:
    return json.dumps(tree.model_dump(mode="json", exclude_none=True), sort_keys=True, indent=2).encode() + b"\n"


def _infographic() -> Component:
    return Component(
        id="blk-000",
        component="Infographic",
        title="Q1 Overview",
        subtitle="Financials",
        theme="ocean",
        sections=[
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
                            "data": {"path": "/charts/blk-000"},
                        },
                    },
                ],
            },
        ],
    )


def _report() -> Component:
    return Component(
        id="blk-010",
        component="Report",
        title="Annual Report",
        reportMetadata={"year": 2026},
        summary="A good year.",
        sections=[
            {"heading": "Intro", "text": "Welcome."},
            {"heading": "Results", "text": "Numbers up."},
        ],
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

    def test_infographic_lowering_preserves_section_order_as_tabs(self):
        tree = infographic.InfographicComponent().lower(_infographic(), {})
        tabs_node = next(c for c in tree.child.children if c.component == "Tabs")
        titles = [tab.title for tab in tabs_node.tabs]
        assert titles == ["Highlights", "Trend"]

    def test_infographic_emits_v1_primitives(self):
        tree = infographic.InfographicComponent().lower(_infographic(), {})
        flat = to_components(tree)
        root = Component(id="root", component="Column", children=[c.id for c in flat])
        surface = CreateSurface(surfaceId="s", catalogId="https://parrot.dev/catalogs/v1", components=[root, *flat])
        validate_envelope(surface)

    def test_half_layout_children_grouped_in_row(self):
        """FEAT-527: two consecutive layout:"half" children lower into one Row."""
        comp = Component(
            id="root", component="Infographic", title="T",
            sections=[
                {
                    "heading": "S",
                    "components": [
                        {
                            "component": "Chart",
                            "properties": {
                                "type": "bar", "x": "m", "y": ["v"],
                                "layout": "half", "data": {"path": "/a"},
                            },
                        },
                        {
                            "component": "Chart",
                            "properties": {
                                "type": "donut", "x": "m", "y": ["v"],
                                "layout": "half", "data": {"path": "/b"},
                            },
                        },
                    ],
                }
            ],
        )
        tree = infographic.InfographicComponent().lower(comp, {"a": [], "b": []})
        # Single section → a plain Column child (no Tabs wrapper).
        section = tree.child.children[1]
        rows = [c for c in section.children if c.component == "Row"]
        assert len(rows) == 1
        assert len(rows[0].children) == 2
        assert rows[0].metadata.extensions.root["parrot_layout"] == "half"

    def test_odd_trailing_half_layout_child_gets_a_single_child_row(self):
        comp = Component(
            id="root", component="Infographic", title="T",
            sections=[
                {
                    "heading": "S",
                    "components": [
                        {
                            "component": "Chart",
                            "properties": {
                                "type": "bar", "x": "m", "y": ["v"],
                                "layout": "half", "data": {"path": "/a"},
                            },
                        },
                    ],
                }
            ],
        )
        tree = infographic.InfographicComponent().lower(comp, {"a": []})
        section = tree.child.children[1]
        rows = [c for c in section.children if c.component == "Row"]
        assert len(rows) == 1
        assert len(rows[0].children) == 1

    def test_full_layout_child_stays_a_direct_column_child(self):
        comp = Component(
            id="root", component="Infographic", title="T",
            sections=[
                {
                    "heading": "S",
                    "components": [
                        {
                            "component": "Chart",
                            "properties": {
                                "type": "bar", "x": "m", "y": ["v"],
                                "data": {"path": "/a"},
                            },
                        },
                    ],
                }
            ],
        )
        tree = infographic.InfographicComponent().lower(comp, {"a": []})
        section = tree.child.children[1]
        # Chart.lower() itself lowers to a "Card" (its own display fallback) —
        # the point here is simply that it is NOT wrapped in a Row.
        assert not any(c.component == "Row" for c in section.children)
        assert any(c.component == "Card" for c in section.children)


class TestReportComponent:
    def test_report_registered_in_catalog(self):
        assert get_component("Report").definition.requires_actions is False

    def test_report_lowering_golden(self):
        one = _dump(report.ReportComponent().lower(_report(), {}))
        two = _dump(report.ReportComponent().lower(_report(), {}))
        assert one == two == (GOLDEN_DIR / "report_lowered.json").read_bytes()

    def test_report_lowering_no_silent_drops(self):
        tree = report.ReportComponent().lower(_report(), {})
        blob = json.dumps(tree.model_dump(mode="json"))
        for survivor in ("Intro", "Welcome.", "Results", "Numbers up.", "A good year."):
            assert survivor in blob


class TestNestedComponentDelegation:
    """Nested composite children (Infographic/Report `sections[].components[]`) are
    parrot-internal authoring data — validated by delegation at LOWER time (via
    the registry), not by the generic wire-level `validate_envelope` (which only
    understands the flat top-level adjacency list, spec §2)."""

    def _infographic_with_nested(self, nested_component: str) -> Component:
        return Component(
            id="blk-0",
            component="Infographic",
            title="T",
            sections=[{"heading": "H", "components": [{"component": nested_component, "properties": {}}]}],
        )

    def test_lower_child_raises_structured_error_on_unknown(self):
        comp = self._infographic_with_nested("NopeComponent")
        with pytest.raises(CatalogValidationError) as exc:
            infographic.InfographicComponent().lower(comp, {})
        assert "NopeComponent" in exc.value.unknown_components

    def test_lower_child_succeeds_for_known_component(self):
        comp = self._infographic_with_nested("KPICard")
        tree = infographic.InfographicComponent().lower(comp, {})
        assert tree.component == "Card"


class TestCompositeDelegation:
    def test_nested_child_lowered_via_registry(self):
        tree = infographic.InfographicComponent().lower(_infographic(), {})
        blob = json.dumps(tree.model_dump(mode="json"))
        # KPICard lowers to a Card variant="kpi"; Chart to variant="chart".
        assert '"kpi"' in blob and '"chart"' in blob

    def test_lowering_preserves_data_bindings(self):
        tree = infographic.InfographicComponent().lower(_infographic(), {})
        blob = json.dumps(tree.model_dump(mode="json"))
        assert "/charts/blk-000" in blob and '"path"' in blob
