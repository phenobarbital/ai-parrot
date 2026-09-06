"""Shared static ``Graph`` SVG renderer (FEAT-529 Module 6).

One implementation, shared by every static lane that draws ``Graph``
inline (interactive-HTML, SSR-HTML, PDF) — spec's "one SVG implementation"
rule, so geometry, accessibility, semantic status roles, and the
degradation boundary agree everywhere instead of three renderers each
hand-rolling their own markup.

**No literal colour anywhere.** Node ``state`` (data) maps to a viz-core
semantic status role via :data:`STATE_TO_STATUS`, and each role maps to a
``DesignSystem`` CSS custom-property NAME (``--accent-green``, not
``#22c55e``) — the SVG references ``var(--token)``, the surrounding page's
own stylesheet (``DesignSystem.stylesheet()``) supplies the actual value.
No JavaScript; no external asset references (pure inline ``<svg>``).
"""

from __future__ import annotations

import html
from typing import Any

from parrot.outputs.a2ui.graph import GraphEdge, GraphGroup, GraphNode, GraphSpec, Position, compute_positions

__all__ = ["STATE_TO_STATUS", "render_graph_svg"]

#: Node domain ``state`` -> viz-core semantic status role (spec §2 renderer
#: contract — documented here, not on any core model: state is DATA, the
#: role/colour mapping is a RENDERER concern).
STATE_TO_STATUS: dict[str, str] = {
    "completed": "good",
    "waiting": "warning",
    "failed": "critical",
    "running": "primary",
    "pending": "neutral",
    "skipped": "neutral",
}

#: Status role -> ``DesignSystem`` CSS custom-property NAME (never a
#: resolved value — the SVG emits ``var(--token)``).
_STATUS_TO_TOKEN: dict[str, str] = {
    "good": "--accent-green",
    "warning": "--accent-amber",
    "critical": "--accent-red",
    "primary": "--primary",
    "neutral": "--neutral-muted",
}

#: Node box size (SVG user units) and canvas padding — independent from
#: `compute_positions`'s abstract rank/node separation units; this module
#: owns its own geometry.
_NODE_WIDTH = 120.0
_NODE_HEIGHT = 40.0
_PADDING = 40.0
_GROUP_MARGIN = 24.0

#: Wire Component-level keys (never part of GraphSpec) to strip from a
#: whole-component dict before reconstructing a bare GraphSpec.
_COMPONENT_ONLY_KEYS = frozenset(
    {"id", "component", "catalogId", "child", "children", "weight", "accessibility", "checks", "action", "metadata", "data"}
)


def render_graph_svg(props: dict[str, Any], *, theme: str | None = None) -> str:
    """Render a baked ``Graph`` component's props to a static SVG string.

    Args:
        props: The ``Graph`` component's props — either the bare GraphSpec
            fields (camelCase: ``kind``, ``direction``, ``nodes``,
            ``edges``, ``groups``, ``layout``, ``accessibleDescription``,
            ...) or a whole baked ``Component.model_dump()`` dict (also
            carrying ``id``/``component``/``catalogId``/``action``/
            ``metadata``); both shapes work — any wire Component-level key
            is stripped before reconstructing a ``GraphSpec``. ``data`` (an
            unresolved binding descriptor, or already-resolved by an
            upstream bake pass) is never read as a literal ``GraphSpec.data``
            value here — callers that need live node-state overlays must
            apply them to ``nodes``/``edges`` themselves BEFORE calling
            this function; this renderer draws exactly what ``nodes``/
            ``edges`` say.
        theme: Unused placeholder for a future per-call override. Every
            colour reference here is a ``DesignSystem`` CSS custom
            property NAME (``var(--accent-green)``), resolved by whatever
            stylesheet wraps the page — never resolved to a literal value
            in this function, so no theme value is needed to produce
            correct markup.

    Returns:
        A self-contained ``<svg>...</svg>`` string: one shape per node,
        group bounding boxes, arrow-marked edges styled by ``kind``, a
        ``<title>`` equal to ``accessibleDescription`` (or a generated
        summary), and ``data-state``/``data-status`` attributes per node.

    Raises:
        GraphTooLargeError: When positions must be computed (none were
            already supplied) and the graph exceeds
            :data:`~parrot.outputs.a2ui.graph.MAX_STATIC_NODES` — the
            caller (a renderer module) is expected to catch this and
            degrade (spec G8).
    """
    # `props` is a whole-component dict — a baked `Component.model_dump()`
    # (id/component/catalogId/action/metadata/... alongside the actual
    # GraphSpec fields) — never just `Component.model_extra` (which already
    # excludes those declared fields). Strip them, plus `data` (an
    # unresolved/resolved binding), before reconstructing a bare
    # `GraphSpec` (`extra="forbid"`).
    graph_props = {key: value for key, value in props.items() if key not in _COMPONENT_ONLY_KEYS}
    spec = GraphSpec.model_validate(graph_props)

    positions = _extract_positions(spec)
    if positions is None:
        positions = compute_positions(spec).positions

    half_w, half_h = _NODE_WIDTH / 2, _NODE_HEIGHT / 2
    offset_x = _PADDING + half_w
    offset_y = _PADDING + half_h
    positions = {node_id: Position(x=pos.x + offset_x, y=pos.y + offset_y) for node_id, pos in positions.items()}

    group_boxes = _compute_group_boxes(spec, positions)
    width, height = _extent(positions)

    accessible_description = spec.accessible_description or (
        f"Graph of {len(spec.nodes)} nodes and {len(spec.edges)} edges ({spec.kind})"
    )
    escaped_description = html.escape(accessible_description)

    body: list[str] = [_defs()]
    for group in spec.groups or []:
        box = group_boxes.get(group.id)
        if box is not None:
            body.append(_render_group_box(group, box))
    for edge in spec.edges:
        if edge.from_ in positions and edge.to in positions:
            body.append(_render_edge(edge, positions))
    for node in spec.nodes:
        body.append(_render_node(node, positions[node.id]))

    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width:.1f} {height:.1f}" '
        f'role="img" aria-label="{escaped_description}">'
        f"<title>{escaped_description}</title>"
        + "".join(body)
        + "</svg>"
    )


