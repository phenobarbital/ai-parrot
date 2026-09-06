"""Pure-Python Mermaid codec for the ``Graph`` vocabulary (FEAT-529 Module 3).

Mermaid is a deterministic IMPORT/EXPORT codec only — :class:`~parrot.
outputs.a2ui.graph.models.GraphSpec` stays the single wire vocabulary
(spec §7 "Patterns to Follow"). This module hand-writes a tokenizer/parser
for a deliberately small subset of three mermaid dialects (``flowchart``,
``stateDiagram-v2``, ``sequenceDiagram``); no external parsing dependency
is introduced (spec Non-Goals — no ``mermaid``/``lark``/``pyparsing``, etc.).

Supported subset (spec §3 Module 3):

* **flowchart**: 6 node shapes (``[rect]``, ``(rounded)``, ``{diamond}``,
  ``((circle))``, ``{{hexagon}}``, ``[[subroutine]]``), 3 edge kinds
  (``-->`` solid, ``-.->`` dashed, ``==>`` thick), labels via
  ``-- text -->`` (parse-only) and ``-->|text|`` (canonical emit),
  ``subgraph id [label] ... end`` groups.
* **stateDiagram-v2**: ``[*] --> A`` / ``A --> [*]`` synthetic
  ``__start__``/``__end__`` circle nodes, ``A --> B : label`` transitions,
  ``state "label" as id`` aliases, composite ``state X { ... }`` groups.
* **sequenceDiagram**: ``participant A as Label`` aliases, ``A->>B: msg``
  (solid) / ``A-->>B: msg`` (dashed) messages, in encountered order
  (``GraphSpec.edges`` is already an ordered list — no separate ordering
  field is needed or exists on :class:`~parrot.outputs.a2ui.graph.models.
  GraphEdge`).

``%%`` lines are comments (ignored); ``%%{...`` init directives,
``classDef``/``click``/``style``/``linkStyle``, and sequence
``loop``/``alt``/``par``/``note`` blocks are explicitly OUT of the
supported subset and raise :class:`MermaidCodecError` naming the
offending line (spec Non-Goals).

**Object round-trip, not textual round-trip.** ``from_mermaid(to_mermaid(
spec)) == spec`` (modulo ``accessible_description``/``size``, which have
no mermaid representation) is the contract — NOT that re-serializing
preserves the exact original source text. Two collapsing conventions make
this practical without extra wire fields:

* A node's ``label`` is omitted on export (and re-inferred as ``None`` on
  import) whenever it is exactly the node's ``id`` — the common "no
  explicit label" case.
* A node's ``shape`` is omitted on export (and re-inferred as ``None`` on
  import) whenever it equals the dialect's DEFAULT shape (``rect`` for
  flowchart, ``rounded`` for state) — an explicit shape matching the
  default is indistinguishable from "no shape given" once round-tripped
  through text, which is harmless: both render identically.

``kind="dag"`` reuses the ``flowchart`` mermaid dialect on export (a DAG
IS an acyclic flowchart); ``from_mermaid`` never infers ``kind="dag"``
back from text — that semantic promise cannot be recovered from syntax
alone, so a flowchart-dialect text always parses to ``kind="flowchart"``.
"""

from __future__ import annotations

import re
from typing import Optional

from parrot.outputs.a2ui.catalog.base import CatalogValidationError
from parrot.outputs.a2ui.graph.models import (
    Direction,
    GraphEdge,
    GraphGroup,
    GraphNode,
    GraphSpec,
)

__all__ = ["MermaidCodecError", "from_mermaid", "to_mermaid"]

#: Synthetic node ids for stateDiagram-v2's ``[*]`` start/end pseudo-state.
_START = "__start__"
_END = "__end__"

_RESERVED_LABEL_CHARS = frozenset('[](){}|"#')

#: Constructs explicitly excluded from the supported subset (spec Non-Goals).
#: Checked as a line PREFIX (after stripping leading whitespace).
_UNSUPPORTED_PREFIXES = (
    "classDef",
    "click",
    "style",
    "linkStyle",
    "loop",
    "alt",
    "par",
    "note",
    "Note",
)

