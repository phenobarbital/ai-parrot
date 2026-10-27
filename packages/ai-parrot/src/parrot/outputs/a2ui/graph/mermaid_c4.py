"""Mermaid C4 dialect codec for ``GraphSpec(kind=\"c4\")`` (FEAT-754, spec §3 Module 2).

Dependency-free like :mod:`.mermaid`. Emits C4Context / C4Container / C4Component / C4Dynamic
source; the supported subset and the lossy fields are documented in ``docs/outputs/a2ui-v1.md``.
"""

from __future__ import annotations

import re
from typing import Optional

from .mermaid import MermaidCodecError, _escape_label, _IDENT, _prepare_lines, _unescape_label  # noqa: F401
from .models import GraphEdge, GraphGroup, GraphLayout, GraphNode, GraphSpec

__all__ = ["C4_LOSSY_FIELDS", "from_mermaid_c4", "to_mermaid_c4"]

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
_MACRO_RE = re.compile(r"^(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*\((?P<args>.*)\)\s*(?P<open>\{)?$")
_BOUNDARY_BY_MACRO: dict[str, Optional[str]] = {macro: c4_type for c4_type, macro in _BOUNDARY_MACRO.items()}
_REL_BY_MACRO: dict[str, tuple[bool, Optional[str]]] = {macro: value for value, macro in _REL_MACRO.items()}
_REL_BY_MACRO.update(
    {
        "Rel_Up": (False, "up"),
        "Rel_Down": (False, "down"),
        "Rel_Left": (False, "left"),
        "Rel_Right": (False, "right"),
    }
)


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
    return f"{_INDENT * depth}{_BOUNDARY_MACRO[group.c4_type]}({group.id}, {_quote(group.label or group.id)}) {{"


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


def _split_macro_args(line_no: int, content: str, raw: str) -> list[str]:
    """Split a macro argument list on top-level commas, respecting double quotes.

    Args:
        line_no: One-based source line number.
        content: The text inside a macro's parentheses.
        raw: The original source line, retained for parse errors.

    Returns:
        Unescaped, stripped macro arguments.

    Raises:
        MermaidCodecError: If a double-quoted argument is not closed.
    """
    args: list[str] = []
    current: list[str] = []
    in_quote = False
    for char in content:
        if char == '"':
            in_quote = not in_quote
            current.append(char)
        elif char == "," and not in_quote:
            args.append(_unescape_label("".join(current).strip()) or "")
            current = []
        else:
            current.append(char)
    if in_quote:
        raise MermaidCodecError(line_no, raw, "unbalanced quoted macro argument")
    args.append(_unescape_label("".join(current).strip()) or "")
    return args


def _optional(value: str) -> Optional[str]:
    """Collapse an empty macro argument to ``None``."""
    return value or None


def _require_identifier(line_no: int, raw: str, value: str) -> str:
    """Return ``value`` when it is a valid Mermaid C4 identifier."""
    if not re.fullmatch(_IDENT, value):
        raise MermaidCodecError(line_no, raw, f"invalid identifier: {value!r}")
    return value


