"""Golden + contract tests for Card/KPICard/Timeline/Form (TASK-1725)."""

import json
from pathlib import Path

from parrot.outputs.a2ui.catalog import get_component
from parrot.outputs.a2ui.catalog.components import card, form, kpicard, timeline
from parrot.outputs.a2ui.models import Component

GOLDEN_DIR = Path(__file__).parent / "golden"


def _dump(tree) -> bytes:
    return json.dumps(tree.model_dump(), sort_keys=True).encode()


def _card() -> Component:
    return Component(
        id="blk-000",
        component="Card",
        properties={
            "title": "Summary",
            "subtitle": "Q1",
            "body": "All good.",
            "image": "https://example.com/x.png",
            "footer": "footer",
        },
    )


def _kpicard() -> Component:
    return Component(
        id="blk-001",
        component="KPICard",
        properties={"label": "Revenue", "value": 1200, "unit": "USD", "delta": 5, "trend": "up"},
    )


def _timeline() -> Component:
    return Component(
        id="blk-002",
        component="Timeline",
        properties={
            "title": "History",
            "events": [
                {"timestamp": "2026-01", "title": "Kickoff", "description": "start"},
                {"timestamp": "2026-02", "title": "Milestone"},
            ],
        },
    )


def _form() -> Component:
    return Component(
        id="blk-003",
        component="Form",
        properties={
            "title": "Signup",
            "fields": [
                {"name": "email", "label": "Email", "input": "text", "required": True},
                {"name": "age", "input": "number"},
            ],
            "submit": {"label": "Send", "action": "signup"},
        },
    )


class TestCardComponent:
    def test_card_registered_in_catalog(self):
        assert get_component("Card").definition.requires_actions is False

    def test_card_lowering_golden(self):
        one = _dump(card.CardComponent().lower(_card(), {}))
        two = _dump(card.CardComponent().lower(_card(), {}))
        assert one == two == (GOLDEN_DIR / "card_lowered.json").read_bytes()


class TestKPICardComponent:
    def test_kpicard_registered_in_catalog(self):
        assert get_component("KPICard").definition.requires_actions is False

    def test_kpicard_lowering_golden(self):
        one = _dump(kpicard.KPICardComponent().lower(_kpicard(), {}))
        two = _dump(kpicard.KPICardComponent().lower(_kpicard(), {}))
        assert one == two == (GOLDEN_DIR / "kpicard_lowered.json").read_bytes()


class TestTimelineComponent:
    def test_timeline_registered_in_catalog(self):
        assert get_component("Timeline").definition.requires_actions is False

    def test_timeline_lowering_golden(self):
        one = _dump(timeline.TimelineComponent().lower(_timeline(), {}))
        two = _dump(timeline.TimelineComponent().lower(_timeline(), {}))
        assert one == two == (GOLDEN_DIR / "timeline_lowered.json").read_bytes()

    def test_timeline_preserves_event_order(self):
        tree = timeline.TimelineComponent().lower(_timeline(), {})
        titles = [
            child.children[1].properties["text"]
            for child in tree.children
            if child.properties.get("role") == "event"
        ]
        assert titles == ["Kickoff", "Milestone"]


class TestFormComponent:
    def test_form_registered_with_requires_actions_true(self):
        assert get_component("Form").definition.requires_actions is True

    def test_form_schema_validates_field_payload(self):
        props = form.FORM_SCHEMA["properties"]
        assert "fields" in props and "submit" in props

    def test_form_instructions_flag_display_only_v1(self):
        text = form.FORM_INSTRUCTIONS.lower()
        assert "not available" in text and "v1" in text

    def test_form_lowering_golden(self):
        one = _dump(form.FormComponent().lower(_form(), {}))
        two = _dump(form.FormComponent().lower(_form(), {}))
        assert one == two == (GOLDEN_DIR / "form_lowered.json").read_bytes()
