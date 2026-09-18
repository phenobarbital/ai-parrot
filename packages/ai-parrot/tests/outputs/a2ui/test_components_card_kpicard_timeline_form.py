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

    def test_kpicard_schema_accepts_icon_color_comparison_period(self):
        """FEAT-527."""
        props = kpicard.KPICARD_SCHEMA["properties"]
        assert {"icon", "color", "comparisonPeriod"} <= set(props)

    def test_kpicard_lower_emits_icon_color_comparison_period_as_extensions(self):
        """FEAT-527: presentation-only, ride on the Card's extensions — never
        a new visible Text node."""
        comp = Component(
            id="blk-003",
            component="KPICard",
            label="Revenue",
            value=1200,
            icon="💰",
            color="#0a0",
            comparisonPeriod="vs Q2",
        )
        tree = kpicard.KPICardComponent().lower(comp, {})
        assert tree.component == "Card"
        extensions = tree.metadata.extensions.root
        assert extensions["parrot_icon"] == "💰"
        assert extensions["parrot_color"] == "#0a0"
        assert extensions["parrot_comparison_period"] == "vs Q2"
        # Never a new visible Text node for these.
        text_roles = {n.metadata.extensions.root.get("parrot_role") for n in tree.child.children if n.metadata}
        assert "icon" not in text_roles and "color" not in text_roles

    def test_kpicard_lower_omits_extensions_when_absent(self):
        tree = kpicard.KPICardComponent().lower(_kpicard(), {})
        extensions = tree.metadata.extensions.root
        assert "parrot_icon" not in extensions
        assert "parrot_color" not in extensions
        assert "parrot_comparison_period" not in extensions

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


class TestKPICardSentiment:
    """The delta's colour. The arrow reports the DIRECTION the number moved;
    `parrot_sentiment` is the separate question of whether that is good news,
    and the two are opposites for a metric where up is worse.
    """

    @staticmethod
    def _sentiment_of(tree) -> str | None:
        """The delta node's `parrot_sentiment`, read off the serialised tree.

        Serialised rather than walked as models: the node types differ by
        level (`child` vs `children`, `ComponentMetadata` vs `Extensions`),
        and the wire shape is what a renderer actually receives anyway.
        """

        def walk(node):
            if isinstance(node, list):
                for each in node:
                    found = walk(each)
                    if found is not None:
                        return found
                return None
            if not isinstance(node, dict):
                return None
            extensions = (node.get("metadata") or {}).get("extensions") or {}
            if extensions.get("parrot_role") == "delta":
                return extensions.get("parrot_sentiment")
            for key in ("child", "children"):
                found = walk(node.get(key))
                if found is not None:
                    return found
            return None

        return walk(tree.model_dump(mode="json"))

    def _lowered(self, **props):
        component = Component(
            id="blk-001", component="KPICard", label="Metric", value=10, delta=5, **props
        )
        return kpicard.KPICardComponent().lower(component, {})

    def test_a_rise_is_good_news_by_default(self):
        assert self._sentiment_of(self._lowered(trend="up")) == "good"

    def test_a_rise_in_a_metric_where_up_is_worse_is_bad_news(self):
        # Missed visits, defects, cost: the arrow still points up.
        assert self._sentiment_of(self._lowered(trend="up", higherIsBetter=False)) == "bad"
        assert self._sentiment_of(self._lowered(trend="down", higherIsBetter=False)) == "good"

    def test_a_metric_with_no_good_direction_is_not_judged(self):
        # `higherIsBetter=None` is the author saying the question has no
        # answer -- hours worked is an input, not an outcome, and fewer of
        # them is efficiency or under-coverage depending on what was
        # achieved. Neither colour would be true.
        assert self._sentiment_of(self._lowered(trend="down", higherIsBetter=None)) == "neutral"
        assert self._sentiment_of(self._lowered(trend="up", higherIsBetter=None)) == "neutral"

    def test_omitted_and_null_are_not_the_same_thing(self):
        # The distinction the `_UNDECLARED` sentinel exists for: `.get()`
        # alone collapses them, and a metric that asked not to be judged
        # would silently be painted as though rising were good.
        assert self._sentiment_of(self._lowered(trend="down")) == "bad"
        assert self._sentiment_of(self._lowered(trend="down", higherIsBetter=None)) == "neutral"
