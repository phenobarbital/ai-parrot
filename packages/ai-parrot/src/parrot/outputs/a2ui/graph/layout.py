"""Deterministic layered layout for the ``Graph`` vocabulary (FEAT-529 Module 4).

Layout is SERVER-SIDE PREPARATION, not styling (spec §2 Overview rule 3):
positions computed here travel on the wire (``GraphLayout.positions``) so
every renderer — the bundled UI, ECharts, and the static SVG lanes — draws
the same picture from the same numbers, with ``layout: "none"`` where the
renderer supports native layout. Positions are emitted ALREADY oriented for
the requested ``direction`` — renderers read ``direction`` only for
arrow/label placement hints, never to re-transform a position (spec §7
"Positions and direction").

Algorithm (a hand-written, dependency-light layered/Sugiyama-style layout,
not a full crossing-minimization implementation):

1. **Cycle breaking** — a stable DFS (3-colour, input node order) finds
   every back edge; each is logically reversed for ranking purposes only
   and recorded in :attr:`LayoutResult.reversed_edges` (the ORIGINAL
   ``(from, to)`` pair — renderers draw the arrowhead on the original
   direction and flip it, per spec §7). Cycles are legal for every
   ``kind`` except ``"dag"`` (rejected earlier, at the model level).
2. **Rank assignment** — longest-path layering over the now-acyclic edge
   set, via :func:`networkx.topological_sort` (the one place
   ``networkx``, already a core hard dependency, is used — spec §3
   Module 4 permits it for "topological generations / cycle detection
   only").
3. **Crossing reduction** — four barycentre sweeps (down/up/down/up),
   stable-sorting each rank's nodes by the mean cross-axis position of
   their neighbours in the adjacent rank, falling back to the current
   position when a node has none.
4. **Coordinate assignment** — integer rank/slot indices scaled by
   ``rank_sep``/``node_sep`` (abstract units) only at the very end, so the
   algorithm itself is exact-integer and platform-independent; axes are
   swapped/placed per ``direction`` (``TB``/``BT``: rank axis is Y;
   ``LR``/``RL``: rank axis is X; ``BT``/``RL`` mirror the rank axis).
5. **Group bounding boxes** — the padded min/max of each group's member
   positions.

Pure and synchronous: no I/O beyond ``logging.getLogger(__name__)`` at
debug (per spec §7 "Patterns to Follow").
"""

from __future__ import annotations

import logging

import networkx as nx
from pydantic import BaseModel, ConfigDict

from parrot.outputs.a2ui.catalog.base import CatalogValidationError
from parrot.outputs.a2ui.graph.models import Direction, GraphSpec, Position

__all__ = ["MAX_STATIC_NODES", "GraphTooLargeError", "LayoutResult", "compute_positions"]

logger = logging.getLogger(__name__)

#: Above this many nodes, static renderers (SVG/SSR-HTML/PDF) degrade
#: rather than lay out and draw a graph (spec §8 open question — default
#: 200, pending Jesus Lara's confirmation after measuring a 200-node
#: fixture). ECharts and the bundled UI have no cap (spec §7).
MAX_STATIC_NODES = 200

#: Padding (abstract units) around a group's member bounding box, and
#: around the overall layout's extent for `LayoutResult.width`/`.height`.
_GROUP_PADDING = 20.0
_LAYOUT_PADDING = 20.0


class GraphTooLargeError(CatalogValidationError):
    """Raised by :func:`compute_positions` above :data:`MAX_STATIC_NODES`.

    Subclasses :class:`~parrot.outputs.a2ui.catalog.base.CatalogValidationError`
    (same reasoning as ``MermaidCodecError``) so the LLM producer's
    validate-retry-degrade loop needs no new plumbing; static renderers
    catch it explicitly to degrade instead (Module 6).

    Attributes:
        node_count: The offending node count.
    """

    def __init__(self, node_count: int) -> None:
        super().__init__(f"Graph has {node_count} nodes, exceeding the static layout cap of {MAX_STATIC_NODES}.")
        self.node_count = node_count


class LayoutResult(BaseModel):
    """The output of :func:`compute_positions`.

    Attributes:
        positions: Final, direction-oriented positions, keyed by node id.
            Abstract units, origin top-left.
        width: Overall layout width (abstract units), including padding.
        height: Overall layout height (abstract units), including padding.
        group_boxes: Per-group ``(x, y, w, h)`` bounding box, padded around
            its members' positions.
        reversed_edges: The ORIGINAL ``(from, to)`` pairs that were
            logically reversed to break a cycle for ranking purposes —
            renderers draw the arrowhead on the original direction and
            flip it (spec §7).
    """

    model_config = ConfigDict(extra="forbid")

    positions: dict[str, Position]
    width: float
    height: float
    group_boxes: dict[str, tuple[float, float, float, float]]
    reversed_edges: list[tuple[str, str]]