_SHAPE_BRACKETS: dict[str, tuple[str, str]] = {
    "circle": ("((", "))"),
    "hexagon": ("{{", "}}"),
    "subroutine": ("[[", "]]"),
    "rect": ("[", "]"),
    "rounded": ("(", ")"),
    "diamond": ("{", "}"),
}
#: Tried in this order so multi-char brackets are matched before their
#: single-char prefixes/suffixes could greedily mismatch them (e.g. a
#: `((circle))` must be tried before `(rounded)` would swallow one pair).
_NODE_SHAPE_ORDER = ("circle", "hexagon", "subroutine", "rect", "rounded", "diamond")
_DEFAULT_FLOWCHART_SHAPE = "rect"
_DEFAULT_STATE_SHAPE = "rounded"

_EDGE_OPS: dict[str, str] = {"solid": "-->", "dashed": "-.->", "thick": "==>"}
_OPS_TO_KIND: dict[str, str] = {v: k for k, v in _EDGE_OPS.items()}
_DEFAULT_EDGE_KIND = "solid"

_IDENT = r"[A-Za-z_][A-Za-z0-9_]*"

_FLOWCHART_HEADER_RE = re.compile(r"^flowchart\s+(TB|LR|BT|RL)$")
_SUBGRAPH_HEADER_RE = re.compile(rf"^(?P<id>{_IDENT})(\s*\[(?P<label>.*)\])?$")
_FLOWCHART_MID_LABEL_RE = re.compile(rf"^(?P<from>{_IDENT})\s+--\s+(?P<label>.+?)\s+-->\s+(?P<to>{_IDENT})$")
_FLOWCHART_EDGE_RE = re.compile(
    rf"^(?P<from>{_IDENT})\s+(?P<op>-->|-\.->|==>)(\|(?P<label>[^|]*)\|)?\s+(?P<to>{_IDENT})$"
)
_FLOWCHART_EDGE_OP_SEARCH_RE = re.compile(r"-->|-\.->|==>")

_STATE_ALIAS_RE = re.compile(rf'^state\s+"(?P<label>.*)"\s+as\s+(?P<id>{_IDENT})$')
_STATE_COMPOSITE_OPEN_RE = re.compile(rf"^state\s+(?P<id>{_IDENT})\s*\{{$")
_STATE_EDGE_RE = re.compile(
    rf"^(?P<from>\[\*\]|{_IDENT})\s*-->\s*(?P<to>\[\*\]|{_IDENT})(\s*:\s*(?P<label>.+))?$"
)
_BARE_IDENT_RE = re.compile(rf"^{_IDENT}$")

_SEQ_PARTICIPANT_RE = re.compile(rf"^participant\s+(?P<id>{_IDENT})(\s+as\s+(?P<label>.+))?$")
_SEQ_MESSAGE_RE = re.compile(rf"^(?P<from>{_IDENT})(?P<arrow>-->>|->>)(?P<to>{_IDENT})(:\s*(?P<label>.+))?$")


class MermaidCodecError(CatalogValidationError):
    """A mermaid source line falls outside the supported subset (spec §2 G4).

    Subclasses :class:`~parrot.outputs.a2ui.catalog.base.CatalogValidationError`
    so the LLM producer's existing validate-retry-degrade loop handles a
    codec failure without any new plumbing.

    Attributes:
        line_no: 1-based source line number of the offending line.
        line: The offending line's raw text.
        reason: Human-readable explanation.
    """

    def __init__(self, line_no: int, line: str, reason: str) -> None:
        super().__init__(f"Mermaid parse error at line {line_no}: {reason} ({line!r})")
        self.line_no = line_no
        self.line = line
        self.reason = reason


def _escape_label(label: str) -> str:
    """Quote ``label`` if it contains any reserved mermaid character."""
    if any(ch in _RESERVED_LABEL_CHARS for ch in label):
        return '"' + label.replace('"', "#quot;") + '"'
    return label


