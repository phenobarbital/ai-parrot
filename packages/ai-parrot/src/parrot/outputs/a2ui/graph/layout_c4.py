"""Deterministic C4 layout for ``GraphSpec(kind="c4")`` (FEAT-754, spec §3 Module 3).

Tier 0 = persons, tier 1 = internal elements laid in nested boundary boxes, tier 2 = other ``*_ext``.
Pure integer slot arithmetic, scaled at the end; no networkx.
"""

from __future__ import annotations

import logging
from typing import Optional

from .layout import (
    MAX_STATIC_NODES,
    _LAYOUT_PADDING,
    GraphTooLargeError,
    LayoutResult,
    _extent,
    _group_boxes,
    _oriented_position,
)
from .models import GraphGroup, GraphNode, GraphSpec, Position

__all__ = ["DEFAULT_BOUNDARY_IN_ROW", "DEFAULT_SHAPE_IN_ROW", "compute_c4_positions"]

logger = logging.getLogger(__name__)

DEFAULT_SHAPE_IN_ROW: int = 4
DEFAULT_BOUNDARY_IN_ROW: int = 2


def _tier_of(node: GraphNode) -> int:
    """Return the C4 rank tier for ``node``."""
    c4_type = node.c4_type or ""
    if c4_type.startswith("person"):
        return 0
    return 2 if c4_type.endswith("_ext") else 1


def _boundary_tree(spec: GraphSpec) -> dict[Optional[str], list[GraphGroup]]:
    """Return children keyed by parent id, preserving ``groups`` order."""
    tree: dict[Optional[str], list[GraphGroup]] = {}
    for group in spec.groups or []:
        tree.setdefault(group.parent, []).append(group)
    return tree


def _footprint(
    group_id: Optional[str],
    members: list[str],
    children: dict[Optional[str], list[GraphGroup]],
    shape_in_row: int,
    depth: int,
) -> tuple[int, int]:
    """Return the bottom-up ``(cross_slots, rank_slots)`` footprint of a boundary."""
    member_width = min(len(members), shape_in_row)
    member_rows = (len(members) + shape_in_row - 1) // shape_in_row
    child_footprints = [
        _footprint(child.id, child.nodes, children, shape_in_row, depth + 1) for child in children.get(group_id, [])
    ]
    child_footprints = [footprint for footprint in child_footprints if footprint != (0, 0)]

    if not members and not child_footprints:
        return (0, 0)

    content_width = max([member_width] + [width for width, _ in child_footprints])
    content_height = member_rows + sum(height for _, height in child_footprints)
    return (content_width + 2 * depth, content_height + 2 * depth)


