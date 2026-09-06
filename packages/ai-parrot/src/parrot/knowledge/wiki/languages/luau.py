"""Luau/Lua plugin for the wiki repo scanner (FEAT-532 TASK-2899).

Deep extractor for ``.lua``/``.luau`` files: leading comments, named/local
functions, colon methods, exported/non-exported type declarations, and
assignments to a returned module table, via tree-sitter when the optional
``tree-sitter-luau`` grammar is installed, or a bounded, comment/string-masked
regex heuristic otherwise (spec §"Local scanning and resolution").

Always returns empty ``symbols``/``refs`` (no ``sym:`` structural plane for
Luau — settled in spec §8: ast-grep cannot register Luau from the wheel).
Require resolution is delegated entirely to
:mod:`parrot.knowledge.wiki.roblox.project` (TASK-2898); this module owns
only syntax extraction, raw require-argument text extraction, and the
combined TASK-2896 resource guards (:mod:`parrot.knowledge.wiki.languages.luau_guard`).
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable
from pathlib import PurePosixPath
from typing import Any, ClassVar

from parrot.knowledge.wiki.languages import luau_guard, treesitter
from parrot.knowledge.wiki.languages.base import LanguageOutline, LanguageScanner

logger = logging.getLogger(__name__)

_SUMMARY_MAX_CHARS = 240

#: Node types that carry a function/method's callable name, in the shapes
#: the ``tree-sitter-luau`` grammar produces (verified 2026-09-06 against
#: tree-sitter-luau 1.2.0): ``function Module.add(...)`` ->
#: ``dot_index_expression``; ``function Module:greet(...)`` ->
#: ``method_index_expression``; ``local function helper(...)`` / bare
#: ``function foo(...)`` -> plain ``identifier``.
_NAME_NODE_TYPES = frozenset({"identifier", "dot_index_expression", "method_index_expression"})

_REQUIRE_IDENTIFIER = "require"


# ---------------------------------------------------------------------------
# Comment/string masking for the heuristic (no-grammar) path
# ---------------------------------------------------------------------------


def _mask_source(source: str, mask_strings: bool) -> str:
    """Blank comments (always) and, optionally, string bodies.

    A single-pass, string-aware state machine — never regex-based, so
    there is no backtracking surface. Replaces masked characters with
    spaces (newlines are preserved) so byte offsets and line numbers used
    by the heuristic patterns stay aligned with the original source.

    Handles ``--`` line comments, ``--[[ ]]``/``--[=[ ]=]`` block
    comments, ``'`` / ``"`` quoted strings with backslash escapes, and
    ``[[ ]]``/``[=[ ]=]`` long strings. Luau's backtick interpolated
    strings are masked as simple strings (interpolation expressions
    inside ``{}`` are not specially recognized) — a documented,
    accepted simplification; this is a heuristic fallback, not a full
    lexer (spec: no Lua dialect completeness required).
    """
    out = list(source)
    n = len(source)
    i = 0

    def _blank(a: int, b: int) -> None:
        for k in range(a, b):
            if out[k] != "\n":
                out[k] = " "

    def _long_bracket_level(pos: int) -> int | None:
        """If ``source[pos]`` starts a ``[=*[`` opener, return its level."""
        if pos >= n or source[pos] != "[":
            return None
        j = pos + 1
        level = 0
        while j < n and source[j] == "=":
            level += 1
            j += 1
        if j < n and source[j] == "[":
            return level
        return None

    while i < n:
        ch = source[i]
        if ch == "-" and source[i : i + 2] == "--":
            level = _long_bracket_level(i + 2)
            if level is not None:
                closer = "]" + ("=" * level) + "]"
                end = source.find(closer, i + 2)
                end = n if end == -1 else end + len(closer)
                _blank(i, end)
                i = end
                continue
            end = source.find("\n", i)
            end = n if end == -1 else end
            _blank(i, end)
            i = end
            continue

        level = _long_bracket_level(i)
        if level is not None:
            closer = "]" + ("=" * level) + "]"
            end = source.find(closer, i)
            end = n if end == -1 else end + len(closer)
            if mask_strings:
                _blank(i, end)
            i = end
            continue

        if ch in ("'", '"'):
            j = i + 1
            while j < n and source[j] != ch:
                if source[j] == "\\":
                    j += 2
                    continue
                j += 1
            end = min(j + 1, n)
            if mask_strings:
                _blank(i, end)
            i = end
            continue

        if ch == "`":
            j = i + 1
            while j < n and source[j] != "`":
                if source[j] == "\\":
                    j += 2
                    continue
                j += 1
            end = min(j + 1, n)
            if mask_strings:
                _blank(i, end)
            i = end
            continue

        i += 1

    return "".join(out)


# ---------------------------------------------------------------------------
# require(...) argument extraction — shared by both modes
# ---------------------------------------------------------------------------


def _extract_requires_from_text(comment_masked: str) -> list[str]:
    """Find every top-level ``require(...)`` call and return its raw
    argument text, in source order.

    Operates on comment-masked (but **not** string-masked) text so a
    string-literal require argument (``require("./Foo")``) is preserved
    verbatim, while a ``require(...)`` example written inside a comment
    is never matched (comments are already blanked). Uses a balanced-
    paren scan rather than a single regex, since arguments can legally
    contain nested parens (``require(game:GetService("X").Bar)``).
    """
    imports: list[str] = []
    pattern = re.compile(r"\b" + _REQUIRE_IDENTIFIER + r"\s*\(")
    for match in pattern.finditer(comment_masked):
        # Reject a member/method call like `obj.require(...)` or
        # `obj:require(...)` — only a bare call is a real require.
        prefix_start = match.start()
        prefix = comment_masked[:prefix_start].rstrip()
        if prefix and prefix[-1] in (".", ":"):
            continue
        depth = 1
        pos = match.end()
        start = pos
        while pos < len(comment_masked) and depth > 0:
            if comment_masked[pos] == "(":
                depth += 1
            elif comment_masked[pos] == ")":
                depth -= 1
            pos += 1
        if depth == 0:
            imports.append(comment_masked[start : pos - 1].strip())
    return imports


# ---------------------------------------------------------------------------
# tree-sitter extraction (runs inside the isolated child process)
# ---------------------------------------------------------------------------


def _ts_text(node: Any, source_bytes: bytes) -> str:
    return source_bytes[node.start_byte : node.end_byte].decode("utf-8", errors="replace")


def _ts_leading_comment(node: Any, source_bytes: bytes) -> str:
    prev = node.prev_sibling
    if prev is None or prev.type != "comment":
        return ""
    for child in prev.children:
        if child.type == "comment_content":
            return _ts_text(child, source_bytes).lstrip("-").strip()[:_SUMMARY_MAX_CHARS]
    return ""


def _ts_function_name(node: Any, source_bytes: bytes) -> tuple[str, bool]:
    """``(name, is_colon_method)`` for a ``function_declaration`` node."""
    name = ""
    is_colon = False
    for child in node.children:
        if child.type in _NAME_NODE_TYPES:
            name = _ts_text(child, source_bytes)
            is_colon = child.type == "method_index_expression"
    return name, is_colon


def _ts_params(node: Any, source_bytes: bytes) -> str:
    for child in node.children:
        if child.type == "parameters":
            return _ts_text(child, source_bytes).strip("()")
    return ""


def _ts_return_type(node: Any, source_bytes: bytes) -> str:
    seen_colon = False
    for child in node.children:
        if child.type == "parameters":
            continue
        if child.type == ":":
            seen_colon = True
            continue
        if seen_colon and child.type != "block":
            return _ts_text(child, source_bytes)
        if child.type == "block":
            break
    return ""


def _ts_module_export_name(root: Any, source_bytes: bytes) -> str | None:
    """The identifier of the file's last top-level ``return <Name>``."""
    result: str | None = None
    for child in root.children:
        if child.type != "return_statement":
            continue
        for sub in child.children:
            if sub.type == "expression_list" and sub.named_child_count == 1:
                expr = sub.named_children[0]
                if expr.type == "identifier":
                    result = _ts_text(expr, source_bytes)
    return result


def _ts_walk(root: Any, source_bytes: bytes) -> tuple[str, list[str]]:
    """Top-level-only outline walk: functions, types, and module-table
    field assignments. Deliberately shallow (root's direct children
    only) — nested declarations inside function bodies are not surfaced,
    matching the sibling scanners' outline granularity."""
    lines: list[str] = []
    module_name = _ts_module_export_name(root, source_bytes)

    summary = ""
    first = root.children[0] if root.children else None
    if first is not None and first.type == "comment":
        for c in first.children:
            if c.type == "comment_content":
                summary = _ts_text(c, source_bytes).lstrip("-").strip()[:_SUMMARY_MAX_CHARS]

    for child in root.children:
        if child.type == "function_declaration":
            # `name` already carries the "." or ":" separator verbatim
            # (it is the raw text of the dot/method index expression), so
            # the colon/dot distinction needs no separate rendering here.
            name, _is_colon_method = _ts_function_name(child, source_bytes)
            if not name:
                continue
            params = _ts_params(child, source_bytes)
            ret = _ts_return_type(child, source_bytes)
            doc = _ts_leading_comment(child, source_bytes)
            sig = f"function {name}({params})"
            if ret:
                sig = f"{sig}: {ret}"
            line = f"{sig}  -- {doc}" if doc else sig
            lines.append(line)
        elif child.type == "type_definition":
            text = _ts_text(child, source_bytes)
            doc = _ts_leading_comment(child, source_bytes)
            line = text if not doc else f"{text}  -- {doc}"
            lines.append(line.split("\n")[0])
        elif child.type == "assignment_statement" and module_name:
            for sub in child.children:
                if sub.type != "variable_list":
                    continue
                for var in sub.children:
                    if var.type == "dot_index_expression":
                        text = _ts_text(var, source_bytes)
                        if text.startswith(f"{module_name}."):
                            lines.append(f"field {text}")

    if module_name:
        lines.append(f"module returns {module_name}")

    return summary, lines


def _run_treesitter_outline(parser: Any, source_bytes: bytes) -> dict[str, Any]:
    """Parse + extract using an already-loaded, cached ``Parser``.

    Runs synchronously, in-process — per
    ``docs/design/luau-parser-resource-policy.md`` §1/§3, per-file
    subprocess isolation is reserved for the offline benchmark/CI
    regression path (:mod:`scripts.benchmarks.luau_parser_limits`,
    ``test_resource_corpus.py``), never the production ``outline()`` hot
    path: the measured pre-parse byte cap (:func:`luau_guard.admit_for_treesitter`)
    already bounds worst-case wall time, and TASK-2896 measured that
    tree-sitter's own error recovery does not hang or raise at these
    sizes — there is nothing left for a per-file fork to usefully cancel.
    """
    tree = parser.parse(source_bytes)
    root = tree.root_node
    density = luau_guard.error_density(root)
    summary, lines = _ts_walk(root, source_bytes)
    return {"summary": summary, "outline": lines, "density": density}


# ---------------------------------------------------------------------------
# Heuristic extraction (no grammar / guard rejection)
# ---------------------------------------------------------------------------

_RE_FUNCTION = re.compile(
    r"^[ \t]*(local\s+)?function\s+([A-Za-z_][\w.:]*)\s*\(([^)]*)\)(?:\s*:\s*([^\n]+?))?\s*$",
    re.MULTILINE,
)
_RE_TYPE = re.compile(r"^[ \t]*(export\s+)?type\s+([A-Za-z_]\w*)\s*=.*$", re.MULTILINE)
_RE_RETURN = re.compile(r"^[ \t]*return\s+([A-Za-z_]\w*)\s*$", re.MULTILINE)
_RE_FIELD_ASSIGN = re.compile(r"^[ \t]*([A-Za-z_]\w*)\.([A-Za-z_]\w*)\s*=", re.MULTILINE)


def _heuristic_comment_for(masked_full: str, pos: int) -> str:
    line_start = masked_full.rfind("\n", 0, pos) + 1
    prev_end = line_start - 1
    if prev_end < 0:
        return ""
    prev_start = masked_full.rfind("\n", 0, prev_end) + 1
    prev_line = masked_full[prev_start:prev_end].strip()
    original_prev = prev_line
    if original_prev.startswith("--"):
        return original_prev.lstrip("-").strip()[:_SUMMARY_MAX_CHARS]
    return ""


def _heuristic_outline(source: str) -> tuple[str, list[str]]:
    """Bounded regex extraction over comment/string-masked source.

    Comments are masked from a **separate, comment-only-masked** copy
    used just for locating "preceding comment" text (so the comment
    content itself is still readable there); the copy the declaration
    regexes run against additionally masks string bodies, so a
    documentation string containing something that looks like a
    function/type declaration can never be picked up.
    """
    comment_only = _mask_source(source, mask_strings=False)
    fully_masked = _mask_source(source, mask_strings=True)

    module_name = None
    for match in _RE_RETURN.finditer(fully_masked):
        module_name = match.group(1)

    entries: list[tuple[int, str]] = []
    for match in _RE_FUNCTION.finditer(fully_masked):
        name, params, ret = match.group(2), match.group(3), match.group(4)
        doc = _heuristic_comment_for(comment_only, match.start())
        sig = f"function {name}({params.strip()})"
        if ret:
            sig = f"{sig}: {ret.strip()}"
        line = f"{sig}  -- {doc}" if doc else sig
        entries.append((match.start(), line))

    for match in _RE_TYPE.finditer(fully_masked):
        doc = _heuristic_comment_for(comment_only, match.start())
        text = match.group(0).strip()
        line = f"{text}  -- {doc}" if doc else text
        entries.append((match.start(), line))

    if module_name:
        for match in _RE_FIELD_ASSIGN.finditer(fully_masked):
            if match.group(1) == module_name:
                entries.append((match.start(), f"field {module_name}.{match.group(2)}"))

    entries.sort(key=lambda e: e[0])
    lines = [line for _pos, line in entries]
    if module_name:
        lines.append(f"module returns {module_name}")

    summary = ""
    first_comment = re.match(r"^[ \t]*--(?!\[)([^\n]*)", source)
    if first_comment:
        summary = first_comment.group(1).lstrip("-").strip()[:_SUMMARY_MAX_CHARS]

    return summary, lines


# ---------------------------------------------------------------------------
# Scanner
# ---------------------------------------------------------------------------


class LuauScanner(LanguageScanner):
    """Deep extractor for ``.lua``/``.luau`` (Roblox Luau) files."""

    name: ClassVar[str] = "luau"
    suffixes: ClassVar[frozenset[str]] = frozenset({".lua", ".luau"})

    def outline(self, source: str, rel_path: str) -> LanguageOutline:
        """Extract summary, API outline, and raw require specifiers.

        Never raises: any admission rejection, guard timeout, or
        unexpected exception degrades to an empty
        :class:`LanguageOutline`. ``symbols``/``refs`` are always empty
        (spec §8: no Luau ``sym:`` structural plane in v1).

        Args:
            source: Raw Luau/Lua source text.
            rel_path: POSIX-style path relative to the repository root
                (unused — kept for interface parity).

        Returns:
            The extracted :class:`LanguageOutline`.
        """
        try:
            source_bytes = source.encode("utf-8")
            comment_only = _mask_source(source, mask_strings=False)
            imports = _extract_requires_from_text(comment_only)

            if not luau_guard.admit_for_heuristic(source_bytes):
                logger.debug(
                    "Luau %s exceeds the %d-byte fallback bound, skipped",
                    rel_path,
                    luau_guard.FALLBACK_BYTE_LIMIT,
                )
                return LanguageOutline()

            parser = treesitter.get_parser("luau") if luau_guard.admit_for_treesitter(source_bytes) else None

            if parser is not None:
                try:
                    result = _run_treesitter_outline(parser, source_bytes)
                    density = result["density"]
                    if density > luau_guard.DENSITY_THRESHOLD:
                        logger.debug("Luau %s parsed with high ERROR density %.2f", rel_path, density)
                    return LanguageOutline(summary=result["summary"], outline=result["outline"], imports=imports)
                except Exception as exc:  # noqa: BLE001 - degrade to heuristic, never raise
                    logger.debug(
                        "Luau tree-sitter parse failed on %s (%s), falling back to heuristic",
                        rel_path,
                        exc,
                    )

            summary, lines = _heuristic_outline(source)
            return LanguageOutline(summary=summary, outline=lines, imports=imports)
        except Exception as exc:  # noqa: BLE001 - degrade, never raise
            logger.debug("Luau outline extraction failed on %s: %s", rel_path, exc)
            return LanguageOutline()

    # -- reference resolution — delegated entirely to TASK-2898 -------------

    def build_reference_index(self, rel_paths: Iterable[str]) -> Any:
        """Build ``(RobloxInstanceIndex, discovered_set)`` over the repo file list.

        Delegates all mapping construction to
        :func:`parrot.knowledge.wiki.roblox.project.build_instance_index`
        — this scanner owns syntax extraction only, never mapping logic.

        Args:
            rel_paths: POSIX-style relative paths of every scanned file.

        Returns:
            Opaque ``(RobloxInstanceIndex, frozenset[str])`` index.
        """
        # Local imports: avoids importing the roblox package (and its
        # eventual acquisition/render siblings) at scanner-module import
        # time, matching PHP's `get_scan_root` circular-import precedent.
        from parrot.knowledge.wiki.languages import get_scan_root
        from parrot.knowledge.wiki.roblox.project import build_instance_index

        discovered = frozenset(PurePosixPath(p).as_posix() for p in rel_paths)
        index = build_instance_index(get_scan_root(), discovered)
        return (index, discovered)

    def resolve_import(self, spec: str, from_file: str, index: Any) -> str | None:
        """Resolve one raw require specifier via TASK-2898's resolver.

        Args:
            spec: Raw require argument text from :meth:`outline`.
            from_file: POSIX-relative path of the requiring file.
            index: The ``(RobloxInstanceIndex, discovered_set)`` pair
                from :meth:`build_reference_index`.

        Returns:
            The resolved rel path, or ``None`` when unresolved.
        """
        from parrot.knowledge.wiki.roblox.project import resolve_roblox_require

        instance_index, discovered = index
        return resolve_roblox_require(spec, from_file, instance_index, discovered)

    @property
    def mode(self) -> str:
        """``"tree-sitter"`` when the optional grammar loads, else
        ``"heuristic"``."""
        if treesitter.get_parser("luau") is not None:
            return "tree-sitter"
        return "heuristic"