def _unescape_label(token: Optional[str]) -> Optional[str]:
    """Inverse of :func:`_escape_label`; ``None`` passes through unchanged."""
    if token is None:
        return None
    token = token.strip()
    if len(token) >= 2 and token.startswith('"') and token.endswith('"'):
        return token[1:-1].replace("#quot;", '"')
    return token


def _check_unsupported(line_no: int, content: str) -> None:
    stripped = content.strip()
    for keyword in _UNSUPPORTED_PREFIXES:
        # Word-boundary match — `startswith` alone would also flag
        # "participant" (contains "par") or "alt_path" (contains "alt").
        if re.match(rf"^{re.escape(keyword)}(\s|$)", stripped):
            raise MermaidCodecError(
                line_no, content, f"unsupported construct: {keyword!r} is not in the supported subset"
            )


def _prepare_lines(text: str) -> list[tuple[int, str]]:
    """Strip comments/blank lines; reject ``%%{init}``-style directives.

    Returns:
        ``(line_no, content)`` pairs, 1-based, blank lines and plain ``%%``
        comments removed.

    Raises:
        MermaidCodecError: On a ``%%{`` init directive (excluded — spec
            Non-Goals; NOT the same as a plain ``%%`` comment, which is
            silently ignored).
    """
    out: list[tuple[int, str]] = []
    for line_no, raw in enumerate(text.splitlines(), start=1):
        stripped = raw.strip()
        if not stripped:
            continue
        if stripped.startswith("%%{"):
            raise MermaidCodecError(
                line_no, raw, "unsupported construct: '%%{init}' directives are not in the supported subset"
            )
        if stripped.startswith("%%"):
            continue
        out.append((line_no, raw.rstrip()))
    return out


# ---------------------------------------------------------------------------
# to_mermaid
# ---------------------------------------------------------------------------


def to_mermaid(spec: GraphSpec) -> str:
    """Emit ``spec`` as canonical mermaid source text.

    Deterministic: the same spec always produces the same text (stable,
    input-preserving order for nodes/edges/groups).

    Args:
        spec: The graph to serialize.

    Returns:
        Mermaid source text (trailing newline included).
    """
    if spec.kind == "sequence":
        return _emit_sequence(spec)
    if spec.kind == "state":
        return _emit_state(spec)
    # "flowchart" and "dag" share the flowchart dialect (a DAG is an
    # acyclic flowchart) — see this module's docstring.
    return _emit_flowchart(spec)


def _emit_flowchart_node_decl(node: GraphNode) -> str:
    shape = node.shape or _DEFAULT_FLOWCHART_SHAPE
    open_bracket, close_bracket = _SHAPE_BRACKETS[shape]
    label_text = node.label if node.label is not None else node.id
    return f"{node.id}{open_bracket}{_escape_label(label_text)}{close_bracket}"


def _emit_flowchart_edge(edge: GraphEdge) -> str:
    op = _EDGE_OPS[edge.kind or _DEFAULT_EDGE_KIND]
    if edge.label:
        return f"{edge.from_} {op}|{_escape_label(edge.label)}| {edge.to}"
    return f"{edge.from_} {op} {edge.to}"


def _emit_flowchart(spec: GraphSpec) -> str:
    # Every node is declared ONCE at top level, in input order (spec §3
    # Module 3: "nodes declared once, in input order") — a subgraph block
    # only BARE-references its members' ids afterwards. This is what keeps
    # `from_mermaid(to_mermaid(spec))`'s `nodes` list in the SAME order as
    # `spec.nodes`: declaring (a subset of) nodes only inside the subgraph
    # block would reorder them to wherever their group happens to sort.
    lines = [f"flowchart {spec.direction}"]

    for node in spec.nodes:
        lines.append(_emit_flowchart_node_decl(node))

    for group in spec.groups or []:
        header = f"subgraph {group.id}"
        if group.label and group.label != group.id:
            header += f" [{_escape_label(group.label)}]"
        lines.append(header)
        for member_id in group.nodes:
            lines.append(member_id)
        lines.append("end")

    for edge in spec.edges:
        lines.append(_emit_flowchart_edge(edge))

    return "\n".join(lines) + "\n"


