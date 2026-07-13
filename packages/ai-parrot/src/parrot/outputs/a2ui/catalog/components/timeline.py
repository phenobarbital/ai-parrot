"""A2UI ``Timeline`` catalog component (Module 3).

Net-new vocabulary: an ordered list of ``events`` each with ``timestamp``, ``title``,
``description``. Lowering keeps events in INPUT order (never re-sorted — determinism
and author intent). Display-only (``requires_actions=False``).
"""

from __future__ import annotations

from typing import Any

from parrot.outputs.a2ui.catalog import register_component
from parrot.outputs.a2ui.catalog.base import BasicNode, BasicTree
from parrot.outputs.a2ui.models import Component

TIMELINE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "events": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "timestamp": {"type": "string"},
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                },
                "required": ["title"],
            },
        },
    },
    "required": ["events"],
}

TIMELINE_INSTRUCTIONS = (
    "Use Timeline to present a chronological sequence of `events`, each with a "
    "`title` and optional `timestamp`/`description`. Events render in the order given "
    "(they are never re-sorted). Display-only."
)


@register_component("Timeline")
class TimelineComponent:
    """The ``Timeline`` catalog component (display-only)."""

    SCHEMA = TIMELINE_SCHEMA
    INSTRUCTIONS = TIMELINE_INSTRUCTIONS

    def lower(self, component: Component, data_model: dict[str, Any]) -> BasicTree:
        """Lower a Timeline to a Basic Catalog tree (pure, deterministic)."""
        props = component.properties
        children: list[BasicNode] = []

        title = props.get("title")
        if title is not None:
            children.append(
                BasicNode(component="Text", properties={"role": "title", "text": title})
            )

        for event in props.get("events") or []:
            row_children = [
                BasicNode(
                    component="Text",
                    properties={"role": "timestamp", "text": event.get("timestamp")},
                ),
                BasicNode(
                    component="Text",
                    properties={"role": "event-title", "text": event.get("title", "")},
                ),
            ]
            if event.get("description") is not None:
                row_children.append(
                    BasicNode(
                        component="Text",
                        properties={"role": "event-description", "text": event["description"]},
                    )
                )
            children.append(
                BasicNode(component="Row", properties={"role": "event"}, children=row_children)
            )

        return BasicNode(
            component="Column",
            properties={"variant": "timeline", "componentId": component.id},
            children=children,
        )