def _extract_positions(spec: GraphSpec) -> dict[str, Position] | None:
    """``spec.layout.positions`` when it covers every node, else ``None``."""
    positions = spec.layout.positions if spec.layout else None
    if positions and all(node.id in positions for node in spec.nodes):
        return positions
    return None


def _compute_group_boxes(
    spec: GraphSpec, positions: dict[str, Position]
) -> dict[str, tuple[float, float, float, float]]:
    half_w, half_h = _NODE_WIDTH / 2, _NODE_HEIGHT / 2
    boxes: dict[str, tuple[float, float, float, float]] = {}
    for group in spec.groups or []:
        member_positions = [positions[member] for member in group.nodes if member in positions]
        if not member_positions:
            continue
        min_x = min(p.x for p in member_positions) - half_w - _GROUP_MARGIN
        min_y = min(p.y for p in member_positions) - half_h - _GROUP_MARGIN
        max_x = max(p.x for p in member_positions) + half_w + _GROUP_MARGIN
        max_y = max(p.y for p in member_positions) + half_h + _GROUP_MARGIN
        boxes[group.id] = (min_x, min_y, max_x - min_x, max_y - min_y)
    return boxes


def _extent(positions: dict[str, Position]) -> tuple[float, float]:
    if not positions:
        return (_NODE_WIDTH + 2 * _PADDING, _NODE_HEIGHT + 2 * _PADDING)
    max_x = max(p.x for p in positions.values())
    max_y = max(p.y for p in positions.values())
    return (max_x + _NODE_WIDTH / 2 + _PADDING, max_y + _NODE_HEIGHT / 2 + _PADDING)


def _defs() -> str:
    return (
        "<defs>"
        '<marker id="graph-arrow" viewBox="0 0 10 10" refX="9" refY="5" '
        'markerWidth="6" markerHeight="6" orient="auto-start-reverse">'
        '<path d="M0,0 L10,5 L0,10 z" fill="var(--neutral-muted)"/>'
        "</marker>"
        "</defs>"
    )


def _render_group_box(group: GraphGroup, box: tuple[float, float, float, float]) -> str:
    x, y, w, h = box
    label_markup = ""
    if group.label:
        label_markup = f'<text x="{x + 4:.1f}" y="{y + 14:.1f}" font-size="10">{html.escape(group.label)}</text>'
    return (
        f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" '
        'fill="none" stroke="var(--neutral-muted)" stroke-dasharray="4,4"/>' + label_markup
    )


