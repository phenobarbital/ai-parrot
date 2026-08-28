"""A2UI ``Infographic`` composite catalog component (Module 5, FEAT-470 TASK-2539).

Infographic is one of Parrot's "exceeds-the-spec" semantic citizens: a header plus
an ordered list of sections, each hosting nested catalog components (KPICard rows,
Chart, Text/Image blocks). Vocabulary is inspired by the legacy
``InfographicHTMLRenderer`` (header / stat blocks / chart slots / themed sections) —
inspiration only, no code reuse. Display-only (``requires_actions=False``).

Composite lowering delegates nested catalog children to their own registered
``lower()`` via the catalog registry, keeping the whole composite deterministic as
long as every child lowering is pure. Multiple sections lower to ``Tabs`` (one tab
per section); a single section lowers to a plain ``Column``.
"""

from __future__ import annotations

from typing import Any

# Nested composite children may now name an official Basic Catalog primitive
# (Divider/List/CheckBox/Image/Tabs, TASK-2541's adapter remap) — ensure the
# 18 primitives are registered before `_lower_child` looks any of them up,
# rather than relying on some earlier `validate_envelope` call having
# already triggered `catalog.basic`'s lazy registration side effect.
from parrot.outputs.a2ui.catalog import basic as _ensure_basic_registered  # noqa: F401
from parrot.outputs.a2ui.catalog import get_component, register_component
from parrot.outputs.a2ui.catalog.base import (
    BasicNode,
    BasicTree,
    CatalogValidationError,
    TabSpec,
)
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
    "components (KPICard, Chart, InfoCard, ...). Sections render in the order given "
    "(as Tabs when there is more than one). Display-only."
)


def _lower_child(
    descriptor: dict[str, Any], data_model: dict[str, Any], child_id: str
) -> BasicNode:
    """Lower a nested catalog child through its registered ``lower()`` (pure).

    A ``descriptor`` naming an official Basic Catalog primitive
    (``is_primitive=True``, e.g. ``Divider``/``List``/``CheckBox``/``Image``,
    TASK-2541's adapter remap) needs no further lowering — it's already a
    Basic Catalog node; this just re-anchors its id and passes its top-level
    props through. ``Tabs`` is special-cased further: its ``tabs`` prop
    entries are ``{"title", "child": <nested descriptor>}`` at the adapter
    layer (a descriptor can't carry a real component id yet), so each
    ``child`` is itself lowered here before building the ``TabSpec``.
    """
    name = descriptor["component"]
    try:
        entry = get_component(name)
    except KeyError as exc:
        raise CatalogValidationError(
            f"Unknown nested component {name!r} in composite",
            unknown_components=[name],
        ) from exc

    props = dict(descriptor.get("properties") or {})

    if entry.definition.is_primitive:
        if name == "Tabs" and "tabs" in props:
            tab_specs = [
                TabSpec(
                    title=tab.get("title"),
                    child=_lower_child(tab["child"], data_model, f"{child_id}-tab{i}"),
                )
                for i, tab in enumerate(props.pop("tabs"))
            ]
            return BasicNode(id=child_id, component=name, tabs=tab_specs, **props)
        children_prop = props.get("children")
        if isinstance(children_prop, list) and children_prop and isinstance(children_prop[0], dict):
            props["children"] = [
                _lower_child(nested, data_model, f"{child_id}-c{i}")
                for i, nested in enumerate(props.pop("children"))
            ]
        if isinstance(props.get("child"), dict):
            props["child"] = _lower_child(props.pop("child"), data_model, f"{child_id}-child")
        return BasicNode(id=child_id, component=name, **props)

    child = Component(id=child_id, component=name, **props)
    return entry.component_cls().lower(child, data_model)


def _lower_section(
    section: dict[str, Any], data_model: dict[str, Any], section_id: str
) -> BasicNode:
    """Lower one section (heading + text + nested components) to a Column."""
    section_children: list[BasicNode] = []
    if section.get("heading") is not None:
        section_children.append(
            BasicNode(
                component="Text",
                text=section["heading"],
                metadata={"extensions": {"parrot_role": "heading"}},
            )
        )
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


@register_component("Infographic", allowed_parents=["root", "Column"])
class InfographicComponent:
    """The ``Infographic`` composite catalog component (display-only)."""

    SCHEMA = INFOGRAPHIC_SCHEMA
    INSTRUCTIONS = INFOGRAPHIC_INSTRUCTIONS

    def lower(self, component: Component, data_model: dict[str, Any]) -> BasicTree:
        """Lower an Infographic to a Basic Catalog ``Card`` tree."""
        props = component.model_extra or {}
        top_children: list[BasicNode] = [
            BasicNode(
                component="Text",
                text=props.get("title", ""),
                metadata={"extensions": {"parrot_role": "title"}},
            )
        ]
        if props.get("subtitle") is not None:
            top_children.append(
                BasicNode(
                    component="Text",
                    text=props["subtitle"],
                    metadata={"extensions": {"parrot_role": "subtitle"}},
                )
            )

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

        return BasicNode(
            id=component.id,
            component="Card",
            child=BasicNode(component="Column", children=top_children),
            metadata={"extensions": {"parrot_variant": "infographic"}},
        )
