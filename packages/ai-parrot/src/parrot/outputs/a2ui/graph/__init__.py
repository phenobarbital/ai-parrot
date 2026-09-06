"""``parrot.outputs.a2ui.graph`` — the ``Graph`` viz-core composite's core vocabulary.

Pure, synchronous modules shared by every renderer and the catalog layer
(FEAT-529): :mod:`.models` (the Pydantic ``GraphSpec`` family — this
package's only module so far). ``.mermaid`` (the mermaid codec, Module 3)
and ``.layout`` (the layered layout, Module 4) add their own exports here
once they land.
"""

from __future__ import annotations

from .models import (
    Direction,
    EdgeKind,
    GraphEdge,
    GraphGroup,
    GraphKind,
    GraphLayout,
    GraphNode,
    GraphSelection,
    GraphSpec,
    LayoutEngine,
    NodeShape,
    NodeState,
    Position,
    VizSize,
)

__all__ = [
    "Direction",
    "EdgeKind",
    "GraphEdge",
    "GraphGroup",
    "GraphKind",
    "GraphLayout",
    "GraphNode",
    "GraphSelection",
    "GraphSpec",
    "LayoutEngine",
    "NodeShape",
    "NodeState",
    "Position",
    "VizSize",
]