def _place(spec: GraphSpec, shape_in_row: int, boundary_in_row: int) -> dict[str, tuple[int, int]]:
    """Return integer ``(rank_slot, cross_slot)`` coordinates for every node."""
    slots: dict[str, tuple[int, int]] = {}
    nodes_by_id = {node.id: node for node in spec.nodes}
    tier_nodes = {tier: [node.id for node in spec.nodes if _tier_of(node) == tier] for tier in (0, 1, 2)}

    def place_row(nodes: list[str], rank_origin: int) -> int:
        for index, node_id in enumerate(nodes):
            row, column = divmod(index, shape_in_row)
            slots[node_id] = (rank_origin + row, column)
        return (len(nodes) + shape_in_row - 1) // shape_in_row

    next_rank = place_row(tier_nodes[0], 0)
    if tier_nodes[0]:
        next_rank += 1

    children = _boundary_tree(spec)
    grouped_tier_one = {
        member_id
        for group in spec.groups or []
        for member_id in group.nodes
        if member_id in nodes_by_id and _tier_of(nodes_by_id[member_id]) == 1
    }
    ungrouped = [node_id for node_id in tier_nodes[1] if node_id not in grouped_tier_one]

    def place_group(group: GraphGroup, rank_origin: int, cross_origin: int, depth: int) -> None:
        members = [
            member_id for member_id in group.nodes if member_id in nodes_by_id and _tier_of(nodes_by_id[member_id]) == 1
        ]
        for index, member_id in enumerate(members):
            row, column = divmod(index, shape_in_row)
            slots[member_id] = (rank_origin + depth + row, cross_origin + depth + column)

        member_rows = (len(members) + shape_in_row - 1) // shape_in_row
        child_rank = rank_origin + depth + member_rows
        for child in children.get(group.id, []):
            child_footprint = _footprint(child.id, child.nodes, children, shape_in_row, depth + 1)
            if child_footprint == (0, 0):
                continue
            place_group(child, child_rank, cross_origin + depth, depth + 1)
            child_rank += child_footprint[1]

    entries: list[tuple[Optional[GraphGroup], list[str], tuple[int, int]]] = []
    if ungrouped:
        entries.append(
            (
                None,
                ungrouped,
                (min(len(ungrouped), shape_in_row), (len(ungrouped) + shape_in_row - 1) // shape_in_row),
            )
        )
    for group in children.get(None, []):
        members = [
            member_id for member_id in group.nodes if member_id in nodes_by_id and _tier_of(nodes_by_id[member_id]) == 1
        ]
        footprint = _footprint(group.id, members, children, shape_in_row, 1)
        if footprint != (0, 0):
            entries.append((group, members, footprint))

    tier_one_start = next_rank
    for row_start in range(0, len(entries), boundary_in_row):
        row_entries = entries[row_start : row_start + boundary_in_row]
        cross_origin = 0
        row_height = max(footprint[1] for _, _, footprint in row_entries)
        for group, members, footprint in row_entries:
            if group is None:
                for index, member_id in enumerate(members):
                    row, column = divmod(index, shape_in_row)
                    slots[member_id] = (next_rank + row, cross_origin + column)
            else:
                place_group(group, next_rank, cross_origin, 1)
            cross_origin += footprint[0] + 1
        next_rank += row_height + 1

    if entries:
        next_rank -= 1
    elif tier_nodes[1]:
        next_rank = tier_one_start + place_row(tier_nodes[1], tier_one_start)

    if tier_nodes[2]:
        if slots:
            next_rank += 1
        place_row(tier_nodes[2], next_rank)

    return slots


def compute_c4_positions(
    spec: GraphSpec,
    *,
    rank_sep: float = 80.0,
    node_sep: float = 40.0,
) -> LayoutResult:
    """Compute deterministic C4 positions with no edge-driven cycle handling.

    Raises:
        GraphTooLargeError: If the graph exceeds ``MAX_STATIC_NODES``.
    """
    if len(spec.nodes) > MAX_STATIC_NODES:
        raise GraphTooLargeError(len(spec.nodes))

    layout = spec.layout
    shape_in_row = (layout.shape_in_row if layout else None) or DEFAULT_SHAPE_IN_ROW
    boundary_in_row = (layout.boundary_in_row if layout else None) or DEFAULT_BOUNDARY_IN_ROW
    slots = _place(spec, shape_in_row, boundary_in_row)

    by_rank: dict[int, list[str]] = {}
    positions: dict[str, Position] = {}
    for node in spec.nodes:
        rank_slot, cross_slot = slots[node.id]
        by_rank.setdefault(rank_slot, []).append(node.id)
        positions[node.id] = _oriented_position(rank_slot * rank_sep, cross_slot * node_sep, spec.direction)

    max_rank = max(by_rank, default=0)
    width, height = _extent(positions, max_rank, rank_sep, node_sep, spec.direction, by_rank)
    positions = {
        node_id: Position(x=position.x + _LAYOUT_PADDING, y=position.y + _LAYOUT_PADDING)
        for node_id, position in positions.items()
    }

    # Persons and ``*_ext`` members sit outside tier 1, so they must not stretch a boundary box.
    tier_one_ids = {node.id for node in spec.nodes if _tier_of(node) == 1}
    boxed_spec = spec.model_copy(
        update={
            "groups": [
                group.model_copy(update={"nodes": [node_id for node_id in group.nodes if node_id in tier_one_ids]})
                for group in spec.groups or []
            ]
        }
    )

    logger.debug("c4 layout: %d nodes, %d groups", len(spec.nodes), len(spec.groups or []))
    return LayoutResult(
        positions=positions,
        width=width,
        height=height,
        group_boxes=_group_boxes(boxed_spec, positions),
        reversed_edges=[],
    )