def _emit_state(spec: GraphSpec) -> str:
    # Same "declare once at top, group blocks bare-reference members"
    # ordering discipline as `_emit_flowchart` (see its comment) — keeps
    # `nodes` list order stable through a round-trip. `__start__`/`__end__`
    # have no top-level declaration (they exist only via `[*]` edge
    # endpoints), so they inevitably land at the END of the parsed node
    # order regardless of their position in `spec.nodes`.
    lines = ["stateDiagram-v2"]

    for node in spec.nodes:
        if node.id in (_START, _END):
            continue
        if node.label and node.label != node.id:
            lines.append(f'state "{_escape_label(node.label)}" as {node.id}')

    for group in spec.groups or []:
        lines.append(f"state {group.id} {{")
        for member_id in group.nodes:
            lines.append(f"    {member_id}")
        lines.append("}")

    for edge in spec.edges:
        from_token = "[*]" if edge.from_ == _START else edge.from_
        to_token = "[*]" if edge.to == _END else edge.to
        if edge.label:
            lines.append(f"{from_token} --> {to_token} : {edge.label}")
        else:
            lines.append(f"{from_token} --> {to_token}")

    return "\n".join(lines) + "\n"


def _emit_sequence(spec: GraphSpec) -> str:
    lines = ["sequenceDiagram"]
    for node in spec.nodes:
        if node.label and node.label != node.id:
            lines.append(f"participant {node.id} as {_escape_label(node.label)}")
        else:
            lines.append(f"participant {node.id}")

    for edge in spec.edges:
        arrow = "-->>" if edge.kind == "dashed" else "->>"
        if edge.label:
            lines.append(f"{edge.from_}{arrow}{edge.to}: {edge.label}")
        else:
            lines.append(f"{edge.from_}{arrow}{edge.to}")

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# from_mermaid
# ---------------------------------------------------------------------------


def from_mermaid(text: str) -> GraphSpec:
    """Parse mermaid source text into a :class:`GraphSpec`.

    Args:
        text: Mermaid source (flowchart / stateDiagram-v2 / sequenceDiagram).

    Returns:
        The parsed :class:`GraphSpec` (``accessible_description``/``size``
        stay at their defaults — mermaid has no representation for them).

    Raises:
        MermaidCodecError: For an empty source, an unrecognized diagram
            header, or any line outside the supported subset — names the
            offending line and a reason.
    """
    lines = _prepare_lines(text)
    if not lines:
        raise MermaidCodecError(1, "", "empty mermaid source")

    header_no, header = lines[0]
    stripped_header = header.strip()
    if stripped_header.startswith("flowchart"):
        return _parse_flowchart(lines)
    if stripped_header.startswith("stateDiagram-v2"):
        return _parse_state(lines)
    if stripped_header.startswith("sequenceDiagram"):
        return _parse_sequence(lines)
    raise MermaidCodecError(header_no, header, "unrecognized or unsupported diagram header")


def _parse_flowchart_node_decl(stripped: str) -> Optional[GraphNode]:
    for shape in _NODE_SHAPE_ORDER:
        open_bracket, close_bracket = _SHAPE_BRACKETS[shape]
        pattern = re.compile(
            rf"^(?P<id>{_IDENT}){re.escape(open_bracket)}(?P<label>.*){re.escape(close_bracket)}$"
        )
        match = pattern.match(stripped)
        if match:
            node_id = match.group("id")
            label = _unescape_label(match.group("label"))
            return GraphNode(
                id=node_id,
                label=None if label == node_id else label,
                shape=None if shape == _DEFAULT_FLOWCHART_SHAPE else shape,
            )
    if _BARE_IDENT_RE.match(stripped):
        return GraphNode(id=stripped)
    return None


