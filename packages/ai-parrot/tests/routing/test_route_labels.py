"""Unit tests for the composite route-label grammar (FEAT-755 TASK-4757)."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from parrot.models.outputs import OutputMode
from parrot.registry.routing.route_labels import (
    A2UI_LABEL_PREFIX,
    OutputShape,
    get_component_hint,
    is_inline_component,
    make_route_label,
    parse_route_label,
    set_output_shape,
)


class TestGrammar:
    """Tests for plain and composite route-label parsing."""

    def test_make_route_label(self) -> None:
        """Create a normalized composite label."""
        assert make_route_label(" KPICard ") == "a2ui:KPICard"

    @pytest.mark.parametrize("bad", ["", "   "])
    def test_make_route_label_rejects_empty(self, bad: str) -> None:
        """Reject labels without a component name."""
        with pytest.raises(ValueError):
            make_route_label(bad)

    def test_parse_plain_mode(self) -> None:
        """Parse a legacy plain output-mode key."""
        assert parse_route_label("structured_chart") == OutputShape(OutputMode.STRUCTURED_CHART, None)

    def test_parse_composite(self) -> None:
        """Parse a component-specific A2UI route label."""
        assert parse_route_label("a2ui:KPICard") == OutputShape(OutputMode.A2UI, "KPICard")

    @pytest.mark.parametrize("label", ["a2ui:", "a2ui:   ", "nope"])
    def test_parse_route_label_rejects_invalid_labels(self, label: str) -> None:
        """Reject malformed composites and unknown output modes."""
        with pytest.raises(ValueError):
            parse_route_label(label)


class TestCatalogGate:
    """Tests for the lazy display-only catalog gate."""

    def test_is_inline_component_filters_catalog_results(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Accept display-only entries and reject action, missing, and ambiguous entries."""
        from parrot.outputs.a2ui import catalog

        display_only = SimpleNamespace(definition=SimpleNamespace(requires_actions=False))
        action_bearing = SimpleNamespace(definition=SimpleNamespace(requires_actions=True))

        def fake_get_component(name: str) -> SimpleNamespace:
            if name == "KPICard":
                return display_only
            if name == "ActionCard":
                return action_bearing
            if name == "AmbiguousCard":
                raise catalog.CatalogError("ambiguous")
            raise KeyError(name)

        monkeypatch.setattr(catalog, "get_component", fake_get_component)

        assert is_inline_component("KPICard") is True
        assert is_inline_component("ActionCard") is False
        assert is_inline_component("MissingCard") is False
        assert is_inline_component("AmbiguousCard") is False


class TestHintChannel:
    """Tests for context-tolerant component-hint helpers."""

    def test_set_output_shape_tolerates_none(self) -> None:
        """Return the mode even when no request context is available."""
        shape = OutputShape(OutputMode.A2UI, "KPICard")

        assert set_output_shape(None, shape) is OutputMode.A2UI

    def test_set_get_output_shape_round_trip(self) -> None:
        """Store and retrieve a component hint on a duck-typed context."""
        context = SimpleNamespace()
        shape = OutputShape(OutputMode.A2UI, "KPICard")

        assert set_output_shape(context, shape) is OutputMode.A2UI
        assert context.a2ui_component == "KPICard"
        assert get_component_hint(context) == "KPICard"

    def test_get_component_hint_tolerates_missing_context_or_attribute(self) -> None:
        """Return no hint for absent or non-enriched contexts."""
        assert get_component_hint(None) is None
        assert get_component_hint(SimpleNamespace()) is None


def test_label_prefix_is_stable() -> None:
    """Expose the public composite-label prefix."""
    assert A2UI_LABEL_PREFIX == "a2ui:"