def _break_cycles(
    node_ids: list[str], edge_pairs: list[tuple[str, str]]
) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    """Stable DFS (3-colour) feedback-arc-set: flips every back edge.

    Args:
        node_ids: Node ids in stable input order (DFS root order).
        edge_pairs: ``(from, to)`` pairs in input order.

    Returns:
        ``(dag_edges, reversed_edges)`` — ``dag_edges`` is ``edge_pairs``
        with every back edge flipped to ``(to, from)`` (an acyclic edge
        set for ranking); ``reversed_edges`` lists the ORIGINAL ``(from,
        to)`` pairs that were flipped, in encounter order.
    """
    adjacency: dict[str, list[str]] = {node_id: [] for node_id in node_ids}
    for from_id, to_id in edge_pairs:
        adjacency[from_id].append(to_id)

    WHITE, GRAY, BLACK = 0, 1, 2
    color = {node_id: WHITE for node_id in node_ids}
    back_edges: set[tuple[str, str]] = set()

    def _visit(start: str) -> None:
        stack: list[tuple[str, int]] = [(start, 0)]
        color[start] = GRAY
        while stack:
            node_id, child_index = stack[-1]
            neighbours = adjacency[node_id]
            if child_index < len(neighbours):
                stack[-1] = (node_id, child_index + 1)
                neighbour = neighbours[child_index]
                if color[neighbour] == WHITE:
                    color[neighbour] = GRAY
                    stack.append((neighbour, 0))
                elif color[neighbour] == GRAY:
                    back_edges.add((node_id, neighbour))
            else:
                color[node_id] = BLACK
                stack.pop()

    for node_id in node_ids:
        if color[node_id] == WHITE:
            _visit(node_id)

    dag_edges: list[tuple[str, str]] = []
    reversed_edges: list[tuple[str, str]] = []
    for from_id, to_id in edge_pairs:
        if (from_id, to_id) in back_edges:
            dag_edges.append((to_id, from_id))
            reversed_edges.append((from_id, to_id))
        else:
            dag_edges.append((from_id, to_id))
    return dag_edges, reversed_edges


def _assign_ranks(node_ids: list[str], dag_edges: list[tuple[str, str]]) -> dict[str, int]:
    """Longest-path rank assignment over the acyclic ``dag_edges``."""
    graph: nx.DiGraph = nx.DiGraph()
    graph.add_nodes_from(node_ids)
    graph.add_edges_from((u, v) for u, v in dag_edges if u != v)

    rank = dict.fromkeys(node_ids, 0)
    for node_id in nx.topological_sort(graph):
        for successor in graph.successors(node_id):
            candidate = rank[node_id] + 1
            if candidate > rank[successor]:
                rank[successor] = candidate
    return rank


def _order_within_ranks(
    node_ids: list[str], rank: dict[str, int], dag_edges: list[tuple[str, str]]
) -> dict[int, list[str]]:
    """Four barycentre sweeps; returns each rank's nodes in slot order."""
    by_rank: dict[int, list[str]] = {}
    for node_id in node_ids:
        by_rank.setdefault(rank[node_id], []).append(node_id)

    if not by_rank:
        return by_rank
    max_rank = max(by_rank)

    down_adjacency: dict[str, list[str]] = {}
    up_adjacency: dict[str, list[str]] = {}
    for u, v in dag_edges:
        if u == v:
            continue
        down_adjacency.setdefault(u, []).append(v)
        up_adjacency.setdefault(v, []).append(u)

    slot: dict[str, int] = {}
    for nodes in by_rank.values():
        for index, node_id in enumerate(nodes):
            slot[node_id] = index

    for sweep in range(4):
        downward = sweep % 2 == 0
        rank_sequence = range(1, max_rank + 1) if downward else range(max_rank - 1, -1, -1)
        neighbours_of = up_adjacency if downward else down_adjacency
        for current_rank in rank_sequence:
            nodes = by_rank.get(current_rank)
            if not nodes:
                continue

            def _barycentre(node_id: str) -> float:
                neighbours = neighbours_of.get(node_id, [])
                if not neighbours:
                    return float(slot[node_id])
                return sum(slot[n] for n in neighbours) / len(neighbours)

            nodes.sort(key=lambda node_id: (_barycentre(node_id), slot[node_id]))
            for index, node_id in enumerate(nodes):
                slot[node_id] = index

    return by_rank


