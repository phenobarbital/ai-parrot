"""A2UI ``Card`` catalog component (Module 3).

Visual vocabulary (title / subtitle / body / image / badge / footer) is inspired by
the legacy ``CardRenderer.CARD_TEMPLATE`` (``ai-parrot-visualizations`` formats/card.py)
— inspiration only, no code reuse. Display-only (``requires_actions=False``).
"""

from __future__ import annotations

from typing import Any

from parrot.outputs.a2ui.catalog import register_component
from parrot.outputs.a2ui.catalog.base import BasicNode, BasicTree
from parrot.outputs.a2ui.models import Component

CARD_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "subtitle": {"type": "string"},
        "body": {"type": "string"},
        "image": {"type": "string", "description": "Image URL or data-model binding."},
        "badge": {"type": "string"},
        "footer": {"type": "string"},
    },
    "required": ["title"],
}

CARD_INSTRUCTIONS = (
    "Use Card to group a titled block of content. Provide `title` and any of "
    "`subtitle`, `body`, `image`, `badge`, `footer`. Display-only."
)


@register_component("Card")
class CardComponent:
    """The ``Card`` catalog component (display-only)."""

    SCHEMA = CARD_SCHEMA
    INSTRUCTIONS = CARD_INSTRUCTIONS

    def lower(self, component: Component, data_model: dict[str, Any]) -> BasicTree:
        """Lower a Card to a Basic Catalog tree (pure, deterministic)."""
        props = component.properties
        children: list[BasicNode] = []
        for role in ("title", "subtitle", "badge", "body", "footer"):
            value = props.get(role)
            if value is not None:
                children.append(
                    BasicNode(component="Text", properties={"role": role, "text": value})
                )
        if props.get("image") is not None:
            children.insert(
                0,
                BasicNode(component="Image", properties={"src": props["image"]}),
            )
        return BasicNode(
            component="Card",
            properties={"variant": "card", "componentId": component.id},
            children=children,
        )
