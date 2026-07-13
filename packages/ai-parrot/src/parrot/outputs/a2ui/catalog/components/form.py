"""A2UI ``Form`` catalog component (Module 3) — the one ``requires_actions=True``
component in v1 (resolved OQ-B, spec §8).

Form ships **schema + instructions** for the complete v1.0 message set, but no
renderer supports it in v1. Because TASK-1721's registry enforces the mandatory
``lower()`` contract (G4, literal), Form ships a minimal read-only degraded
lowering: a Column of field-label Texts plus a "form not available on this surface"
notice (spec §7 "Known Risks" — actions stripped + visible notice). Submission,
`action`/`actionResponse` dispatch, and rendering are FEAT-B territory.
"""

from __future__ import annotations

from typing import Any

from parrot.outputs.a2ui.catalog import register_component
from parrot.outputs.a2ui.catalog.base import BasicNode, BasicTree
from parrot.outputs.a2ui.models import Component

FORM_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "fields": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "label": {"type": "string"},
                    "input": {
                        "type": "string",
                        "enum": ["text", "number", "select", "checkbox", "date", "textarea"],
                    },
                    "required": {"type": "boolean", "default": False},
                },
                "required": ["name", "input"],
            },
        },
        "submit": {
            "type": "object",
            "description": "Submit action descriptor (dispatched in FEAT-B).",
            "properties": {
                "label": {"type": "string"},
                "action": {"type": "string"},
            },
        },
    },
    "required": ["fields", "submit"],
}

FORM_INSTRUCTIONS = (
    "Form collects user input via `fields` (name/label/input type) and a `submit` "
    "descriptor. NOTE: Form is NOT available on display-only surfaces in v1 — do not "
    "emit it from the display (LLM) producer. It is action-bearing "
    "(requires_actions=True) and degrades to a read-only notice on static surfaces."
)


@register_component("Form", requires_actions=True)
class FormComponent:
    """The ``Form`` catalog component (action-bearing; schema-only in v1)."""

    SCHEMA = FORM_SCHEMA
    INSTRUCTIONS = FORM_INSTRUCTIONS

    def lower(self, component: Component, data_model: dict[str, Any]) -> BasicTree:
        """Lower a Form to a read-only degraded Basic tree (pure, deterministic).

        Static surfaces cannot dispatch actions, so the form renders as its field
        labels plus a visible "not available" notice (spec §7).
        """
        props = component.properties
        children: list[BasicNode] = []

        title = props.get("title")
        if title is not None:
            children.append(
                BasicNode(component="Text", properties={"role": "title", "text": title})
            )

        for field in props.get("fields") or []:
            children.append(
                BasicNode(
                    component="Text",
                    properties={
                        "role": "field-label",
                        "text": field.get("label") or field.get("name", ""),
                    },
                )
            )

        children.append(
            BasicNode(
                component="Text",
                properties={
                    "role": "notice",
                    "text": "This form is not available on this surface.",
                },
            )
        )
        return BasicNode(
            component="Column",
            properties={"variant": "form", "componentId": component.id},
            children=children,
        )
