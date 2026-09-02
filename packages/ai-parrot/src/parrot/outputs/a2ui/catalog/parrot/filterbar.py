"""A2UI ``FilterBar`` catalog component (Module 5, FEAT-493 TASK-2715 — net-new).

The ONE net-new catalog vocabulary this feature adds — "a bar of filters
over this surface's data model". Nothing in the 8 pre-existing Parrot
composites expresses this. Display-only (``requires_actions=False``): a
``FilterBar`` declares available filters and each one's options; it carries
no client-side state of its own in v1 (TASK-2716 adds the interactive
multiselect behaviour on top of this vocabulary, on JS-capable surfaces
only — JS-less surfaces degrade to a static summary, see
``a2ui_renderers/ssr_html.py``).

Each declared filter lowers to a Basic Catalog ``ChoicePicker`` primitive,
tagged ``parrot_role: "filter"`` + ``parrot_filter_column`` (the data-model
column it applies to) so renderers can recognise a filter without needing
to know this composite's own schema. A filter with exactly ONE declared
option is lowered with that option pre-selected (``value``) — an
unambiguous single choice; a filter with zero or multiple options starts
unconstrained (``value: []``, meaning "all").
"""

from __future__ import annotations

from typing import Any

from parrot.outputs.a2ui.catalog import register_component
from parrot.outputs.a2ui.catalog.base import BasicNode, BasicTree
from parrot.outputs.a2ui.models import Component

FILTERBAR_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "filters": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "column": {
                        "type": "string",
                        "description": "The data-model column this filter applies to.",
                    },
                    "label": {"type": "string"},
                    "options": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "label": {"type": "string"},
                                "value": {"type": "string"},
                            },
                            "required": ["label", "value"],
                        },
                    },
                    "multiple": {"type": "boolean"},
                },
                "required": ["column", "label", "options"],
            },
        },
    },
    "required": ["filters"],
}

FILTERBAR_INSTRUCTIONS = (
    "Use FilterBar to declare a bar of filters over this surface's data model. "
    "Provide `filters`: a list of `{column, label, options, multiple?}` — `column` "
    "is the data-model column the filter applies to, `options` is the list of "
    "`{label, value}` choices. Optional `title`. Display-only."
)


def _lower_filter(*, column: str, label: str, options: list[dict[str, Any]], multiple: bool, node_id: str) -> BasicNode:
    """Lower one declared filter to a ``ChoicePicker`` primitive.

    Args:
        column: The data-model column this filter applies to.
        label: Human-readable filter label.
        options: The filter's declared ``{"label", "value"}`` choices.
        multiple: Whether more than one option may be selected at once.
        node_id: Deterministic id for this ``ChoicePicker`` node — derived
            from the parent component's own id, never minted with ``uuid``
            (the golden test lowers twice and compares byte-for-byte).

    Returns:
        A ``ChoicePicker`` :class:`BasicNode` carrying
        ``parrot_role: "filter"`` and ``parrot_filter_column: column``.
    """
    choice_options = [{"label": o.get("label", ""), "value": o.get("value", "")} for o in options]
    # Exactly one option -> unambiguous, pre-selected; zero or multiple
    # options -> unconstrained ("all") until TASK-2716's client-side
    # behaviour (or a future recipe binding) narrows it.
    value = [choice_options[0]["value"]] if len(choice_options) == 1 else []
    return BasicNode(
        id=node_id,
        component="ChoicePicker",
        label=label,
        options=choice_options,
        value=value,
        variant="multipleSelection" if multiple else "mutuallyExclusive",
        metadata={"extensions": {"parrot_role": "filter", "parrot_filter_column": column}},
    )


@register_component("FilterBar")
class FilterBarComponent:
    """The ``FilterBar`` catalog component (display-only)."""

    SCHEMA = FILTERBAR_SCHEMA
    INSTRUCTIONS = FILTERBAR_INSTRUCTIONS

    def lower(self, component: Component, data_model: dict[str, Any]) -> BasicTree:
        """Lower a FilterBar to a Basic Catalog ``Row`` of ``ChoicePicker`` filters."""
        props = component.model_extra or {}
        filters = props.get("filters") or []
        children = [
            _lower_filter(
                column=f.get("column", ""),
                label=f.get("label") or f.get("column", ""),
                options=f.get("options") or [],
                multiple=bool(f.get("multiple")),
                node_id=f"{component.id}-f{i}",
            )
            for i, f in enumerate(filters)
            if isinstance(f, dict)
        ]
        return BasicNode(
            id=component.id,
            component="Row",
            children=children,
            metadata={"extensions": {"parrot_variant": "filter-bar"}},
        )
