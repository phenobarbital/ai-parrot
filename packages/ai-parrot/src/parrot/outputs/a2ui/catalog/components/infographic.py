"""A2UI ``Infographic`` composite catalog component (Module 3).

Infographic is one of Parrot's "exceeds-the-spec" semantic citizens: a header plus
an ordered list of sections, each hosting nested catalog components (KPICard rows,
Chart, Text/Image blocks). Vocabulary is inspired by the legacy
``InfographicHTMLRenderer`` (header / stat blocks / chart slots / themed sections) —
inspiration only, no code reuse. Display-only (``requires_actions=False``).

Composite lowering delegates nested catalog children to their own registered
``lower()`` via the catalog registry, keeping the whole composite deterministic as
long as every child lowering is pure.
"""

from __future__ import annotations

from typing import Any

from parrot.outputs.a2ui.catalog import get_component, register_component
from parrot.outputs.a2ui.catalog.base import BasicNode, BasicTree, CatalogValidationError
from parrot.outputs.a2ui.models import Component

INFOGRAPHIC_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "subtitle": {"type": "string"},
        "theme": {"type": "string", "description": "Theme hint (e.g. palette name)."},
        "sections": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "heading": {"type": "string"},
                    "components": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "component": {"type": "string"},
                                "properties": {"type": "object"},
                            },
                            "required": ["component"],
                        },
                    },
                    "text": {"type": "string"},
                },
            },
        },
    },
    "required": ["title", "sections"],
}

INFOGRAPHIC_INSTRUCTIONS = (
    "Use Infographic for a visual, section-structured summary. Provide `title`, "
    "optional `subtitle`/`theme`, and ordered `sections`. Each section has a "
    "`heading`, optional `text`, and a `components` list nesting other catalog "
    "components (KPICard, Chart, Card, ...). Sections render in the order given. "
    "Display-only."
)


def _lower_child(
    descriptor: dict[str, Any], data_model: dict[str, Any], child_id: str
) -> BasicNode:
    """Lower a nested catalog child through its registered ``lower()`` (pure)."""
    name = descriptor["component"]
    try:
        entry = get_component(name)
    except KeyError as exc:
        raise CatalogValidationError(
            f"Unknown nested component {name!r} in composite",
            unknown_components=[name],
        ) from exc
    child = Component(
        id=child_id,
        component=name,
        properties=descriptor.get("properties", {}) or {},
    )
    return entry.component_cls().lower(child, data_model)


@register_component("Infographic")
class InfographicComponent:
    """The ``Infographic`` composite catalog component (display-only)."""

    SCHEMA = INFOGRAPHIC_SCHEMA
    INSTRUCTIONS = INFOGRAPHIC_INSTRUCTIONS

    def lower(self, component: Component, data_model: dict[str, Any]) -> BasicTree:
        """Lower an Infographic to a Basic Catalog tree (pure, deterministic)."""
        props = component.properties
        children: list[BasicNode] = [
            BasicNode(
                component="Text",
                properties={"role": "title", "text": props.get("title", "")},
            )
        ]
        if props.get("subtitle") is not None:
            children.append(
                BasicNode(
                    component="Text",
                    properties={"role": "subtitle", "text": props["subtitle"]},
                )
            )

        for si, section in enumerate(props.get("sections") or []):
            section_children: list[BasicNode] = []
            if section.get("heading") is not None:
                section_children.append(
                    BasicNode(
                        component="Text",
                        properties={"role": "heading", "text": section["heading"]},
                    )
                )
            if section.get("text") is not None:
                section_children.append(
                    BasicNode(
                        component="Text",
                        properties={"role": "body", "text": section["text"]},
                    )
                )
            for ci, descriptor in enumerate(section.get("components") or []):
                section_children.append(
                    _lower_child(descriptor, data_model, f"{component.id}-s{si}-c{ci}")
                )
            children.append(
                BasicNode(
                    component="Column",
                    properties={"role": "section", "index": si},
                    children=section_children,
                )
            )

        return BasicNode(
            component="Card",
            properties={"variant": "infographic", "componentId": component.id},
            children=children,
        )
