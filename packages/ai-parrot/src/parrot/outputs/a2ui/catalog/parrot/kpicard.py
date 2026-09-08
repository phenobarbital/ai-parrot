"""A2UI ``KPICard`` catalog component (Module 5, FEAT-470 TASK-2539 — v1.0 lowering).

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
        "icon": {"type": "string", "description": "Optional icon glyph/name (FEAT-527)."},
        "color": {"type": "string", "description": "Optional accent CSS colour (FEAT-527)."},
        "comparisonPeriod": {
            "type": "string",
            "description": "Optional label for the baseline period the delta compares against (FEAT-527).",
        },
    },
    "required": ["label", "value"],
}

KPICARD_INSTRUCTIONS = (
    "Use KPICard to highlight a single headline metric. Provide `label` and `value`; "
    "optionally `unit`, `delta`, `trend` (up/down/flat), `icon`, `color`, and "
    "`comparisonPeriod` (e.g. 'vs Q2'). Display-only."
)


def _as_text(value: Any) -> Any:
    """Coerce a scalar KPI value/delta to the Basic Catalog ``Text.text`` shape.

    ``value``/``delta`` are documented as "number, string, or binding"
    (``KPICARD_SCHEMA``) — but the Basic Catalog ``Text`` primitive's own
    ``text`` field is ``DynamicString`` (string | ``{"path"}`` | ``{"call"}``),
    which rejects a bare number (TASK-2548 conformance sweep caught this: a
    numeric ``value`` like ``42`` failed ``agent_to_renderer.json`` validation
    outright). A binding/call dict, or ``None``, passes through unchanged;
    any other scalar is stringified.
    """
    if value is None or isinstance(value, dict):
        return value
    return str(value)


@register_component("KPICard")
class KPICardComponent:
    """The ``KPICard`` catalog component (display-only)."""

    SCHEMA = KPICARD_SCHEMA
    INSTRUCTIONS = KPICARD_INSTRUCTIONS

    def lower(self, component: Component, data_model: dict[str, Any]) -> BasicTree:
        """Lower a KPICard to a Basic Catalog ``Card{child: Column}`` tree."""
        props = component.model_extra or {}
        children: list[BasicNode] = [
            BasicNode(
                component="Text",
                text=props.get("label", ""),
                metadata={"extensions": {"parrot_role": "label"}},
            ),
            BasicNode(
                component="Text",
                text=_as_text(props.get("value")),
                metadata={"extensions": {"parrot_role": "value", "parrot_unit": props.get("unit")}},
            ),
        ]
        delta, trend = props.get("delta"), props.get("trend")
        if delta is not None or trend is not None:
            # Text.text is REQUIRED on the Basic Catalog primitive (unlike
            # this component's own optional `delta`) — fall back to `trend`
            # (itself meaningful text: "up"/"down"/"flat") and finally an
            # empty string, never an absent/None text (TASK-2548 conformance
            # sweep: a text-less Text node fails agent_to_renderer.json).
            children.append(
                BasicNode(
                    component="Text",
                    text=_as_text(delta) if delta is not None else str(trend or ""),
                    metadata={
                        "extensions": {
                            "parrot_role": "delta",
                            "parrot_trend": trend,
                        }
                    },
                )
            )
        # FEAT-527: icon/color/comparisonPeriod are presentation-only metadata
        # — they ride on the existing Card's extensions, never as new visible
        # Text nodes (renderer-owned presentation, same policy as parrot_variant).
        card_extensions: dict[str, Any] = {"parrot_variant": "kpi"}
        if props.get("icon") is not None:
            card_extensions["parrot_icon"] = props["icon"]
        if props.get("color") is not None:
            card_extensions["parrot_color"] = props["color"]
        if props.get("comparisonPeriod") is not None:
            card_extensions["parrot_comparison_period"] = props["comparisonPeriod"]

        return BasicNode(
            id=component.id,
            component="Card",
            child=BasicNode(component="Column", children=children),
            metadata={"extensions": card_extensions},
        )
