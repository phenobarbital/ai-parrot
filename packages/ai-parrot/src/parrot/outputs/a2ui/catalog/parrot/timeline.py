"""A2UI ``Timeline`` catalog component (Module 5, FEAT-470 TASK-2539 — v1.0 lowering).

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
        """Lower a Timeline to a Basic Catalog ``Column`` tree (title + event rows)."""
        props = component.model_extra or {}
        children: list[BasicNode] = []

        title = props.get("title")
        if title is not None:
            children.append(
                BasicNode(
                    component="Text", text=title, metadata={"extensions": {"parrot_role": "title"}}
                )
            )

        for event in props.get("events") or []:
            row_children: list[BasicNode] = []
            if event.get("timestamp") is not None:
                row_children.append(
                    BasicNode(
                        component="Text",
                        text=event["timestamp"],
                        metadata={"extensions": {"parrot_role": "timestamp"}},
                    )
                )
            row_children.append(
                BasicNode(
                    component="Text",
                    text=event.get("title", ""),
                    metadata={"extensions": {"parrot_role": "event-title"}},
                )
            )
            if event.get("description") is not None:
                row_children.append(
                    BasicNode(
                        component="Text",
                        text=event["description"],
                        metadata={"extensions": {"parrot_role": "event-description"}},
                    )
                )
            children.append(
                BasicNode(
                    component="Row",
                    children=row_children,
                    metadata={"extensions": {"parrot_role": "event"}},
                )
            )

        return BasicNode(
            id=component.id,
            component="Column",
            children=children,
            metadata={"extensions": {"parrot_variant": "timeline"}},
        )
