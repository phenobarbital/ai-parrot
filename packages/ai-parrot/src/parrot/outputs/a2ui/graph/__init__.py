"""``parrot.outputs.a2ui.graph`` — the ``Graph`` viz-core composite's core vocabulary.

Pure, synchronous modules shared by every renderer and the catalog layer
(FEAT-529): :mod:`.models` (the Pydantic ``GraphSpec`` family),
:mod:`.mermaid` (the mermaid codec, Module 3), and :mod:`.layout` (the
layered layout, Module 4).
"""

from __future__ import annotations

from .layout import MAX_STATIC_NODES, GraphTooLargeError, LayoutResult, compute_positions
from .mermaid import MermaidCodecError, from_mermaid, to_mermaid
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
    "MAX_STATIC_NODES",
    "Direction",
    "EdgeKind",
    "GraphEdge",
    "GraphGroup",
    "GraphKind",
    "GraphLayout",
    "GraphNode",
    "GraphSelection",
    "GraphSpec",
    "GraphTooLargeError",
    "LayoutEngine",
    "LayoutResult",
    "MermaidCodecError",
    "NodeShape",
    "NodeState",
    "Position",
    "VizSize",
    "compute_positions",
    "from_mermaid",
    "to_mermaid",
]
