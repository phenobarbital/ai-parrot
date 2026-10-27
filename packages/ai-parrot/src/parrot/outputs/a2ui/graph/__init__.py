"""``parrot.outputs.a2ui.graph`` — the ``Graph`` viz-core composite's core vocabulary.

Pure, synchronous modules shared by every renderer and the catalog layer
(FEAT-529): :mod:`.models` (the Pydantic ``GraphSpec`` family),
:mod:`.mermaid` (the Mermaid codecs, including C4), and :mod:`.layout`
(the layered layout, with :mod:`.layout_c4` for C4 placement).
"""

from __future__ import annotations

from .layout import MAX_STATIC_NODES, GraphTooLargeError, LayoutResult, compute_positions
from .layout_c4 import compute_c4_positions
from .mermaid import MermaidCodecError, from_mermaid, to_mermaid
from .mermaid_c4 import C4_LOSSY_FIELDS, from_mermaid_c4, to_mermaid_c4
from .models import (
    C4BoundaryType,
    C4ElementType,
    C4Level,
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
    RelHint,
    VizSize,
)

__all__ = [
    "MAX_STATIC_NODES",
    "C4_LOSSY_FIELDS",
    "C4BoundaryType",
    "C4ElementType",
    "C4Level",
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
    "RelHint",
    "VizSize",
    "compute_positions",
    "compute_c4_positions",
    "from_mermaid",
    "from_mermaid_c4",
    "to_mermaid",
    "to_mermaid_c4",
]
