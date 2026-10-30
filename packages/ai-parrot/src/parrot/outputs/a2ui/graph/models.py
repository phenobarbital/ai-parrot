"""The ``Graph`` viz-core composite's wire vocabulary (FEAT-529 Module 1).

:class:`GraphSpec` (and its child models) is the SINGLE source of vocabulary
for the ``Graph`` component — the mermaid codec (``graph/mermaid.py``), the
layered layout (``graph/layout.py``), the builder (``builders.build_graph``),
the ``FlowDefinition`` adapter (``adapters/flow.py``), the derived
``GRAPH_SCHEMA`` (``catalog/viz_core/graph.py``), and every renderer all
consume or produce a :class:`GraphSpec`; nothing else defines a parallel
shape (spec §7 "Patterns to Follow").

**What, never how** (spec §2 Overview, §7): no field on any model here may
carry a colour, a font, a pixel size or a renderer-library option.
``rankSep``/``nodeSep`` are ABSTRACT layout units, not pixels; node ``state``
is DATA (a domain enum) — the renderer contract (documented, not modelled
here) maps it to a viz-core semantic status role and paints that role with
its own theme. This invariant is enforced mechanically by
``test_graph_schema_has_no_colour_vocabulary`` (Module 2) against the
DERIVED wire schema, not against this module directly.

This module is pure and synchronous: no I/O, no catalog registration, no
import from ``parrot.bots``/``parrot.clients`` (core A2UI invariant, spec G9).
"""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

__all__ = [
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
    "LayoutEngine",
    "NodeShape",
    "NodeState",
    "Position",
    "RelHint",
    "VizSize",
]

GraphKind = Literal["flowchart", "state", "sequence", "dag", "c4"]
Direction = Literal["TB", "LR", "BT", "RL"]
NodeShape = Literal["rect", "rounded", "diamond", "circle", "hexagon", "subroutine"]
NodeState = Literal["pending", "running", "completed", "failed", "skipped", "waiting"]
EdgeKind = Literal["solid", "dashed", "thick"]
LayoutEngine = Literal["layered", "force", "manual"]
#: viz-core common prop (spec §2 Overview: size is intent, never pixels).
VizSize = Literal["inline", "tile", "hero"]
#: C4 abstraction level (Mermaid header: C4Context / C4Container / C4Component / C4Dynamic).
C4Level = Literal["context", "container", "component", "dynamic"]
#: C4 element type — exactly the 20 Mermaid C4 element macros, snake_case on the wire.
C4ElementType = Literal[
    "person",
    "person_ext",
    "system",
    "system_ext",
    "system_db",
    "system_db_ext",
    "system_queue",
    "system_queue_ext",
    "container",
    "container_ext",
    "container_db",
    "container_db_ext",
    "container_queue",
    "container_queue_ext",
    "component",
    "component_ext",
    "component_db",
    "component_db_ext",
    "component_queue",
    "component_queue_ext",
]
#: C4 boundary type — Enterprise_Boundary / System_Boundary / Container_Boundary / Boundary (generic).
C4BoundaryType = Literal["enterprise", "system", "container", "generic"]
#: Relationship placement hint — Mermaid Rel_U / Rel_D / Rel_L / Rel_R / Rel_Back.
RelHint = Literal["up", "down", "left", "right", "back"]