def _render_edge(edge: GraphEdge, positions: dict[str, Position]) -> str:
    """Draw ``edge`` in its ORIGINAL ``from`` -> ``to`` direction.

    ``positions`` may come from a layout that internally reversed this
    edge to break a cycle for RANKING purposes only — this function never
    consults that; it always draws from the edge's own ``from_``/``to``
    (spec §7 "Cycles in flowchart/state ... the arrowhead on the original
    direction").
    """
    start = positions[edge.from_]
    end = positions[edge.to]
    dash_attr = ' stroke-dasharray="6,4"' if edge.kind == "dashed" else ""
    stroke_width = 3 if edge.kind == "thick" else 1.5
    label_markup = ""
    if edge.label:
        mid_x, mid_y = (start.x + end.x) / 2, (start.y + end.y) / 2
        label_markup = (
            f'<text x="{mid_x:.1f}" y="{mid_y:.1f}" text-anchor="middle" font-size="10">'
            f"{html.escape(edge.label)}</text>"
        )
    return (
        f'<line x1="{start.x:.1f}" y1="{start.y:.1f}" x2="{end.x:.1f}" y2="{end.y:.1f}" '
        f'stroke="var(--neutral-muted)" stroke-width="{stroke_width}"{dash_attr} '
        'marker-end="url(#graph-arrow)"/>' + label_markup
    )


def _render_node(node: GraphNode, position: Position) -> str:
    status = STATE_TO_STATUS.get(node.state, "neutral") if node.state else "neutral"
    token = _STATUS_TO_TOKEN[status]
    label = node.label if node.label is not None else node.id
    shape = node.shape or "rect"
    cx, cy = position.x, position.y
    half_w, half_h = _NODE_WIDTH / 2, _NODE_HEIGHT / 2

    title_markup = ""
    if node.meta:
        meta_title = ", ".join(f"{key}={value}" for key, value in node.meta.items())
        title_markup = f"<title>{html.escape(meta_title)}</title>"

    common_attrs = (
        f'data-node-id="{html.escape(node.id)}" data-state="{html.escape(node.state or "")}" '
        f'data-status="{status}" fill="var({token})" stroke="var({token})"'
    )

    if shape == "circle":
        radius = min(_NODE_WIDTH, _NODE_HEIGHT) / 2
        shape_markup = f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{radius:.1f}" {common_attrs}/>'
    elif shape == "diamond":
        points = (
            f"{cx:.1f},{cy - half_h:.1f} {cx + half_w:.1f},{cy:.1f} "
            f"{cx:.1f},{cy + half_h:.1f} {cx - half_w:.1f},{cy:.1f}"
        )
        shape_markup = f'<polygon points="{points}" {common_attrs}/>'
    elif shape == "hexagon":
        inset = half_w * 0.3
        points = (
            f"{cx - half_w + inset:.1f},{cy - half_h:.1f} {cx + half_w - inset:.1f},{cy - half_h:.1f} "
            f"{cx + half_w:.1f},{cy:.1f} {cx + half_w - inset:.1f},{cy + half_h:.1f} "
            f"{cx - half_w + inset:.1f},{cy + half_h:.1f} {cx - half_w:.1f},{cy:.1f}"
        )
        shape_markup = f'<polygon points="{points}" {common_attrs}/>'
    elif shape == "subroutine":
        x, y = cx - half_w, cy - half_h
        inset = 6.0
        shape_markup = (
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{_NODE_WIDTH:.1f}" height="{_NODE_HEIGHT:.1f}" {common_attrs}/>'
            f'<line x1="{x + inset:.1f}" y1="{y:.1f}" x2="{x + inset:.1f}" y2="{y + _NODE_HEIGHT:.1f}" '
            f'stroke="var({token})"/>'
            f'<line x1="{x + _NODE_WIDTH - inset:.1f}" y1="{y:.1f}" x2="{x + _NODE_WIDTH - inset:.1f}" '
            f'y2="{y + _NODE_HEIGHT:.1f}" stroke="var({token})"/>'
        )
    elif shape == "rounded":
        x, y = cx - half_w, cy - half_h
        shape_markup = (
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{_NODE_WIDTH:.1f}" height="{_NODE_HEIGHT:.1f}" '
            f'rx="10" ry="10" {common_attrs}/>'
        )
    else:  # "rect" (also the fallback for an unrecognized shape)
        x, y = cx - half_w, cy - half_h
        shape_markup = f'<rect x="{x:.1f}" y="{y:.1f}" width="{_NODE_WIDTH:.1f}" height="{_NODE_HEIGHT:.1f}" {common_attrs}/>'

    text_markup = (
        f'<text x="{cx:.1f}" y="{cy:.1f}" text-anchor="middle" dominant-baseline="middle">'
        f"{html.escape(label)}</text>"
    )
    return f"<g>{title_markup}{shape_markup}{text_markup}</g>"
