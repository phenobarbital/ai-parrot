"""A2UI ``KPICard`` catalog component (Module 3).

Net-new vocabulary (no prior KPICard model exists): ``label``, ``value``, ``unit``,
``delta``, ``trend``. Display-only (``requires_actions=False``).
"""

from __future__ import annotations

from typing import Any

from parrot.outputs.a2ui.catalog import register_component
from parrot.outputs.a2ui.catalog.base import BasicNode, BasicTree
from parrot.outputs.a2ui.models import Component

KPICARD_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "label": {"type": "string"},
        "value": {"description": "Primary metric value (number, string, or binding)."},
        "unit": {"type": "string"},
        "delta": {"description": "Change vs. a baseline (number, string, or binding)."},
        "trend": {"type": "string", "enum": ["up", "down", "flat"]},
    },
    "required": ["label", "value"],
}

KPICARD_INSTRUCTIONS = (
    "Use KPICard to highlight a single headline metric. Provide `label` and `value`; "
    "optionally `unit`, `delta`, and `trend` (up/down/flat). Display-only."
)


@register_component("KPICard")
class KPICardComponent:
    """The ``KPICard`` catalog component (display-only)."""

    SCHEMA = KPICARD_SCHEMA
    INSTRUCTIONS = KPICARD_INSTRUCTIONS

    def lower(self, component: Component, data_model: dict[str, Any]) -> BasicTree:
        """Lower a KPICard to a Basic Catalog tree (pure, deterministic)."""
        props = component.properties
        children: list[BasicNode] = [
            BasicNode(
                component="Text",
                properties={"role": "label", "text": props.get("label", "")},
            ),
            BasicNode(
                component="Text",
                properties={
                    "role": "value",
                    "text": props.get("value"),
                    "unit": props.get("unit"),
                },
            ),
        ]
        if props.get("delta") is not None or props.get("trend") is not None:
            children.append(
                BasicNode(
                    component="Text",
                    properties={
                        "role": "delta",
                        "text": props.get("delta"),
                        "trend": props.get("trend"),
                    },
                )
            )
        return BasicNode(
            component="Card",
            properties={"variant": "kpi", "componentId": component.id},
            children=children,
        )