def _parse_flowchart_edge_line(line_no: int, content: str, stripped: str) -> GraphEdge:
    mid_match = _FLOWCHART_MID_LABEL_RE.match(stripped)
    if mid_match:
        return GraphEdge(
            **{
                "from": mid_match.group("from"),
                "to": mid_match.group("to"),
                "label": _unescape_label(mid_match.group("label")),
                "kind": "solid",
            }
        )

    match = _FLOWCHART_EDGE_RE.match(stripped)
    if match:
        return GraphEdge(
            **{
                "from": match.group("from"),
                "to": match.group("to"),
                "label": _unescape_label(match.group("label")),
                "kind": _OPS_TO_KIND[match.group("op")],
            }
        )

    raise MermaidCodecError(line_no, content, "malformed flowchart edge declaration")


def _parse_flowchart(lines: list[tuple[int, str]]) -> GraphSpec:
    header_no, header = lines[0]
    direction_match = _FLOWCHART_HEADER_RE.match(header.strip())
    if not direction_match:
        raise MermaidCodecError(header_no, header, "flowchart header must be 'flowchart <TB|LR|BT|RL>'")
    direction: Direction = direction_match.group(1)  # type: ignore[assignment]

    nodes: dict[str, GraphNode] = {}
    node_order: list[str] = []
    edges: list[GraphEdge] = []
    groups: list[GraphGroup] = []

    current_group_id: Optional[str] = None
    current_group_label: Optional[str] = None
    current_group_members: Optional[list[str]] = None

    def _register(node: GraphNode) -> None:
        if node.id not in nodes:
            nodes[node.id] = node
            node_order.append(node.id)
        if current_group_members is not None:
            current_group_members.append(node.id)

    for line_no, content in lines[1:]:
        stripped = content.strip()
        _check_unsupported(line_no, content)

        if stripped.startswith("subgraph"):
            if current_group_members is not None:
                raise MermaidCodecError(line_no, content, "nested 'subgraph' is not supported")
            rest = stripped[len("subgraph") :].strip()
            match = _SUBGRAPH_HEADER_RE.match(rest)
            if not match:
                raise MermaidCodecError(line_no, content, "malformed subgraph header")
            current_group_id = match.group("id")
            current_group_label = _unescape_label(match.group("label"))
            current_group_members = []
            continue

        if stripped == "end":
            if current_group_members is None:
                raise MermaidCodecError(line_no, content, "'end' with no open subgraph")
            groups.append(
                GraphGroup(id=current_group_id, label=current_group_label, nodes=list(current_group_members))
            )
            current_group_id = None
            current_group_label = None
            current_group_members = None
            continue

        if _FLOWCHART_EDGE_OP_SEARCH_RE.search(stripped):
            edges.append(_parse_flowchart_edge_line(line_no, content, stripped))
            continue

        node = _parse_flowchart_node_decl(stripped)
        if node is None:
            raise MermaidCodecError(line_no, content, "unrecognized flowchart statement")
        _register(node)

    if current_group_members is not None:
        last_no, last_line = lines[-1]
        raise MermaidCodecError(last_no, last_line, "subgraph missing closing 'end'")

    ordered_nodes = [nodes[node_id] for node_id in node_order]
    return GraphSpec(kind="flowchart", direction=direction, nodes=ordered_nodes, edges=edges, groups=groups or None)


