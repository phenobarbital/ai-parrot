"""JavaScript/TypeScript plugin for the wiki repo scanner.

A single scanner claims every JS/TS suffix (``.js``/``.jsx``/``.mjs``/
``.ts``/``.tsx``, FEAT-394): an API outline (exported and non-exported
classes, functions, consts, interfaces, type aliases, with their JSDoc
first line) via tree-sitter when the optional ``ai-parrot[wiki-languages]``
extra is installed, or a bounded, line-anchored regex heuristic
otherwise. Only **relative** import specifiers (``./``, ``../``) are
resolved — bare package names (``react``, ``lodash``) are dropped at
extraction time, never even reaching :meth:`resolve_import`. Relative
specifiers resolve via extension guessing (``.ts``/``.tsx``/``.js``/
``.jsx``/``.mjs``, then ``/index.*``); ``tsconfig.json`` path aliases are
explicitly out of scope for v1 (per spec).
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable
from pathlib import PurePosixPath
from typing import Any, ClassVar

from parrot.knowledge.wiki.languages import treesitter
from parrot.knowledge.wiki.languages.base import LanguageOutline, LanguageScanner

logger = logging.getLogger(__name__)

_SUMMARY_MAX_CHARS = 240

# ---------------------------------------------------------------------------
# Heuristic patterns — line-anchored, bounded, no nested quantifiers (no
# catastrophic backtracking).
# ---------------------------------------------------------------------------

_RE_DOCBLOCK = re.compile(r"/\*\*(.*?)\*/", re.DOTALL)

_RE_EXPORT_CLASS = re.compile(
    r"^\s*export\s+(?:default\s+)?(?:abstract\s+)?class\s+(\w+)", re.MULTILINE
)
_RE_EXPORT_FUNCTION = re.compile(
    r"^\s*export\s+(?:default\s+)?(?:async\s+)?function\s+(\w+)\s*\(([^)]*)\)",
    re.MULTILINE,
)
_RE_EXPORT_CONST = re.compile(
    r"^\s*export\s+(?:default\s+)?const\s+(\w+)", re.MULTILINE
)
_RE_EXPORT_INTERFACE = re.compile(
    r"^\s*export\s+(?:default\s+)?interface\s+(\w+)", re.MULTILINE
)
_RE_EXPORT_TYPE = re.compile(
    r"^\s*export\s+(?:default\s+)?type\s+(\w+)\s*=", re.MULTILINE
)
_RE_CLASS = re.compile(r"^\s*(?:abstract\s+)?class\s+(\w+)", re.MULTILINE)
_RE_FUNCTION = re.compile(
    r"^\s*(?:async\s+)?function\s+(\w+)\s*\(([^)]*)\)", re.MULTILINE
)

_RE_IMPORT_FROM = re.compile(
    r"""(?:import|export)\s+.*?\s+from\s+['"]([^'"]+)['"]""", re.MULTILINE
)
_RE_IMPORT_SIDE_EFFECT = re.compile(r"""import\s+['"]([^'"]+)['"]""", re.MULTILINE)
_RE_REQUIRE = re.compile(r"""require\s*\(\s*['"]([^'"]+)['"]\s*\)""", re.MULTILINE)

#: Rendering label + start-of-line pattern for each exported construct
#: that has no distinct "params" group.
_EXPORT_SIMPLE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("export const", _RE_EXPORT_CONST),
    ("export interface", _RE_EXPORT_INTERFACE),
    ("export type", _RE_EXPORT_TYPE),
)

_EXTENSION_CANDIDATES: tuple[str, ...] = (".ts", ".tsx", ".js", ".jsx", ".mjs")
_INDEX_CANDIDATES: tuple[str, ...] = (
    "index.ts", "index.tsx", "index.js", "index.jsx", "index.mjs",
)


def _docblock_first_line(doc_body: str) -> str:
    """First non-empty line of a JSDoc block, ``*``-prefix stripped."""
    for raw in doc_body.splitlines():
        stripped = raw.strip().lstrip("*").strip()
        if stripped:
            return stripped[:_SUMMARY_MAX_CHARS]
    return ""


def _find_docblocks(source: str) -> list[tuple[int, int, str]]:
    """Every ``/** ... */`` block as ``(start, end, first_line)``, in order."""
    return [
        (m.start(), m.end(), _docblock_first_line(m.group(1)))
        for m in _RE_DOCBLOCK.finditer(source)
    ]


def _doc_for(docblocks: list[tuple[int, int, str]], decl_start: int) -> str:
    """JSDoc first line immediately (whitespace only) preceding ``decl_start``."""
    best = ""
    best_end = -1
    for _start, end, first_line in docblocks:
        if end <= decl_start and end > best_end:
            best_end = end
            best = first_line
    return best


def _extract_imports(source: str) -> list[str]:
    """Raw import specifiers, relative-only (bare package names dropped)."""
    specs: list[str] = []
    for pattern in (_RE_IMPORT_FROM, _RE_IMPORT_SIDE_EFFECT, _RE_REQUIRE):
        specs.extend(m.group(1) for m in pattern.finditer(source))
    seen: set[str] = set()
    ordered: list[str] = []
    for spec in specs:
        if spec.startswith(".") and spec not in seen:
            seen.add(spec)
            ordered.append(spec)
    return ordered


def _normalize_posix(path: PurePosixPath) -> str:
    """Collapse ``.``/``..`` segments in a (possibly non-existent) path."""
    parts: list[str] = []
    for part in path.parts:
        if part == "..":
            if parts:
                parts.pop()
        elif part in (".", ""):
            continue
        else:
            parts.append(part)
    return "/".join(parts)


class JavaScriptScanner(LanguageScanner):
    """Deep extractor for JavaScript/TypeScript files."""

    name: ClassVar[str] = "javascript"
    suffixes: ClassVar[frozenset[str]] = frozenset(
        {".js", ".jsx", ".mjs", ".ts", ".tsx"}
    )

    # -- outline ------------------------------------------------------------

    def outline(self, source: str, rel_path: str) -> LanguageOutline:
        """Extract summary, API outline, and raw imports from JS/TS source.

        Args:
            source: Raw JS/TS source text.
            rel_path: POSIX-style path relative to the repository root
                (unused by this scanner — kept for interface parity).

        Returns:
            The extracted :class:`LanguageOutline`. Any extraction
            failure degrades to an empty outline rather than raising.
        """
        try:
            imports = _extract_imports(source)
            language = "typescript" if PurePosixPath(rel_path).suffix in (
                ".ts", ".tsx"
            ) else "javascript"
            parser = treesitter.get_parser(language)
            if parser is not None:
                summary, lines = self._outline_treesitter(parser, source)
            else:
                summary, lines = self._outline_heuristic(source)
        except Exception as exc:  # noqa: BLE001 - degrade, never raise
            logger.debug("JS/TS outline extraction failed on %s: %s", rel_path, exc)
            return LanguageOutline()
        return LanguageOutline(summary=summary, outline=lines, imports=imports)

    def _outline_heuristic(self, source: str) -> tuple[str, list[str]]:
        """Bounded regex extraction — the fallback when tree-sitter is
        unavailable."""
        docblocks = _find_docblocks(source)
        entries: list[tuple[int, str]] = []

        for match in _RE_EXPORT_CLASS.finditer(source):
            doc = _doc_for(docblocks, match.start())
            entries.append(
                (match.start(), f"export class {match.group(1)}: {doc}".rstrip(": "))
            )
        for match in _RE_CLASS.finditer(source):
            doc = _doc_for(docblocks, match.start())
            entries.append(
                (match.start(), f"class {match.group(1)}: {doc}".rstrip(": "))
            )
        for match in _RE_EXPORT_FUNCTION.finditer(source):
            doc = _doc_for(docblocks, match.start())
            params = match.group(2).strip()
            entries.append((
                match.start(),
                f"export function {match.group(1)}({params}): {doc}".rstrip(": "),
            ))
        for match in _RE_FUNCTION.finditer(source):
            doc = _doc_for(docblocks, match.start())
            params = match.group(2).strip()
            entries.append((
                match.start(),
                f"function {match.group(1)}({params}): {doc}".rstrip(": "),
            ))
        for label, pattern in _EXPORT_SIMPLE_PATTERNS:
            for match in pattern.finditer(source):
                doc = _doc_for(docblocks, match.start())
                entries.append(
                    (match.start(), f"{label} {match.group(1)}: {doc}".rstrip(": "))
                )

        entries.sort(key=lambda e: e[0])
        lines = [line for _pos, line in entries]

        first_pos = min((pos for pos, _line in entries), default=len(source))
        summary = ""
        if docblocks and docblocks[0][0] < first_pos:
            summary = docblocks[0][2]
        return summary, lines

    def _outline_treesitter(self, parser: Any, source: str) -> tuple[str, list[str]]:
        """Best-effort tree-sitter outline using the JS/TS grammar's node
        types. Exercised only when the optional
        ``ai-parrot[wiki-languages]`` extra is installed; any structural
        mismatch degrades to an empty outline via the caller's
        ``except Exception`` guard rather than raising.
        """
        tree = parser.parse(source.encode("utf-8"))
        root = tree.root_node
        source_bytes = source.encode("utf-8")
        lines: list[str] = []

        def _text(node: Any) -> str:
            return source_bytes[node.start_byte:node.end_byte].decode(
                "utf-8", errors="replace"
            )

        def _name_of(node: Any) -> str:
            name_node = node.child_by_field_name("name")
            return _text(name_node) if name_node is not None else ""

        def _leading_doc(node: Any) -> str:
            prev = node.prev_sibling
            if prev is not None and prev.type == "comment":
                text = _text(prev)
                if text.startswith("/**"):
                    body = text[3:-2] if text.endswith("*/") else text[3:]
                    return _docblock_first_line(body)
            return ""

        exportable_types = {
            "class_declaration": "class",
            "function_declaration": "function",
            "interface_declaration": "interface",
            "type_alias_declaration": "type",
        }

        def _is_exported(node: Any) -> bool:
            parent = node.parent
            return parent is not None and parent.type == "export_statement"

        def _walk(node: Any) -> None:
            for child in node.children:
                kind = exportable_types.get(child.type)
                if kind is not None:
                    name = _name_of(child)
                    doc = _leading_doc(child) or _leading_doc(
                        child.parent if _is_exported(child) else child
                    )
                    prefix = "export " if _is_exported(child) else ""
                    lines.append(f"{prefix}{kind} {name}: {doc}".rstrip(": "))
                elif child.type == "lexical_declaration":
                    # `export const NAME = ...` / `const NAME = ...`
                    for decl in child.named_children:
                        name_node = decl.child_by_field_name("name")
                        if name_node is None:
                            continue
                        name = _text(name_node)
                        doc = _leading_doc(child)
                        prefix = "export " if _is_exported(child) else ""
                        lines.append(f"{prefix}const {name}: {doc}".rstrip(": "))
                _walk(child)

        _walk(root)

        summary = ""
        first_child = root.children[0] if root.children else None
        if first_child is not None and first_child.type == "comment":
            text = _text(first_child)
            if text.startswith("/**"):
                body = text[3:-2] if text.endswith("*/") else text[3:]
                summary = _docblock_first_line(body)
        return summary, lines

    # -- reference resolution -------------------------------------------------

    def build_reference_index(self, rel_paths: Iterable[str]) -> Any:
        """Build the set of every scanned repo file's POSIX rel path.

        Args:
            rel_paths: POSIX-style relative paths of every scanned file.

        Returns:
            An opaque ``frozenset[str]`` of rel paths.
        """
        return frozenset(PurePosixPath(p).as_posix() for p in rel_paths)

    def resolve_import(
        self, spec: str, from_file: str, index: Any
    ) -> str | None:
        """Resolve a relative import specifier via extension guessing.

        Bare (non-relative) specifiers are already filtered out at
        extraction time, but this is defensive: it also returns ``None``
        for any specifier that is not relative.

        Args:
            spec: A relative import specifier (``./x``, ``../x``).
            from_file: POSIX-relative path of the importing file.
            index: The ``frozenset[str]`` from :meth:`build_reference_index`.

        Returns:
            The resolved rel path, or ``None`` when unresolved.
        """
        if not spec.startswith("."):
            return None
        file_set: frozenset[str] = index
        base = PurePosixPath(from_file).parent / spec
        base_str = _normalize_posix(base)
        if base_str in file_set:
            return base_str
        for ext in _EXTENSION_CANDIDATES:
            candidate = base_str + ext
            if candidate in file_set:
                return candidate
        for idx in _INDEX_CANDIDATES:
            candidate = f"{base_str}/{idx}"
            if candidate in file_set:
                return candidate
        return None

    @property
    def mode(self) -> str:
        """``"tree-sitter"`` when either JS/TS grammar loads, else
        ``"heuristic"``."""
        if (
            treesitter.get_parser("typescript") is not None
            or treesitter.get_parser("javascript") is not None
        ):
            return "tree-sitter"
        return "heuristic"
