"""``parrot.outputs.a2ui.graph`` — the ``Graph`` viz-core composite's core vocabulary.

Pure, synchronous modules shared by every renderer and the catalog layer
(FEAT-529): :mod:`.models` (the Pydantic ``GraphSpec`` family) and
:mod:`.mermaid` (the mermaid codec, Module 3). ``.layout`` (the layered
layout, Module 4) adds its own exports here once it lands.
"""

from __future__ import annotations

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
    "MermaidCodecError",
    "NodeShape",
    "NodeState",
    "Position",
    "VizSize",
    "from_mermaid",
    "to_mermaid",
]