def from_mermaid_c4(text: str) -> GraphSpec:
    """Parse Mermaid C4 source into a ``kind=\"c4\"`` :class:`GraphSpec`.

    Raises:
        MermaidCodecError: For source outside the supported C4 subset, always
            identifying the source line which caused the error.
    """
    lines = _prepare_lines(text)
    if not lines:
        raise MermaidCodecError(1, "", "empty mermaid source")

    header_no, header = lines[0]
    level_by_header = {value: key for key, value in _LEVEL_HEADER.items()}
    level = level_by_header.get(header.strip())
    if level is None:
        raise MermaidCodecError(header_no, header, "unrecognized or unsupported diagram header")

    title: Optional[str] = None
    nodes: list[GraphNode] = []
    groups: list[GraphGroup] = []
    groups_by_id: dict[str, GraphGroup] = {}
    edges: list[GraphEdge] = []
    indexed_edges: list[tuple[int, int, GraphEdge]] = []
    plain_dynamic_edges: list[GraphEdge] = []
    stack: list[str] = []
    layout: Optional[GraphLayout] = None

    for line_no, raw in lines[1:]:
        stripped = raw.strip()
        if stripped.startswith("title ") and not nodes and not groups and not edges and not indexed_edges:
            title = _optional(stripped[6:].rstrip())
            continue
        if stripped == "}":
            if not stack:
                raise MermaidCodecError(line_no, raw, "unbalanced boundary block")
            stack.pop()
            continue

        match = _MACRO_RE.match(stripped)
        if match is None:
            raise MermaidCodecError(line_no, raw, "unknown or unsupported macro")
        macro = match.group("name")
        args_content = match.group("args")
        args = _split_macro_args(line_no, args_content, raw)
        if any(argument.startswith(("$sprite=", "$tags=", "$link=")) for argument in args):
            raise MermaidCodecError(line_no, raw, "sprite/tags/link arguments are not in the supported subset")
        if macro in {"UpdateElementStyle", "UpdateRelStyle"}:
            raise MermaidCodecError(line_no, raw, "styling is not in the supported subset")
        if macro in {"Deployment_Node", "Node"}:
            raise MermaidCodecError(line_no, raw, "unknown or unsupported macro")

        is_open = match.group("open") is not None
        if macro in _BOUNDARY_BY_MACRO:
            if not is_open or not 1 <= len(args) <= 2:
                raise MermaidCodecError(line_no, raw, "boundary macro has invalid arity")
            group_id = _require_identifier(line_no, raw, args[0])
            group = GraphGroup(
                id=group_id,
                label=None if len(args) < 2 or args[1] == group_id else _optional(args[1]),
                nodes=[],
                parent=stack[-1] if stack else None,
                c4Type=_BOUNDARY_BY_MACRO[macro] or "generic",
            )
            groups.append(group)
            groups_by_id[group_id] = group
            stack.append(group_id)
            continue
        if is_open:
            raise MermaidCodecError(line_no, raw, "unknown or unsupported macro")

        if macro in _MACRO_ELEMENT:
            c4_type = _MACRO_ELEMENT[macro]
            maximum = 3 if c4_type.startswith(("person", "system")) else 4
            if not 1 <= len(args) <= maximum:
                raise MermaidCodecError(line_no, raw, "element macro has invalid arity")
            node_id = _require_identifier(line_no, raw, args[0])
            label = _optional(args[1]) if len(args) > 1 else None
            node_values: dict[str, Optional[str]] = {
                "id": node_id,
                "label": None if label == node_id else label,
                "technology": None,
                "description": None,
            }
            if c4_type.startswith(("person", "system")):
                if len(args) > 2:
                    node_values["description"] = _optional(args[2])
            else:
                if len(args) > 2:
                    node_values["technology"] = _optional(args[2])
                if len(args) > 3:
                    node_values["description"] = _optional(args[3])
            nodes.append(GraphNode(c4Type=c4_type, **node_values))
            if stack:
                groups_by_id[stack[-1]].nodes.append(node_id)
            continue

        if macro == "UpdateLayoutConfig":
            if len(args) != 2:
                raise MermaidCodecError(line_no, raw, "UpdateLayoutConfig has invalid arity")
            shape_match = re.fullmatch(r'\$c4ShapeInRow="?(\d+)"?', args[0])
            boundary_match = re.fullmatch(r'\$c4BoundaryInRow="?(\d+)"?', args[1])
            if shape_match is None or boundary_match is None:
                raise MermaidCodecError(line_no, raw, "UpdateLayoutConfig has unsupported arguments")
            layout = GraphLayout(shapeInRow=int(shape_match.group(1)), boundaryInRow=int(boundary_match.group(1)))
            continue

        if macro == "RelIndex":
            if level != "dynamic" or not 4 <= len(args) <= 5:
                raise MermaidCodecError(line_no, raw, "RelIndex has invalid arity")
            if not args[0].isdigit() or int(args[0]) < 1:
                raise MermaidCodecError(line_no, raw, "RelIndex requires a positive integer index")
            source = _require_identifier(line_no, raw, args[1])
            target = _require_identifier(line_no, raw, args[2])
            indexed_edges.append(
                (
                    int(args[0]),
                    line_no,
                    GraphEdge(
                        **{
                            "from": source,
                            "to": target,
                            "label": _optional(args[3]),
                            "technology": _optional(args[4]) if len(args) == 5 else None,
                        }
                    ),
                )
            )
            continue

        if macro in _REL_BY_MACRO:
            if not 3 <= len(args) <= 4:
                raise MermaidCodecError(line_no, raw, "relationship macro has invalid arity")
            if level == "dynamic" and macro != "Rel":
                raise MermaidCodecError(line_no, raw, "C4Dynamic only supports Rel or RelIndex")
            source = _require_identifier(line_no, raw, args[0])
            target = _require_identifier(line_no, raw, args[1])
            bidirectional, hint = _REL_BY_MACRO[macro]
            edge = GraphEdge(
                **{
                    "from": source,
                    "to": target,
                    "label": _optional(args[2]),
                    "technology": _optional(args[3]) if len(args) == 4 else None,
                    "bidirectional": bidirectional or None,
                    "hint": hint,
                }
            )
            if level == "dynamic":
                plain_dynamic_edges.append(edge)
            else:
                edges.append(edge)
            continue
        raise MermaidCodecError(line_no, raw, "unknown or unsupported macro")

    if stack:
        raise MermaidCodecError(lines[-1][0], lines[-1][1], "unbalanced boundary block")
    if level == "dynamic":
        indexed_edges.sort(key=lambda item: item[0])
        indices = [index for index, _, _ in indexed_edges]
        if indices != list(range(1, len(indices) + 1)):
            error_line = indexed_edges[-1][1] if indexed_edges else lines[0][0]
            raise MermaidCodecError(error_line, "", "RelIndex values must be unique and contiguous from 1")
        edges = [edge for _, _, edge in indexed_edges] + plain_dynamic_edges
    return GraphSpec(kind="c4", level=level, direction="TB", title=title, nodes=nodes, edges=edges, groups=groups or None, layout=layout)
