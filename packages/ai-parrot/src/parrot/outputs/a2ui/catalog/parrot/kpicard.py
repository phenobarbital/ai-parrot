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
        "higherIsBetter": {
            "type": ["boolean", "null"],
            "description": (
                "Whether a RISING value is good news. Three answers, not two. "
                "Omitted: yes (the default). False: a metric where up is worse "
                "(missed visits, defects, cost) -- the arrow still points the way "
                "the number moved, but the colour reports what that means. NULL: "
                "the question has no answer, so nothing is judged and the delta "
                "renders neutral. Hours worked is the case: an input, not an "
                "outcome, whose meaning depends on what was achieved with it -- "
                "fewer hours is efficiency or under-coverage, and the card cannot "
                "tell. Note that null and omitted differ ON PURPOSE."
            ),
        },
        "format": {
            "type": "string",
            "enum": ["percent", "currency", "number"],
            "description": (
                "Optional display hint for `value`, mirroring `TableColumn.format`. "
                "A ratio sent as 0.683 renders as '68.3%' only when this says so — "
                "renderers never guess a number's meaning from its label."
            ),
        },
    },
    "required": ["label", "value"],
}

KPICARD_INSTRUCTIONS = (
    "Use KPICard to highlight a single headline metric. Provide `label` and `value`; "
    "optionally `unit`, `delta`, `trend` (up/down/flat), `icon`, `color`, "
    "`comparisonPeriod` (e.g. 'vs Q2'), `higherIsBetter` (false when up is bad "
    "news, e.g. missed visits; null when the metric has no good direction at "
    "all, e.g. hours worked, and must not be judged) "
    "and `format` (percent/currency/number — "
    "send a ratio as 0.683 with format='percent', never as the string '68.3%'). "
    "Display-only."
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


#: `higherIsBetter` absent. Distinct from an explicit null, which is the
#: author saying the metric has no good direction — `.get()` alone cannot
#: tell those apart, and collapsing them would silently judge a metric that
#: asked not to be judged.
_UNDECLARED = object()


def _sentiment(trend: Any, higher_is_better: Any) -> str | None:
    """Is this movement good news? ``good`` | ``bad`` | ``neutral``.

    Direction and sentiment are the same thing for most metrics and exact
    opposites for the ones where up is worse — missed visits, defects, cost.
    Without this a renderer has to assume the first, and paints a month with
    more missed events green.

    Some metrics have no good direction at all. An explicit ``None`` says so
    and the movement renders neutral: hours worked is an input, not an
    outcome, and whether fewer of them is efficiency or under-coverage is a
    question this card cannot answer. ``_UNDECLARED`` (the property absent)
    keeps the old default — rising is good.

    Returns ``None`` when there is no direction to judge at all, so a card
    that says nothing keeps saying nothing.
    """
    if trend not in ("up", "down", "flat"):
        return None
    if trend == "flat":
        return "neutral"
    if higher_is_better is None:
        return "neutral"
    rising_is_good = higher_is_better is not False
    return "good" if (trend == "up") == rising_is_good else "bad"


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
                metadata={
                    "extensions": {
                        "parrot_role": "value",
                        "parrot_unit": props.get("unit"),
                        # The raw value stays the Text's `text` (a renderer
                        # that ignores this extension is unchanged); the hint
                        # rides beside it so every renderer formats the same
                        # number the same way.
                        "parrot_value_format": props.get("format"),
                    }
                },
            ),
        ]
        delta, trend = props.get("delta"), props.get("trend")
        if delta is not None or trend is not None:
            # Text.text is REQUIRED on the Basic Catalog primitive (unlike
            # this component's own optional `delta`) — fall back to `trend`
            # (itself meaningful text: "up"/"down"/"flat") and finally an
            # empty string, never an absent/None text (TASK-2548 conformance
            # sweep: a text-less Text node fails agent_to_renderer.json).
            # `parrot_trend` is the DIRECTION the value moved; `parrot_sentiment`
            # is whether that is good news. They are the same thing for most
            # metrics and opposites for the ones where up is worse, and a
            # renderer that only had the direction had to assume the first.
            children.append(
                BasicNode(
                    component="Text",
                    text=_as_text(delta) if delta is not None else str(trend or ""),
                    metadata={
                        "extensions": {
                            "parrot_role": "delta",
                            "parrot_trend": trend,
                            "parrot_sentiment": _sentiment(
                                trend, props.get("higherIsBetter", _UNDECLARED)
                            ),
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
