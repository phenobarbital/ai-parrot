"""``parrot.outputs.a2ui.graph`` — the ``Graph`` viz-core composite's core vocabulary.

Pure, synchronous modules shared by every renderer and the catalog layer
(FEAT-529): :mod:`.models` (the Pydantic ``GraphSpec`` family),
:mod:`.mermaid` (the mermaid codec, Module 3), and :mod:`.layout` (the
layered layout, Module 4).
"""

from __future__ import annotations

from .layout import MAX_STATIC_NODES, GraphTooLargeError, LayoutResult, compute_positions
from .mermaid import MermaidCodecError, from_mermaid, to_mermaid
from .mermaid_source import (
    MERMAID_DIAGRAM_ROUTE_KEY,
    MERMAID_DIAGRAM_ROUTE_UTTERANCES,
    MERMAID_DIAGRAM_TYPES,
    MERMAID_SOURCE_MAX_BYTES,
    check_mermaid_source,
    detect_diagram_type,
    graph_spec_from_mermaid_source,
    normalize_mermaid_source,
)
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
    "MERMAID_DIAGRAM_ROUTE_KEY",
    "MERMAID_DIAGRAM_ROUTE_UTTERANCES",
    "MERMAID_DIAGRAM_TYPES",
    "MERMAID_SOURCE_MAX_BYTES",
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
    "check_mermaid_source",
    "compute_positions",
    "detect_diagram_type",
    "from_mermaid",
    "graph_spec_from_mermaid_source",
    "normalize_mermaid_source",
    "to_mermaid",
]