def compute_positions(
    spec: GraphSpec,
    *,
    rank_sep: float = 80.0,
    node_sep: float = 40.0,
) -> LayoutResult:
    """Compute a deterministic layered layout for ``spec``.

    Args:
        spec: The graph to lay out. Its own ``layout.rank_sep``/
            ``layout.node_sep`` are NOT read here — callers (the builder)
            pass them explicitly if they want to override the defaults.
        rank_sep: Abstract-unit spacing between consecutive ranks.
        node_sep: Abstract-unit spacing between consecutive nodes within
            the same rank.

    Returns:
        A :class:`LayoutResult` with positions for every node, overall
        dimensions, per-group bounding boxes, and any reversed edges.

    Raises:
        GraphTooLargeError: If ``len(spec.nodes) > MAX_STATIC_NODES``.
    """
    node_count = len(spec.nodes)
    if node_count > MAX_STATIC_NODES:
        raise GraphTooLargeError(node_count)

    node_ids = [node.id for node in spec.nodes]
    edge_pairs = [(edge.from_, edge.to) for edge in spec.edges]

    dag_edges, reversed_edges = _break_cycles(node_ids, edge_pairs)
    rank = _assign_ranks(node_ids, dag_edges)
    by_rank = _order_within_ranks(node_ids, rank, dag_edges)

    slot: dict[str, int] = {}
    for nodes in by_rank.values():
        for index, node_id in enumerate(nodes):
            slot[node_id] = index

    max_rank = max(by_rank) if by_rank else 0
    positions: dict[str, Position] = {}
    for node_id in node_ids:
        rank_coord = rank[node_id] * rank_sep
        cross_coord = slot[node_id] * node_sep
        positions[node_id] = _oriented_position(rank_coord, cross_coord, spec.direction)

    width, height = _extent(positions, max_rank, rank_sep, node_sep, spec.direction, by_rank)
    group_boxes = _group_boxes(spec, positions)

    logger.debug(
        "compute_positions: %d nodes, %d ranks, %d reversed edge(s)",
        node_count,
        max_rank + 1 if by_rank else 0,
        len(reversed_edges),
    )

    return LayoutResult(
        positions=positions,
        width=width,
        height=height,
        group_boxes=group_boxes,
        reversed_edges=reversed_edges,
    )


def _oriented_position(rank_coord: float, cross_coord: float, direction: Direction) -> Position:
    """Place ``(rank_coord, cross_coord)`` on the axes ``direction`` implies.

    ``TB``/``BT``: the rank axis is Y (vertical); ``LR``/``RL``: the rank
    axis is X (horizontal) — i.e. ``LR`` positions are the ``TB``
    positions with X/Y swapped (spec test: "LR == transposed TB"). ``BT``/
    ``RL`` additionally mirror their rank axis (reversed_edges are still
    reported on the ORIGINAL direction; only the coordinate is mirrored).
    """
    if direction in ("TB", "BT"):
        # BT mirrors the rank axis; the caller passes the UN-mirrored
        # rank_coord (0 at the first rank) — mirroring happens afterwards,
        # in `_extent`, once `max_rank` is known (see `compute_positions`).
        return Position(x=cross_coord, y=rank_coord)
    return Position(x=rank_coord, y=cross_coord)  # LR, RL (RL mirrored in `_extent`)


def _extent(
    positions: dict[str, Position],
    max_rank: int,
    rank_sep: float,
    node_sep: float,
    direction: Direction,
    by_rank: dict[int, list[str]],
) -> tuple[float, float]:
    """Mirror BT/RL in place (rank axis reversed) and return (width, height)."""
    if direction in ("BT", "RL"):
        rank_extent = max_rank * rank_sep
        for nodes in by_rank.values():
            for node_id in nodes:
                pos = positions[node_id]
                if direction == "BT":
                    positions[node_id] = Position(x=pos.x, y=rank_extent - pos.y)
                else:  # RL
                    positions[node_id] = Position(x=rank_extent - pos.x, y=pos.y)

    if not positions:
        return (_LAYOUT_PADDING * 2, _LAYOUT_PADDING * 2)

    max_x = max(pos.x for pos in positions.values())
    max_y = max(pos.y for pos in positions.values())
    return (max_x + _LAYOUT_PADDING * 2, max_y + _LAYOUT_PADDING * 2)


def _group_boxes(spec: GraphSpec, positions: dict[str, Position]) -> dict[str, tuple[float, float, float, float]]:
    boxes: dict[str, tuple[float, float, float, float]] = {}
    for group in spec.groups or []:
        member_positions = [positions[member_id] for member_id in group.nodes]
        if not member_positions:
            continue
        min_x = min(p.x for p in member_positions) - _GROUP_PADDING
        min_y = min(p.y for p in member_positions) - _GROUP_PADDING
        max_x = max(p.x for p in member_positions) + _GROUP_PADDING
        max_y = max(p.y for p in member_positions) + _GROUP_PADDING
        boxes[group.id] = (min_x, min_y, max_x - min_x, max_y - min_y)
    return boxes