class GraphNode(BaseModel):
    """A single node in a :class:`GraphSpec`.

    Attributes:
        id: Unique node identifier (unique within the owning ``GraphSpec``).
        label: Display label. Renderers default to ``id`` when omitted.
        shape: Node shape hint. Renderer default is ``rect`` (``rounded`` for
            ``kind="state"`` graphs).
        group: The :class:`GraphGroup.id` this node belongs to, if any.
        state: DATA, not styling — the domain state of whatever this node
            represents. The renderer contract maps it to a viz-core semantic
            status role (documented in ``catalog/viz_core/graph.py``/the
            renderer modules, not here).
        icon: A free-form icon name hint (``parrot_icon`` semantics per
            ``KPICard.icon``, FEAT-527) — never an asset path or pixel size.
        meta: Opaque data surfaced by renderers as a tooltip. Never
            interpreted by this module.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    id: str
    label: Optional[str] = None
    shape: Optional[NodeShape] = None
    group: Optional[str] = None
    state: Optional[NodeState] = None
    icon: Optional[str] = None
    meta: Optional[dict[str, Any]] = None
    c4_type: Optional[C4ElementType] = Field(default=None, alias="c4Type")
    technology: Optional[str] = None
    description: Optional[str] = None


class GraphEdge(BaseModel):
    """A directed edge between two :class:`GraphNode` ids.

    Attributes:
        from_: Source node id (wire alias ``from`` — ``from`` is a Python
            keyword, hence the trailing underscore).
        to: Target node id.
        label: Display label (e.g. a mermaid edge label, or a CEL predicate
            summary from ``flow_definition_to_graph``).
        kind: Edge stroke kind. Renderer default is ``solid``.
        condition: Free text (e.g. ``"on_error"``, a CEL predicate) — never
            interpreted here; carried through for renderers/tooltips.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    from_: str = Field(alias="from")
    to: str
    label: Optional[str] = None
    kind: Optional[EdgeKind] = None
    condition: Optional[str] = None
    technology: Optional[str] = None
    hint: Optional[RelHint] = None
    bidirectional: Optional[bool] = None


class GraphGroup(BaseModel):
    """A named grouping of node ids (rendered as a bounding box).

    Attributes:
        id: Unique group identifier.
        label: Display label for the group.
        nodes: Member node ids. Every id must exist in the owning
            :class:`GraphSpec` and belong to at most one group.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    id: str
    label: Optional[str] = None
    nodes: list[str]
    parent: Optional[str] = None
    c4_type: Optional[C4BoundaryType] = Field(default=None, alias="c4Type")


class Position(BaseModel):
    """An abstract-unit 2D coordinate (origin top-left, never pixels).

    Attributes:
        x: Horizontal coordinate, abstract units.
        y: Vertical coordinate, abstract units.
    """

    model_config = ConfigDict(extra="forbid")

    x: float
    y: float


class GraphLayout(BaseModel):
    """Layout configuration and (optionally) precomputed node positions.

    Attributes:
        engine: The layout engine hint. ``"layered"`` (default) is computed
            server-side (``graph/layout.py``); ``"force"`` is an interactive-
            renderer-only hint (static lanes degrade to layered); ``"manual"``
            requires ``positions`` to cover every node.
        rank_sep: Abstract rank-axis spacing unit (wire alias ``rankSep``) —
            NOT pixels.
        node_sep: Abstract cross-axis spacing unit (wire alias ``nodeSep``) —
            NOT pixels.
        positions: Precomputed node positions, keyed by node id. Required
            (and must cover every node) when ``engine == "manual"``.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    engine: LayoutEngine = "layered"
    rank_sep: Optional[float] = Field(default=None, alias="rankSep")
    node_sep: Optional[float] = Field(default=None, alias="nodeSep")
    positions: Optional[dict[str, Position]] = None
    shape_in_row: Optional[int] = Field(default=None, alias="shapeInRow", ge=1)
    boundary_in_row: Optional[int] = Field(default=None, alias="boundaryInRow", ge=1)


class GraphSelection(BaseModel):
    """Node selection state.

    Attributes:
        selectable: Whether nodes may be selected (renderer hint).
        selected: The currently selected node id, if any.
    """

    model_config = ConfigDict(extra="forbid")

    selectable: bool = False
    selected: Optional[str] = None


