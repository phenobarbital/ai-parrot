"""``MermaidDiagramTool`` — render Mermaid source as an inline A2UI ``MermaidDiagram`` surface (FEAT-753).

Reachable via the legacy path too (``parrot.tools`` meta_path finder):
``from parrot.tools.mermaid_diagram import MermaidDiagramTool``.
"""

from __future__ import annotations

from typing import Any

from parrot.outputs.a2ui.builders import build_mermaid_diagram
from parrot.tools.abstract import AbstractTool, AbstractToolArgsSchema
from pydantic import Field


class MermaidDiagramArgs(AbstractToolArgsSchema):
    """Arguments for rendering a Mermaid diagram as an inline A2UI surface."""

    source: str = Field(
        description=(
            "Mermaid source (flowchart, sequenceDiagram, classDiagram, erDiagram, gantt, pie, mindmap, …). "
            "No %%{init}%% directives, no click statements."
        )
    )
    title: str | None = Field(default=None, description="Optional title shown above the diagram.")
    caption: str | None = Field(default=None, description="Optional caption shown below the diagram.")
    theme: str | None = Field(
        default=None, description="Optional Mermaid theme hint: default, neutral, dark, forest, base."
    )
    accessible_description: str | None = Field(
        default=None, description="One-sentence screen-reader summary of what the diagram shows."
    )


class MermaidDiagramTool(AbstractTool):
    """Render Mermaid source as an inline A2UI ``MermaidDiagram`` surface.

    Use it when the answer is best shown as a diagram (sequence, class, ER, state, flowchart, gantt, pie,
    mindmap, gitGraph, C4, …). The source is validated (size cap, no init directives, no click/javascript
    statements) and returned as an A2UI envelope the chat UI renders inline; text-only channels show the
    source. The bot lifts the envelope only when no interactive/infographic envelope was produced in the
    same turn — do not call it alongside an infographic render.
    """

    name = "render_mermaid_diagram"
    description = (
        "Render Mermaid diagram source (sequence, class, ER, state, flowchart, gantt, pie, mindmap, C4, …) as an "
        "inline A2UI diagram surface; pass source and optionally title, caption, theme, accessible_description."
    )
    args_schema = MermaidDiagramArgs

    async def _execute(
        self,
        *,
        source: str,
        title: str | None = None,
        caption: str | None = None,
        theme: str | None = None,
        accessible_description: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Return the lift-shaped dict (spec §2 "Tool result shape").

        Raises:
            CatalogValidationError: invalid source — propagated so ``execute()`` reports the issue codes.
        """
        envelope = build_mermaid_diagram(
            source=source, title=title, caption=caption, theme=theme, accessible_description=accessible_description
        )
        root = envelope.components[0].model_extra or {}
        diagram_type = root.get("diagramType")
        self.logger.debug("render_mermaid_diagram built a %s surface", diagram_type)
        return {
            "a2ui_envelope": envelope.model_dump(by_alias=True, mode="json"),
            "artifacts": [
                {
                    "type": "a2ui_surface",
                    "component": "MermaidDiagram",
                    "surface_id": envelope.surface_id,
                    "diagram_type": diagram_type,
                }
            ],
            "diagram_type": diagram_type,
            "source": root.get("source"),
        }