def _parse_state(lines: list[tuple[int, str]]) -> GraphSpec:
    nodes: dict[str, GraphNode] = {}
    node_order: list[str] = []
    edges: list[GraphEdge] = []
    groups: list[GraphGroup] = []

    current_group_id: Optional[str] = None
    current_group_members: Optional[list[str]] = None

    def _ensure_node(node_id: str, label: Optional[str] = None, shape: Optional[str] = None) -> None:
        if node_id not in nodes:
            # Synthetic start/end states are always circles (spec §2 Data
            # Models) — there is no textual declaration for them to carry a
            # shape, so it is filled in here, at first reference.
            if node_id in (_START, _END) and shape is None:
                shape = "circle"
            nodes[node_id] = GraphNode(id=node_id, label=label, shape=shape)
            node_order.append(node_id)
        elif label is not None:
            nodes[node_id] = nodes[node_id].model_copy(update={"label": label})
        if current_group_members is not None and node_id not in (_START, _END):
            current_group_members.append(node_id)

    def _reject_reserved(line_no: int, content: str, *ids: str) -> None:
        for candidate in ids:
            if candidate in (_START, _END):
                raise MermaidCodecError(
                    line_no, content, f"{candidate!r} is reserved for the synthetic start/end state"
                )

    for line_no, content in lines[1:]:
        stripped = content.strip()
        _check_unsupported(line_no, content)

        alias_match = _STATE_ALIAS_RE.match(stripped)
        if alias_match:
            node_id = alias_match.group("id")
            _reject_reserved(line_no, content, node_id)
            _ensure_node(node_id, label=_unescape_label(alias_match.group("label")))
            continue

        composite_match = _STATE_COMPOSITE_OPEN_RE.match(stripped)
        if composite_match:
            if current_group_members is not None:
                raise MermaidCodecError(line_no, content, "nested composite state is not supported")
            current_group_id = composite_match.group("id")
            current_group_members = []
            continue

        if stripped == "}":
            if current_group_members is None:
                raise MermaidCodecError(line_no, content, "'}' with no open composite state")
            groups.append(GraphGroup(id=current_group_id, nodes=list(current_group_members)))
            current_group_id = None
            current_group_members = None
            continue

        edge_match = _STATE_EDGE_RE.match(stripped)
        if edge_match:
            from_raw = edge_match.group("from")
            to_raw = edge_match.group("to")
            _reject_reserved(line_no, content, from_raw, to_raw)
            from_id = _START if from_raw == "[*]" else from_raw
            to_id = _END if to_raw == "[*]" else to_raw
            _ensure_node(from_id)
            _ensure_node(to_id)
            edges.append(
                GraphEdge(**{"from": from_id, "to": to_id, "label": edge_match.group("label")})
            )
            continue

        bare_match = _BARE_IDENT_RE.match(stripped)
        if bare_match:
            _reject_reserved(line_no, content, stripped)
            _ensure_node(stripped)
            continue

        raise MermaidCodecError(line_no, content, "unrecognized stateDiagram-v2 statement")

    if current_group_members is not None:
        last_no, last_line = lines[-1]
        raise MermaidCodecError(last_no, last_line, "composite state missing closing '}'")

    # __start__/__end__ (if referenced) were already registered by
    # `_ensure_node` the first time an edge mentioned `[*]` — they have no
    # top-level textual declaration of their own to parse separately.
    ordered_nodes = [nodes[node_id] for node_id in node_order]
    return GraphSpec(kind="state", direction="TB", nodes=ordered_nodes, edges=edges, groups=groups or None)


def _parse_sequence(lines: list[tuple[int, str]]) -> GraphSpec:
    nodes: dict[str, GraphNode] = {}
    node_order: list[str] = []
    edges: list[GraphEdge] = []

    def _ensure_node(node_id: str, label: Optional[str] = None) -> None:
        if node_id not in nodes:
            nodes[node_id] = GraphNode(id=node_id, label=label)
            node_order.append(node_id)
        elif label is not None:
            nodes[node_id] = nodes[node_id].model_copy(update={"label": label})

    for line_no, content in lines[1:]:
        stripped = content.strip()
        _check_unsupported(line_no, content)

        participant_match = _SEQ_PARTICIPANT_RE.match(stripped)
        if participant_match:
            node_id = participant_match.group("id")
            label = _unescape_label(participant_match.group("label"))
            _ensure_node(node_id, label=label)
            continue

        message_match = _SEQ_MESSAGE_RE.match(stripped)
        if message_match:
            from_id = message_match.group("from")
            to_id = message_match.group("to")
            _ensure_node(from_id)
            _ensure_node(to_id)
            kind = "dashed" if message_match.group("arrow") == "-->>" else "solid"
            edges.append(
                GraphEdge(
                    **{
                        "from": from_id,
                        "to": to_id,
                        "label": message_match.group("label"),
                        "kind": kind,
                    }
                )
            )
            continue

        raise MermaidCodecError(line_no, content, "unrecognized sequenceDiagram statement")

    ordered_nodes = [nodes[node_id] for node_id in node_order]
    return GraphSpec(kind="sequence", direction="TB", nodes=ordered_nodes, edges=edges)
