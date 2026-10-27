"""Pure Mermaid-source utilities for the ``MermaidDiagram`` component (FEAT-753, Module 1).

Detects the diagram type, strips ``%%{ … }%%`` directives (builder lane), checks a source for the
wire (every origin, called from ``catalog.validate_envelope``) and bridges the flowchart / state /
sequence subset to a typed ``GraphSpec``. Never draws, never does I/O. MUST NOT import the
``parrot.outputs.a2ui.catalog`` package (it imports this module) — only ``catalog.base``.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from typing import Final, Literal, TypedDict, get_args

from parrot.outputs.a2ui.catalog.base import (
    MERMAID_DIAGRAM_TYPE_MISMATCH,
    MERMAID_SOURCE_TOO_LARGE,
    MERMAID_UNSAFE_DIRECTIVE,
    MERMAID_UNSAFE_INTERACTION,
)
from parrot.outputs.a2ui.graph.mermaid import from_mermaid
from parrot.outputs.a2ui.graph.models import GraphSpec

__all__ = [
    "MERMAID_DIAGRAM_ROUTE_KEY",
    "MERMAID_DIAGRAM_ROUTE_UTTERANCES",
    "MERMAID_DIAGRAM_TYPES",
    "MERMAID_SOURCE_MAX_BYTES",
    "MERMAID_THEMES",
    "MermaidDiagramType",
    "MermaidSourceIssue",
    "check_mermaid_source",
    "detect_diagram_type",
    "graph_spec_from_mermaid_source",
    "iter_statements",
    "normalize_mermaid_source",
]

MermaidDiagramType = Literal[
    "flowchart",
    "sequence",
    "class",
    "state",
    "er",
    "journey",
    "gantt",
    "pie",
    "quadrant",
    "requirement",
    "gitGraph",
    "c4",
    "mindmap",
    "timeline",
    "zenuml",
    "sankey",
    "xychart",
    "block",
    "packet",
    "kanban",
    "architecture",
    "radar",
    "treemap",
    "unknown",
]
MERMAID_DIAGRAM_TYPES: Final[tuple[str, ...]] = get_args(MermaidDiagramType)
MERMAID_SOURCE_MAX_BYTES: Final[int] = 32_768
MERMAID_THEMES: Final[tuple[str, ...]] = ("default", "neutral", "dark", "forest", "base")
MERMAID_DIAGRAM_ROUTE_KEY: Final[str] = "a2ui:MermaidDiagram"
MERMAID_DIAGRAM_ROUTE_UTTERANCES: Final[tuple[str, ...]] = (
    "as a diagram",
    "draw this as a diagram",
    "sequence diagram of",
    "show the flow as a sequence diagram",
    "class diagram of",
    "ER diagram of the data model",
    "gantt chart of the plan",
    "draw a mindmap",
    "diagrama de secuencia de",
    "muéstralo como diagrama",
    "diagrama de clases de",
    "diagrama entidad-relación",
    "haz un diagrama de flujo",
    "dibuja un mapa mental",
)

#: header keyword (first token of the first statement) -> diagram type
_HEADER_TO_TYPE: Final[dict[str, str]] = {
    "flowchart": "flowchart",
    "graph": "flowchart",
    "sequenceDiagram": "sequence",
    "classDiagram": "class",
    "classDiagram-v2": "class",
    "stateDiagram": "state",
    "stateDiagram-v2": "state",
    "erDiagram": "er",
    "journey": "journey",
    "gantt": "gantt",
    "pie": "pie",
    "quadrantChart": "quadrant",
    "requirementDiagram": "requirement",
    "gitGraph": "gitGraph",
    "C4Context": "c4",
    "C4Container": "c4",
    "C4Component": "c4",
    "C4Dynamic": "c4",
    "C4Deployment": "c4",
    "mindmap": "mindmap",
    "timeline": "timeline",
    "zenuml": "zenuml",
    "sankey-beta": "sankey",
    "xychart-beta": "xychart",
    "block-beta": "block",
    "packet-beta": "packet",
    "kanban": "kanban",
    "architecture-beta": "architecture",
    "radar-beta": "radar",
    "treemap-beta": "treemap",
}
_INTERACTION_KEYWORDS: Final[frozenset[str]] = frozenset({"click", "link", "links", "callback"})
_UNSAFE_ANYWHERE = re.compile(r"javascript:|<script", re.IGNORECASE)
_DIRECTIVE_RE = re.compile(r"^[ \t]*%%\{.*?\}%%[ \t]*\n?", re.DOTALL | re.MULTILINE)
_INLINE_DIRECTIVE_RE = re.compile(r"%%\{.*?\}%%", re.DOTALL)
_THEME_RE = re.compile(r"""["']?theme["']?\s*:\s*["']?(\w+)""")
_OPEN_BRACKETS: Final[str] = "[({"
_CLOSE_BRACKETS: Final[str] = "])}"


class MermaidSourceIssue(TypedDict):
    """One validation finding: ``code`` (a ``catalog.base`` constant), ``message``, ``line_no`` (1-based or None)."""

    code: str
    message: str
    line_no: int | None


_INVISIBLE_RE = re.compile("[\u200b-\u200d\u2060\ufeff]")
_TITLE_KEY_RE = re.compile(r"^title\s*:")


def _split_lines(source: str) -> list[str]:
    """Split on any line ending (``\\r\\n``, ``\\r``, ``\\n``), dropping zero-width characters.

    Zero-width characters (BOM, ZWSP, ZWNJ, ZWJ, word joiner) are removed so that ``str.strip`` and the
    keyword match see the same token boundaries as Mermaid's own lexer (fail closed).
    """
    text = _INVISIBLE_RE.sub("", source)
    return text.replace("\r\n", "\n").replace("\r", "\n").split("\n")


def _front_matter_span(lines: list[str]) -> tuple[int, int] | None:
    """Return the 0-based ``(start, end)`` indexes of a leading ``---`` block, or ``None``."""
    start = next((i for i, line in enumerate(lines) if line.strip()), None)
    if start is None or lines[start].strip() != "---":
        return None
    for idx in range(start + 1, len(lines)):
        if lines[idx].strip() == "---":
            return start, idx
    return None


def _is_ambiguous(line: str) -> bool:
    """True when ``line`` ends inside a quote or an open bracket (quote/bracket rules differ per diagram)."""
    in_quote = False
    escape = False
    depth = 0
    for ch in line:
        if in_quote:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_quote = False
        elif ch == '"':
            in_quote = True
        elif ch in _OPEN_BRACKETS:
            depth += 1
        elif ch in _CLOSE_BRACKETS:
            depth = max(0, depth - 1)
    return in_quote or depth > 0


def _split_statements(line: str) -> list[str]:
    """Split one physical line on ``;`` outside quotes and bracket nesting."""
    parts: list[str] = []
    buf: list[str] = []
    in_quote = False
    escape = False
    depth = 0
    for ch in line:
        if in_quote:
            buf.append(ch)
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_quote = False
            continue
        if ch == '"':
            in_quote = True
        elif ch in _OPEN_BRACKETS:
            depth += 1
        elif ch in _CLOSE_BRACKETS:
            depth = max(0, depth - 1)
        elif ch == ";" and depth == 0:
            parts.append("".join(buf))
            buf = []
            continue
        buf.append(ch)
    parts.append("".join(buf))
    return parts


def iter_statements(source: str) -> Iterator[tuple[int, str]]:
    """Yield ``(line_no, stripped_statement)`` for every logical statement.

    Split on newlines and on semicolons outside quoted text and label delimiters; keep the 1-based
    line where each statement starts. Skip blank statements, ``%%`` comments, ``%%{ … }%%``
    directives and a leading YAML front-matter block. Never raises.
    """
    lines = _split_lines(source)
    span = _front_matter_span(lines)
    in_directive = False
    for idx, raw in enumerate(lines):
        if span is not None and span[0] <= idx <= span[1]:
            continue
        stripped = raw.strip()
        if in_directive:
            if "}%%" in stripped:
                in_directive = False
            continue
        if stripped.startswith("%%{"):
            if "}%%" not in stripped:
                in_directive = True
            continue
        if not stripped or stripped.startswith("%%"):
            continue
        for part in _split_statements(stripped):
            statement = part.strip()
            if statement:
                yield idx + 1, statement


def detect_diagram_type(source: str) -> str:
    """Return the diagram type from the first token of the first statement (exact, case-sensitive); else ``"unknown"``."""
    for _line_no, statement in iter_statements(source):
        return _HEADER_TO_TYPE.get(statement.split(maxsplit=1)[0], "unknown")
    return "unknown"


def normalize_mermaid_source(source: str) -> tuple[str, str | None]:
    """Strip every ``%%{ … }%%`` directive (single- or multi-line) and every front-matter key except ``title:``; lift ``theme``.

    Returns ``(normalized_source, theme)`` — ``theme`` only when it is one of ``MERMAID_THEMES``.
    Line endings become ``\\n`` and exactly one trailing newline is guaranteed. Never raises.
    """
    text = "\n".join(_split_lines(source))
    theme: str | None = None
    for match in _DIRECTIVE_RE.finditer(text):
        found = _THEME_RE.search(match.group(0))
        if found and found.group(1) in MERMAID_THEMES:
            theme = found.group(1)
            break
    text = _DIRECTIVE_RE.sub("", text)
    for match in _INLINE_DIRECTIVE_RE.finditer(text):
        found = _THEME_RE.search(match.group(0))
        if theme is None and found and found.group(1) in MERMAID_THEMES:
            theme = found.group(1)
    text = _INLINE_DIRECTIVE_RE.sub("", text)

    lines = text.split("\n")
    span = _front_matter_span(lines)
    if span is not None:
        lines = [
            line
            for idx, line in enumerate(lines)
            if not (span[0] < idx < span[1]) or _TITLE_KEY_RE.match(line) or not line.strip()
        ]
    text = "\n".join(lines)
    if not text.strip():
        return "", theme
    return text.rstrip("\n") + "\n", theme


def check_mermaid_source(source: str, *, declared_type: str | None = None) -> list[MermaidSourceIssue]:
    """Validate ``source`` for the wire; return EVERY issue found (empty list == valid). Pure; never raises.

    Order: size/empty -> surviving directive or front-matter key other than ``title:`` -> interaction statement /
    ``javascript:`` / ``<script`` -> declared type mismatch.
    """
    issues: list[MermaidSourceIssue] = []
    if not source or len(source.encode("utf-8")) > MERMAID_SOURCE_MAX_BYTES:
        issues.append(
            {
                "code": MERMAID_SOURCE_TOO_LARGE,
                "message": "empty source" if not source else f"source exceeds {MERMAID_SOURCE_MAX_BYTES} UTF-8 bytes",
                "line_no": None,
            }
        )
        if not source:
            return issues

    lines = _split_lines(source)
    for idx, raw in enumerate(lines):
        if "%%{" in raw:
            issues.append(
                {
                    "code": MERMAID_UNSAFE_DIRECTIVE,
                    "message": "%%{ }%% directives are not allowed in source",
                    "line_no": idx + 1,
                }
            )
    span = _front_matter_span(lines)
    if span is not None:
        for idx in range(span[0] + 1, span[1]):
            if lines[idx].strip() and not _TITLE_KEY_RE.match(lines[idx]):
                issues.append(
                    {
                        "code": MERMAID_UNSAFE_DIRECTIVE,
                        "message": "front matter other than a single-line 'title:' is not allowed in source",
                        "line_no": idx + 1,
                    }
                )

    for line_no, statement in iter_statements(source):
        if statement.split(maxsplit=1)[0].lower() in _INTERACTION_KEYWORDS:
            issues.append(
                {
                    "code": MERMAID_UNSAFE_INTERACTION,
                    "message": f"interaction statement {statement.split(maxsplit=1)[0]!r} is not allowed",
                    "line_no": line_no,
                }
            )
    # Fail closed: on a line whose quotes/brackets do not balance, Mermaid's per-diagram lexer may still
    # treat every ';' as a statement boundary, so scan each raw ';' segment regardless of quoting.
    for idx, raw in enumerate(lines):
        if span is not None and span[0] <= idx <= span[1]:
            continue
        stripped = raw.strip()
        if not stripped or stripped.startswith("%%") or not _is_ambiguous(stripped):
            continue
        for segment in stripped.split(";"):
            tokens = segment.split(maxsplit=1)
            if tokens and tokens[0].lower() in _INTERACTION_KEYWORDS:
                issues.append(
                    {
                        "code": MERMAID_UNSAFE_INTERACTION,
                        "message": f"interaction statement {tokens[0]!r} is not allowed",
                        "line_no": idx + 1,
                    }
                )
    for idx, raw in enumerate(lines):
        for found in _UNSAFE_ANYWHERE.finditer(raw):
            issues.append(
                {
                    "code": MERMAID_UNSAFE_INTERACTION,
                    "message": f"{found.group(0).lower()!r} is not allowed in source",
                    "line_no": idx + 1,
                }
            )

    if declared_type is not None:
        detected = detect_diagram_type(source)
        if declared_type != detected:
            issues.append(
                {
                    "code": MERMAID_DIAGRAM_TYPE_MISMATCH,
                    "message": f"diagramType {declared_type!r} does not match detected {detected!r}",
                    "line_no": None,
                }
            )
    return issues


def graph_spec_from_mermaid_source(source: str) -> GraphSpec:
    """Opt-in bridge: normalize ``source`` and delegate to :func:`from_mermaid`.

    Raises:
        MermaidCodecError: outside the codec's flowchart / stateDiagram-v2 / sequenceDiagram subset.
    """
    normalized, _theme = normalize_mermaid_source(source)
    return from_mermaid(normalized)
