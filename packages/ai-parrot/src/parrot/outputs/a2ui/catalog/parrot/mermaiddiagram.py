"""A2UI ``MermaidDiagram`` catalog component (FEAT-753, Module 2).

The second opaque Parrot-catalog component after ``HtmlDocument`` — with the opposite trust posture:
Mermaid source is a declarative text DSL, so the component is LLM-authorable (NOT ``tool_only``). Safety
lives in :func:`~parrot.outputs.a2ui.graph.mermaid_source.check_mermaid_source`, run by
``validate_envelope`` for every origin. Python never draws: ``lower()`` emits a readable Basic tree whose
last Text carries the exact source under ``parrot_role: "mermaid-source"``.
"""

from __future__ import annotations

from typing import Any

from parrot.outputs.a2ui.catalog import register_component
from parrot.outputs.a2ui.catalog.base import BasicNode, BasicTree
from parrot.outputs.a2ui.graph.mermaid_source import (
    MERMAID_DIAGRAM_TYPES,
    MERMAID_SOURCE_MAX_BYTES,
    MERMAID_THEMES,
    detect_diagram_type,
)
from parrot.outputs.a2ui.models import Component

MERMAIDDIAGRAM_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "source": {
            "type": "string",
            "minLength": 1,
            "maxLength": MERMAID_SOURCE_MAX_BYTES,
            "description": "Mermaid diagram source. No %%{init}%% directives, no click/link/callback statements.",
        },
        "diagramType": {
            "type": "string",
            "enum": list(MERMAID_DIAGRAM_TYPES),
            "description": "Detected from the first statement of `source`; a mismatch fails validation.",
        },
        "title": {"type": "string"},
        "caption": {"type": "string"},
        "theme": {
            "type": "string",
            "enum": list(MERMAID_THEMES),
            "description": "Renderer hint only; the renderer may override it with the host theme.",
        },
        "accessibleDescription": {
            "type": "string",
            "description": "Screen-reader summary; first line of the lowered fallback.",
        },
    },
    "required": ["source"],
}

MERMAIDDIAGRAM_INSTRUCTIONS = (
    "MermaidDiagram shows a diagram written in Mermaid syntax: sequence, class, ER, state, flowchart, gantt, "
    "pie, user journey, mindmap, gitGraph, timeline, quadrant, requirement, C4 and the other Mermaid diagram "
    "types. Put the complete Mermaid text in `source` (one statement per line, the diagram keyword on the first "
    "line, under 32 KB). Set `diagramType` to the detected type (flowchart, sequence, class, state, er, journey, "
    "gantt, pie, quadrant, requirement, gitGraph, c4, mindmap, timeline, …) and always give "
    "`accessibleDescription` (one sentence saying what the diagram shows). Optional `title`, `caption`, and a "
    "`theme` hint (default, neutral, dark, forest, base). NEVER write `%%{init: …}%%` directives, `click`/`link`/"
    "`callback` statements, `javascript:` URLs or HTML tags — the envelope is rejected. For a workflow, state "
    "machine or dependency graph that renderers should lay out and style from typed data, prefer the viz-core "
    "`Graph` component instead; use MermaidDiagram when the diagram type has no typed component."
)


@register_component("MermaidDiagram", allowed_parents=["root", "Column"])
class MermaidDiagramComponent:
    """The ``MermaidDiagram`` Parrot-catalog component: opaque, display-only Mermaid source."""

    SCHEMA = MERMAIDDIAGRAM_SCHEMA
    INSTRUCTIONS = MERMAIDDIAGRAM_INSTRUCTIONS

    def lower(self, component: Component, data_model: dict[str, Any]) -> BasicTree:
        """Lower to ``Card{Column[description, title?, caption?, source]}`` (spec §2 "Lowered tree").

        Deterministic: identical input -> byte-identical tree. Never validates (``validate_envelope`` did).
        """
        props = component.model_extra or {}
        source = str(props.get("source") or "")
        diagram_type = props.get("diagramType") or detect_diagram_type(source)
        theme = props.get("theme")
        children: list[BasicNode] = [
            BasicNode(
                component="Text",
                text=props.get("accessibleDescription") or f"Mermaid {diagram_type} diagram",
                metadata={"extensions": {"parrot_role": "description"}},
            ),
        ]
        if props.get("title"):
            children.append(
                BasicNode(component="Text", text=props["title"], metadata={"extensions": {"parrot_role": "title"}})
            )
        if props.get("caption"):
            children.append(
                BasicNode(component="Text", text=props["caption"], metadata={"extensions": {"parrot_role": "caption"}})
            )
        source_ext: dict[str, Any] = {"parrot_role": "mermaid-source", "parrot_diagram_type": diagram_type}
        if theme:
            source_ext["parrot_mermaid_theme"] = theme
        children.append(BasicNode(component="Text", text=source, metadata={"extensions": source_ext}))
        return BasicNode(
            id=component.id,
            component="Card",
            child=BasicNode(component="Column", children=children),
            metadata={"extensions": {"parrot_variant": "mermaid-diagram"}},
        )
