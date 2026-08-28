"""A2UI ``Report`` composite catalog component (Module 5, FEAT-470 TASK-2539).

Report is a narrative, section-structured document: title/metadata, an ordered list
of sections (heading + rich text + optional embedded catalog components + tables),
and an optional summary. Vocabulary is inspired by the legacy
``TemplateReportRenderer`` (dict/dataclass context flattened into a narrative
template) — inspiration only, no code reuse. Display-only (``requires_actions=False``).

Nested catalog children are lowered through the registry (delegation), keeping the
composite lowering deterministic. Multiple sections lower to ``Tabs`` (one tab per
section); a single section lowers to a plain ``Column``.
"""

from __future__ import annotations

from typing import Any

from parrot.outputs.a2ui.catalog import get_component, register_component
from parrot.outputs.a2ui.catalog.base import (
    BasicNode,
    BasicTree,
    CatalogValidationError,
    TabSpec,
)
from parrot.outputs.a2ui.models import Component

REPORT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "reportMetadata": {
            "type": "object",
            "description": (
                "Arbitrary report metadata (e.g. year, author). Named "
                "`reportMetadata` (not `metadata`) to avoid colliding with "
                "the wire's own reserved `metadata.extensions` field."
            ),
        },
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
    "render in the order given (as Tabs when there is more than one). Display-only."
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
    child = Component(id=child_id, component=name, **(descriptor.get("properties") or {}))
    return entry.component_cls().lower(child, data_model)


def _lower_section(
    section: dict[str, Any], data_model: dict[str, Any], section_id: str
) -> BasicNode:
    """Lower one section (heading + text + nested components) to a Column."""
    section_children: list[BasicNode] = [
        BasicNode(
            component="Text",
            text=section.get("heading", ""),
            metadata={"extensions": {"parrot_role": "heading"}},
        )
    ]
    if section.get("text") is not None:
        section_children.append(
            BasicNode(
                component="Text",
                text=section["text"],
                metadata={"extensions": {"parrot_role": "body"}},
            )
        )
    for ci, descriptor in enumerate(section.get("components") or []):
        section_children.append(_lower_child(descriptor, data_model, f"{section_id}-c{ci}"))
    return BasicNode(component="Column", children=section_children)


@register_component("Report", allowed_parents=["root", "Column"])
class ReportComponent:
    """The ``Report`` composite catalog component (display-only)."""

    SCHEMA = REPORT_SCHEMA
    INSTRUCTIONS = REPORT_INSTRUCTIONS

    def lower(self, component: Component, data_model: dict[str, Any]) -> BasicTree:
        """Lower a Report to a Basic Catalog ``Card`` tree."""
        props = component.model_extra or {}
        top_children: list[BasicNode] = [
            BasicNode(
                component="Text",
                text=props.get("title", ""),
                metadata={"extensions": {"parrot_role": "title"}},
            )
        ]

        sections = props.get("sections") or []
        if len(sections) > 1:
            tab_specs = [
                TabSpec(
                    title=section.get("heading") or f"Section {si + 1}",
                    child=_lower_section(section, data_model, f"{component.id}-s{si}"),
                )
                for si, section in enumerate(sections)
            ]
            top_children.append(BasicNode(component="Tabs", tabs=tab_specs))
        elif sections:
            top_children.append(_lower_section(sections[0], data_model, f"{component.id}-s0"))

        if props.get("summary") is not None:
            top_children.append(
                BasicNode(
                    component="Text",
                    text=props["summary"],
                    metadata={"extensions": {"parrot_role": "summary"}},
                )
            )

        return BasicNode(
            id=component.id,
            component="Card",
            child=BasicNode(component="Column", children=top_children),
            metadata={"extensions": {"parrot_variant": "report"}},
        )
