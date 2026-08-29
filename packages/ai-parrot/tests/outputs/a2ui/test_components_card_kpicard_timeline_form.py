"""Golden + contract tests for InfoCard/KPICard/Timeline (FEAT-470 TASK-2539, v1.0).

``Form`` is intentionally NOT covered here anymore — it is retired as a
registered component (spec G6); see TASK-2540's ``build_form()`` tests.
"""

import json
from pathlib import Path

import pytest
from parrot.outputs.a2ui.catalog import get_component, validate_envelope
from parrot.outputs.a2ui.catalog.base import to_components
from parrot.outputs.a2ui.catalog.parrot import infocard, kpicard, timeline
from parrot.outputs.a2ui.models import Component, CreateSurface

GOLDEN_DIR = Path(__file__).parent / "golden"


def _dump(tree) -> bytes:
    return json.dumps(tree.model_dump(mode="json", exclude_none=True), sort_keys=True, indent=2).encode() + b"\n"


def _validates(tree) -> None:
    flat = to_components(tree)
    root = Component(id="root", component="Column", children=[c.id for c in flat])
    surface = CreateSurface(surfaceId="s", catalogId="https://parrot.dev/catalogs/v1", components=[root, *flat])
    validate_envelope(surface)


def _infocard() -> Component:
    return Component(
        id="blk-000",
        component="InfoCard",
        title="Summary",
        subtitle="Q1",
        body="All good.",
        image="https://example.com/x.png",
        footer="footer",
    )


def _kpicard() -> Component:
    return Component(
        id="blk-001",
        component="KPICard",
        label="Revenue",
        value=1200,
        unit="USD",
        delta=5,
        trend="up",
    )


def _timeline() -> Component:
    return Component(
        id="blk-002",
        component="Timeline",
        title="History",
        events=[
            {"timestamp": "2026-01", "title": "Kickoff", "description": "start"},
            {"timestamp": "2026-02", "title": "Milestone"},
        ],
    )


class TestInfoCardComponent:
    def test_infocard_registered_card_resolves_basic(self):
        assert get_component("InfoCard").definition.requires_actions is False
        assert get_component("InfoCard").definition.catalog_id == "https://parrot.dev/catalogs/v1"
        # "Card" itself resolves to the OFFICIAL Basic Catalog primitive, not parrot.
        from parrot.outputs.a2ui.catalog.basic import BASIC_CATALOG_ID

        assert get_component("Card").definition.catalog_id == BASIC_CATALOG_ID

    def test_infocard_lowering_golden(self):
        one = _dump(infocard.InfoCardComponent().lower(_infocard(), {}))
        two = _dump(infocard.InfoCardComponent().lower(_infocard(), {}))
        assert one == two == (GOLDEN_DIR / "infocard_lowered.json").read_bytes()

    def test_infocard_emits_v1_primitives(self):
        tree = infocard.InfoCardComponent().lower(_infocard(), {})
        assert tree.component == "Card"
        _validates(tree)


class TestKPICardComponent:
    def test_kpicard_registered_in_catalog(self):
        assert get_component("KPICard").definition.requires_actions is False

    def test_kpicard_lowering_golden(self):
        one = _dump(kpicard.KPICardComponent().lower(_kpicard(), {}))
        two = _dump(kpicard.KPICardComponent().lower(_kpicard(), {}))
        assert one == two == (GOLDEN_DIR / "kpicard_lowered.json").read_bytes()

    def test_kpicard_emits_v1_primitives(self):
        _validates(kpicard.KPICardComponent().lower(_kpicard(), {}))


class TestTimelineComponent:
    def test_timeline_registered_in_catalog(self):
        assert get_component("Timeline").definition.requires_actions is False

    def test_timeline_lowering_golden(self):
        one = _dump(timeline.TimelineComponent().lower(_timeline(), {}))
        two = _dump(timeline.TimelineComponent().lower(_timeline(), {}))
        assert one == two == (GOLDEN_DIR / "timeline_lowered.json").read_bytes()

    def test_timeline_preserves_event_order(self):
        tree = timeline.TimelineComponent().lower(_timeline(), {})
        rows = [c for c in tree.children if c.metadata.extensions.root.get("parrot_role") == "event"]
        titles = [
            grandchild.model_extra["text"]
            for row in rows
            for grandchild in row.children
            if grandchild.metadata.extensions.root.get("parrot_role") == "event-title"
        ]
        assert titles == ["Kickoff", "Milestone"]

    def test_timeline_emits_v1_primitives(self):
        _validates(timeline.TimelineComponent().lower(_timeline(), {}))


class TestFormRetired:
    def test_form_not_registered(self):
        with pytest.raises(KeyError):
            get_component("Form")
