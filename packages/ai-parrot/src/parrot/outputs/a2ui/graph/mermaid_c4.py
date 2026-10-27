"""Mermaid C4 dialect codec for ``GraphSpec(kind=\"c4\")`` (FEAT-754, spec §3 Module 2).

Dependency-free like :mod:`.mermaid`. Emits C4Context / C4Container / C4Component / C4Dynamic
source; the supported subset and the lossy fields are documented in ``docs/outputs/a2ui-v1.md``.
"""

from __future__ import annotations

from typing import Optional

from .mermaid import MermaidCodecError, _escape_label, _IDENT  # noqa: F401
from .models import GraphEdge, GraphGroup, GraphNode, GraphSpec

__all__ = ["C4_LOSSY_FIELDS", "to_mermaid_c4"]

#: GraphSpec fields (dotted for nested) with no Mermaid C4 representation — the "modulo" set of the
#: round-trip contract. Dotted paths, NOT a pydantic ``exclude`` argument.
C4_LOSSY_FIELDS: frozenset[str] = frozenset(
    {
        "accessible_description",
        "size",
        "direction",
        "selection",
        "data",
        "layout.engine",
        "layout.rank_sep",
        "layout.node_sep",
        "layout.positions",
        "nodes.shape",
        "nodes.state",
        "nodes.icon",
        "nodes.meta",
        "nodes.group",
        "edges.kind",
        "edges.condition",
    }
)

_LEVEL_HEADER: dict[str, str] = {
    "context": "C4Context",
    "container": "C4Container",
    "component": "C4Component",
    "dynamic": "C4Dynamic",
}
_ELEMENT_MACRO: dict[str, str] = {
    "person": "Person",
    "person_ext": "Person_Ext",
    "system": "System",
    "system_ext": "System_Ext",
    "system_db": "SystemDb",
    "system_db_ext": "SystemDb_Ext",
    "system_queue": "SystemQueue",
    "system_queue_ext": "SystemQueue_Ext",
    "container": "Container",
    "container_ext": "Container_Ext",
    "container_db": "ContainerDb",
    "container_db_ext": "ContainerDb_Ext",
    "container_queue": "ContainerQueue",
    "container_queue_ext": "ContainerQueue_Ext",
    "component": "Component",
    "component_ext": "Component_Ext",
    "component_db": "ComponentDb",
    "component_db_ext": "ComponentDb_Ext",
    "component_queue": "ComponentQueue",
    "component_queue_ext": "ComponentQueue_Ext",
}
_MACRO_ELEMENT: dict[str, str] = {macro: c4 for c4, macro in _ELEMENT_MACRO.items()}
_BOUNDARY_MACRO: dict[Optional[str], str] = {
    "enterprise": "Enterprise_Boundary",
    "system": "System_Boundary",
    "container": "Container_Boundary",
    "generic": "Boundary",
    None: "Boundary",
}
_REL_MACRO: dict[tuple[bool, Optional[str]], str] = {
    (True, None): "BiRel",
    (False, None): "Rel",
    (False, "back"): "Rel_Back",
    (False, "up"): "Rel_U",
    (False, "down"): "Rel_D",
    (False, "left"): "Rel_L",
    (False, "right"): "Rel_R",
}
_INDENT = "    "


def _quote(value: Optional[str]) -> str:
    """Double-quote a macro string argument, escaping ``\"`` as ``#quot;``."""
    return '"' + (value or "").replace('"', "#quot;") + '"'


def _emit_element(node: GraphNode, depth: int) -> str:
    """Emit one element macro line at ``depth`` (4-space indent per level)."""
    macro = _ELEMENT_MACRO[node.c4_type or ""]
    label = node.label or node.id
    args = [node.id, _quote(label)]
    if node.c4_type and node.c4_type.startswith(("person", "system")):
        if node.description is not None:
            args.append(_quote(node.description))
    elif node.description is not None:
        args.extend([_quote(node.technology), _quote(node.description)])
    elif node.technology is not None:
        args.append(_quote(node.technology))
    return f"{_INDENT * depth}{macro}({', '.join(args)})"


def _emit_boundary_open(group: GraphGroup, depth: int) -> str:
    """Emit a ``<Macro>(id, \"label\") {`` line for a boundary."""
    return f'{_INDENT * depth}{_BOUNDARY_MACRO[group.c4_type]}({group.id}, {_quote(group.label or group.id)}) {{'


def _emit_rel(edge: GraphEdge, index: int, dynamic: bool) -> str:
    """Emit one relationship line using ``index`` for a dynamic graph."""
    args = [edge.from_, edge.to, _quote(edge.label)]
    if edge.technology is not None:
        args.append(_quote(edge.technology))
    if dynamic:
        args.insert(0, _quote(str(index)))
        return f"RelIndex({', '.join(args)})"
    macro = _REL_MACRO[(bool(edge.bidirectional), edge.hint)]
    return f"{macro}({', '.join(args)})"


def to_mermaid_c4(spec: GraphSpec) -> str:
    """Emit canonical Mermaid C4 source for a ``kind=\"c4\"`` spec (trailing newline included).

    Raises:
        ValueError: if ``spec.kind != \"c4\"``.
    """
    if spec.kind != "c4":
        raise ValueError(f"to_mermaid_c4 requires kind='c4', got {spec.kind!r}")

    lines: list[str] = [_LEVEL_HEADER[spec.level or ""]]
    if spec.title and spec.title.strip():
        lines.append(f"title {spec.title.rstrip()}")

    groups = spec.groups or []
    node_by_id = {node.id: node for node in spec.nodes}
    grouped_node_ids = {node_id for group in groups for node_id in group.nodes}
    children_by_parent: dict[Optional[str], list[GraphGroup]] = {}
    for group in groups:
        children_by_parent.setdefault(group.parent, []).append(group)

    for node in spec.nodes:
        if node.id not in grouped_node_ids:
            lines.append(_emit_element(node, 0))

    def emit_boundary(group: GraphGroup, depth: int) -> None:
        lines.append(_emit_boundary_open(group, depth))
        for node_id in group.nodes:
            lines.append(_emit_element(node_by_id[node_id], depth + 1))
        for child in children_by_parent.get(group.id, []):
            emit_boundary(child, depth + 1)
        lines.append(f"{_INDENT * depth}}}")

    for group in children_by_parent.get(None, []):
        emit_boundary(group, 0)

    dynamic = spec.level == "dynamic"
    for index, edge in enumerate(spec.edges, start=1):
        lines.append(_emit_rel(edge, index, dynamic))

    if spec.layout and spec.layout.shape_in_row is not None and spec.layout.boundary_in_row is not None:
        lines.append(
            "UpdateLayoutConfig("
            f'$c4ShapeInRow="{spec.layout.shape_in_row}", '
            f'$c4BoundaryInRow="{spec.layout.boundary_in_row}")'
        )
    return "\n".join(lines) + "\n"
