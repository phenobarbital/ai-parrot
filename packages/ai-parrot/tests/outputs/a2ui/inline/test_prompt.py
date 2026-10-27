"""Inline component prompt addon (FEAT-755 TASK-4763)."""
from __future__ import annotations

import pytest

from parrot.outputs.a2ui.catalog import get_component
from parrot.outputs.a2ui.inline.prompt import (
    INLINE_AUTHORING_NOTES, INLINE_COMPONENTS, build_component_prompt,
)


class TestAllowlist:
    def test_v1_components(self):
        assert INLINE_COMPONENTS == {"KPICard", "InfoCard", "Timeline", "Graph"}

    @pytest.mark.parametrize("name", sorted(INLINE_COMPONENTS))
    def test_resolves_and_display_only(self, name):
        assert get_component(name).definition.requires_actions is False

    def test_notes_only_graph(self):
        assert set(INLINE_AUTHORING_NOTES) == {"Graph"}


class TestPrompt:
    @pytest.mark.parametrize("name", sorted(INLINE_COMPONENTS))
    def test_contains_instructions_and_rules(self, name):
        out = build_component_prompt(name)
        assert f"INLINE A2UI {name} OUTPUT MODE" in out
        assert get_component(name).definition.instructions in out
        assert "RULES:" in out

    @pytest.mark.parametrize("name", sorted(INLINE_COMPONENTS))
    def test_notes_only_for_graph(self, name):
        out = build_component_prompt(name)
        note = INLINE_AUTHORING_NOTES["Graph"]
        assert (note in out) == (name == "Graph")

    def test_unregistered_raises_keyerror(self):
        with pytest.raises(KeyError):
            build_component_prompt("NoSuchComponent")

    def test_schema_is_not_serialized(self):
        """G6: the schema travels as structured_output, never as prompt text."""
        out = build_component_prompt("KPICard")
        assert '"properties"' not in out
        assert '"$ref"' not in out
