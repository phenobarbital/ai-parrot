"""FilterBar catalog component tests (FEAT-493, TASK-2715) — registration,
lowering golden, and v1.0 primitive validity."""

import json
from pathlib import Path

from parrot.outputs.a2ui.catalog import get_component
from parrot.outputs.a2ui.catalog.base import to_components
from parrot.outputs.a2ui.catalog.parrot import filterbar
from parrot.outputs.a2ui.models import Component

GOLDEN_DIR = Path(__file__).parent / "golden"


def _dump(tree) -> bytes:
    return json.dumps(tree.model_dump(mode="json", exclude_none=True), sort_keys=True, indent=2).encode() + b"\n"


def _filterbar() -> Component:
    return Component(
        id="fb",
        component="FilterBar",
        filters=[
            {
                "column": "month",
                "label": "Month",
                "options": [{"label": "Aug-2026", "value": "2026-08"}],
                "multiple": True,
            },
            {"column": "pay_code", "label": "Pay Code", "options": []},
        ],
    )


class TestFilterBarComponent:
    def test_filterbar_registered_in_catalog(self):
        assert get_component("FilterBar").definition.requires_actions is False

    def test_filterbar_lowering_golden(self):
        one = _dump(filterbar.FilterBarComponent().lower(_filterbar(), {}))
        two = _dump(filterbar.FilterBarComponent().lower(_filterbar(), {}))
        assert one == two == (GOLDEN_DIR / "filterbar_lowered.json").read_bytes()

    def test_filterbar_emits_v1_primitives(self):
        tree = filterbar.FilterBarComponent().lower(_filterbar(), {})
        assert tree.component == "Row"
        assert tree.metadata.extensions.root["parrot_variant"] == "filter-bar"
        to_components(tree)

    def test_children_carry_filter_column(self):
        tree = filterbar.FilterBarComponent().lower(_filterbar(), {})
        cols = [c.metadata.extensions.root["parrot_filter_column"] for c in tree.children]
        assert cols == ["month", "pay_code"]

    def test_children_carry_filter_role(self):
        tree = filterbar.FilterBarComponent().lower(_filterbar(), {})
        assert all(c.metadata.extensions.root["parrot_role"] == "filter" for c in tree.children)

    def test_single_option_filter_is_preselected(self):
        tree = filterbar.FilterBarComponent().lower(_filterbar(), {})
        assert tree.children[0].value == ["2026-08"]

    def test_zero_option_filter_is_unconstrained(self):
        tree = filterbar.FilterBarComponent().lower(_filterbar(), {})
        assert tree.children[1].value == []

    def test_children_are_choicepicker(self):
        tree = filterbar.FilterBarComponent().lower(_filterbar(), {})
        assert all(c.component == "ChoicePicker" for c in tree.children)

    def test_lowering_is_deterministic_across_instances(self):
        """No uuid/timestamp minting — same input, same ids, every time."""
        tree = filterbar.FilterBarComponent().lower(_filterbar(), {})
        assert tree.children[0].id == "fb-f0"
        assert tree.children[1].id == "fb-f1"
