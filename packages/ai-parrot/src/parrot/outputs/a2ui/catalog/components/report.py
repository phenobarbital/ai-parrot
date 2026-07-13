"""A2UI ``Report`` composite catalog component (Module 3).

Report is a narrative, section-structured document: title/metadata, an ordered list
of sections (heading + rich text + optional embedded catalog components + tables),
and an optional summary. Vocabulary is inspired by the legacy
``TemplateReportRenderer`` (dict/dataclass context flattened into a narrative
template) — inspiration only, no code reuse. Display-only (``requires_actions=False``).

Nested catalog children are lowered through the registry (delegation), keeping the
composite lowering deterministic.
"""

from __future__ import annotations

from typing import Any

from parrot.outputs.a2ui.catalog import get_component, register_component
from parrot.outputs.a2ui.catalog.base import BasicNode, BasicTree, CatalogValidationError
from parrot.outputs.a2ui.models import Component

REPORT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "metadata": {"type": "object"},
        "summary": {"type": "string"},
        "sections": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "heading": {"type": "string"},
                    "text": {"type": "string"},
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
                },
                "required": ["heading"],
            },
        },
    },
    "required": ["title", "sections"],
}

REPORT_INSTRUCTIONS = (
    "Use Report for a narrative, section-structured document. Provide `title`, "
    "optional `metadata`/`summary`, and ordered `sections` (each with a `heading`, "
    "`text`, and optionally embedded `components` such as DataTable/Chart). Sections "
    "render in the order given. Display-only."
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


@register_component("Report")
class ReportComponent:
    """The ``Report`` composite catalog component (display-only)."""

    SCHEMA = REPORT_SCHEMA
    INSTRUCTIONS = REPORT_INSTRUCTIONS

    def lower(self, component: Component, data_model: dict[str, Any]) -> BasicTree:
        """Lower a Report to a Basic Catalog tree (pure, deterministic)."""
        props = component.properties
        children: list[BasicNode] = [
            BasicNode(
                component="Text",
                properties={"role": "title", "text": props.get("title", "")},
            )
        ]

        for si, section in enumerate(props.get("sections") or []):
            section_children: list[BasicNode] = [
                BasicNode(
                    component="Text",
                    properties={"role": "heading", "text": section.get("heading", "")},
                )
            ]
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

        if props.get("summary") is not None:
            children.append(
                BasicNode(
                    component="Text",
                    properties={"role": "summary", "text": props["summary"]},
                )
            )

        return BasicNode(
            component="Card",
            properties={"variant": "report", "componentId": component.id},
            children=children,
        )
