"""A2UI ``InfoCard`` catalog component (Module 5, FEAT-470 TASK-2539).

Renamed from the pre-v1.0 ``Card`` (spec G9) — the Basic Catalog already owns
the name ``Card`` (a single-child container primitive); this component's
lowering wraps its content in exactly that Basic ``Card`` primitive.
``metadata.extensions.parrot_variant = "card"`` records the parrot semantic
kind for renderers that want to style parrot cards distinctly.
"""

from __future__ import annotations

from typing import Any

from parrot.outputs.a2ui.catalog import register_component
from parrot.outputs.a2ui.catalog.base import BasicNode, BasicTree
from parrot.outputs.a2ui.models import Component

INFOCARD_SCHEMA: dict[str, Any] = {
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

INFOCARD_INSTRUCTIONS = (
    "Use InfoCard to group a titled block of content. Provide `title` and any of "
    "`subtitle`, `body`, `image`, `badge`, `footer`. Display-only."
)


@register_component("InfoCard")
class InfoCardComponent:
    """The ``InfoCard`` catalog component (display-only)."""

    SCHEMA = INFOCARD_SCHEMA
    INSTRUCTIONS = INFOCARD_INSTRUCTIONS

    def lower(self, component: Component, data_model: dict[str, Any]) -> BasicTree:
        """Lower an InfoCard to a Basic Catalog ``Card{child: Column}`` tree."""
        props = component.model_extra or {}
        children: list[BasicNode] = []
        if props.get("image") is not None:
            children.append(BasicNode(component="Image", url=props["image"]))
        for role in ("title", "subtitle", "badge", "body", "footer"):
            value = props.get(role)
            if value is not None:
                children.append(
                    BasicNode(
                        component="Text",
                        text=value,
                        metadata={"extensions": {"parrot_role": role}},
                    )
                )
        return BasicNode(
            id=component.id,
            component="Card",
            child=BasicNode(component="Column", children=children),
            metadata={"extensions": {"parrot_variant": "card"}},
        )