class GraphSpec(BaseModel):
    """Wire vocabulary of the viz-core ``Graph`` composite (camelCase aliases).

    This is the SINGLE source of vocabulary for ``Graph`` — see this
    module's docstring. ``action`` is deliberately NOT a field here: it is
    the component-level prop the catalog layer (``catalog/viz_core/
    graph.py``) declares explicitly in ``GRAPH_SCHEMA`` (a ``$ref`` to
    ``common_types.json#/$defs/Action``), because ``action`` is not part of
    the official ``ComponentCommon`` (spec §2 Overview).

    Attributes:
        kind: The graph's semantic kind. ``kind="dag"`` enforces
            acyclicity; ``"flowchart"``/``"state"``/``"sequence"`` legally
            allow cycles (real workflows loop).
        direction: Layout direction hint honoured by ``compute_positions``.
        title: Optional display title.
        accessible_description: viz-core common prop (wire alias
            ``accessibleDescription``) — plain-language summary used as the
            lowered fallback's first line and the SVG ``<title>``.
        size: viz-core common prop — layout INTENT (``inline``/``tile``/
            ``hero``), never pixels.
        nodes: The graph's nodes.
        edges: The graph's edges. Every endpoint must reference an existing
            node id.
        groups: Optional node groupings. Every member must exist and belong
            to at most one group.
        layout: Optional layout configuration/precomputed positions.
        selection: Optional selection state.
        data: INPUT-ONLY — a data-model binding descriptor replaces this
            field in the DERIVED wire schema (``GRAPH_SCHEMA``, Module 2).
            Resolves to ``{node_id: {"state"?: NodeState, "label"?: str,
            "meta"?: dict}}``, overlaying the matching node's ``state``/
            ``label``/``meta`` at render time.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    kind: GraphKind = "flowchart"
    direction: Direction = "TB"
    title: Optional[str] = None
    accessible_description: Optional[str] = Field(default=None, alias="accessibleDescription")
    size: VizSize = "tile"
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    groups: Optional[list[GraphGroup]] = None
    layout: Optional[GraphLayout] = None
    selection: Optional[GraphSelection] = None
    data: Optional[dict[str, dict[str, Any]]] = None
    level: Optional[C4Level] = None

    @model_validator(mode="after")
    def _validate_graph(self) -> GraphSpec:
        """Enforce the spec §2 Data Models invariants (all reported via ``ValueError``).

        * Node ids are unique.
        * Every edge endpoint (``from``/``to``) references an existing node.
        * Every group member exists and belongs to at most one group.
        * ``kind == "dag"`` implies the edge graph is acyclic (cycles are
          legal for every other ``kind`` — real workflows loop).
        * ``layout.engine == "manual"`` implies ``layout.positions`` covers
          every node.
        """
        node_ids = [node.id for node in self.nodes]
        id_set = set(node_ids)
        if len(node_ids) != len(id_set):
            seen: set[str] = set()
            dupes: set[str] = set()
            for node_id in node_ids:
                if node_id in seen:
                    dupes.add(node_id)
                seen.add(node_id)
            raise ValueError(f"Duplicate GraphNode id(s): {sorted(dupes)}")

        for edge in self.edges:
            if edge.from_ not in id_set:
                raise ValueError(f"GraphEdge.from {edge.from_!r} does not reference an existing node")
            if edge.to not in id_set:
                raise ValueError(f"GraphEdge.to {edge.to!r} does not reference an existing node")

        if self.groups:
            node_group: dict[str, str] = {}
            for group in self.groups:
                for member in group.nodes:
                    if member not in id_set:
                        raise ValueError(f"GraphGroup {group.id!r} references unknown node {member!r}")
                    if member in node_group:
                        raise ValueError(
                            f"Node {member!r} belongs to more than one group "
                            f"({node_group[member]!r} and {group.id!r})"
                        )
                    node_group[member] = group.id

        if self.kind == "dag" and self._has_cycle():
            raise ValueError("kind='dag' requires an acyclic graph, but a cycle was found")

        if self.layout is not None and self.layout.engine == "manual":
            positions = self.layout.positions or {}
            missing = id_set - set(positions)
            if missing:
                raise ValueError(
                    "layout.engine='manual' requires a position for every node; " f"missing: {sorted(missing)}"
                )

        self._validate_c4()
        return self

    def _validate_c4(self) -> None:
        """Enforce V1–V7 for C4 vocabulary and group parent relationships."""
        is_c4 = self.kind == "c4"
        groups = self.groups or []

        if is_c4:
            if self.level is None:
                raise ValueError("kind='c4' requires level")
            for node in self.nodes:
                if node.c4_type is None:
                    raise ValueError(f"kind='c4' requires c4_type for node {node.id!r}")
        else:
            if self.level is not None:
                raise ValueError("level is only valid for kind='c4'")
            for node in self.nodes:
                if node.c4_type is not None:
                    raise ValueError("node.c4_type is only valid for kind='c4'")
            for edge in self.edges:
                if edge.hint is not None:
                    raise ValueError("edge.hint is only valid for kind='c4'")
                if edge.bidirectional is not None:
                    raise ValueError("edge.bidirectional is only valid for kind='c4'")
            for group in groups:
                if group.parent is not None:
                    raise ValueError("group.parent is only valid for kind='c4'")
                if group.c4_type is not None:
                    raise ValueError("group.c4_type is only valid for kind='c4'")
            if self.layout is not None:
                if self.layout.shape_in_row is not None:
                    raise ValueError("layout.shape_in_row is only valid for kind='c4'")
                if self.layout.boundary_in_row is not None:
                    raise ValueError("layout.boundary_in_row is only valid for kind='c4'")

        group_ids = [group.id for group in groups]
        group_id_set = set(group_ids)
        if len(group_ids) != len(group_id_set):
            duplicates = sorted({group_id for group_id in group_ids if group_ids.count(group_id) > 1})
            raise ValueError(f"Duplicate GraphGroup id(s): {duplicates}")
        for group in groups:
            if group.parent is not None:
                if group.parent not in group_id_set:
                    raise ValueError(f"GraphGroup {group.id!r} parent references unknown group {group.parent!r}")
                if group.parent == group.id:
                    raise ValueError(f"GraphGroup {group.id!r} cannot be its own parent")
        cycle_group = self._group_parent_cycle()
        if cycle_group is not None:
            raise ValueError(f"GraphGroup parent cycle found at {cycle_group!r}")

        if self.layout is not None:
            shape_in_row = self.layout.shape_in_row
            boundary_in_row = self.layout.boundary_in_row
            if (shape_in_row is None) != (boundary_in_row is None):
                raise ValueError("layout.shape_in_row and layout.boundary_in_row must be set together")

        if self.level == "dynamic":
            for edge in self.edges:
                if edge.hint is not None or edge.bidirectional is not None:
                    raise ValueError("level='dynamic' does not allow edge hint or bidirectional")

        if is_c4:
            for edge in self.edges:
                if edge.bidirectional is True and edge.hint is not None:
                    raise ValueError("bidirectional C4 edges cannot specify hint")
            for node in self.nodes:
                if node.c4_type is not None and node.c4_type.startswith(("person", "system")):
                    if node.technology is not None:
                        raise ValueError(f"C4 {node.c4_type} node {node.id!r} cannot specify technology")

    def _group_parent_cycle(self) -> Optional[str]:
        """Return the first group id whose parent chain loops back on itself, else None."""
        parents = {group.id: group.parent for group in self.groups or []}
        for start in parents:
            visited: set[str] = set()
            current: Optional[str] = start
            while current is not None:
                if current in visited:
                    return current
                visited.add(current)
                current = parents.get(current)
        return None

    def _has_cycle(self) -> bool:
        """Whether the (directed) edge graph contains a cycle.

        Iterative 3-colour DFS with an explicit stack (mirrors
        ``graph/layout.py``'s ``_break_cycles``) — deliberately NOT recursive
        Python-call-stack DFS, so an adversarially large or long-chained
        ``dag`` candidate raises the intended ``ValidationError`` via the
        caller's ``kind == "dag"`` check rather than crashing the process
        with an unhandled ``RecursionError``.
        """
        adjacency: dict[str, list[str]] = {}
        for edge in self.edges:
            adjacency.setdefault(edge.from_, []).append(edge.to)

        WHITE, GRAY, BLACK = 0, 1, 2
        color: dict[str, int] = {node.id: WHITE for node in self.nodes}

        for start in color:
            if color[start] != WHITE:
                continue
            stack: list[tuple[str, int]] = [(start, 0)]
            color[start] = GRAY
            while stack:
                node_id, child_index = stack[-1]
                neighbours = adjacency.get(node_id, [])
                if child_index < len(neighbours):
                    stack[-1] = (node_id, child_index + 1)
                    neighbour = neighbours[child_index]
                    if neighbour not in color:
                        # Dangling edge target — already rejected earlier in
                        # _validate_graph; defensively skip rather than KeyError.
                        continue
                    if color[neighbour] == WHITE:
                        color[neighbour] = GRAY
                        stack.append((neighbour, 0))
                    elif color[neighbour] == GRAY:
                        return True
                else:
                    color[node_id] = BLACK
                    stack.pop()

        return False
