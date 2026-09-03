"""Rust plugin for the wiki repo scanner.

Deep extractor for ``.rs`` files (FEAT-394): an API outline (``pub``
structs, enums, traits, fns, mods, and ``impl`` blocks with their ``pub``
methods, each with its ``///`` doc-comment first line) via tree-sitter
when the optional ``ai-parrot[wiki-languages]`` extra is installed, or a
bounded, line-anchored regex heuristic otherwise. Import extraction
(``use crate::``/``use super::``/``use self::`` and ``mod foo;``
declarations) is regex-based in both modes. Reference resolution follows
Rust's crate-layout conventions: ``mod foo;`` resolves to ``foo.rs`` or
``foo/mod.rs`` relative to the declaring file's directory; ``use
crate::a::b`` resolves ``a/b.rs`` or ``a/b/mod.rs`` relative to the
nearest ancestor directory holding a ``src/lib.rs``/``src/main.rs`` crate
root.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable
from pathlib import PurePosixPath
from typing import Any, ClassVar

from parrot.knowledge.wiki.languages import astgrep, treesitter
from parrot.knowledge.wiki.languages.base import LanguageOutline, LanguageScanner
from parrot.knowledge.wiki.languages.render import render_outline, structural_enabled

logger = logging.getLogger(__name__)

_SUMMARY_MAX_CHARS = 240

# ---------------------------------------------------------------------------
# Heuristic patterns — line-anchored, bounded, no nested quantifiers (no
# catastrophic backtracking).
# ---------------------------------------------------------------------------

_RE_PUB_STRUCT = re.compile(r"^\s*pub(?:\(crate\))?\s+struct\s+(\w+)", re.MULTILINE)
_RE_PUB_ENUM = re.compile(r"^\s*pub(?:\(crate\))?\s+enum\s+(\w+)", re.MULTILINE)
_RE_PUB_TRAIT = re.compile(r"^\s*pub(?:\(crate\))?\s+trait\s+(\w+)", re.MULTILINE)
_RE_PUB_FN = re.compile(
    r"^\s*pub(?:\(crate\))?\s+(?:async\s+)?fn\s+(\w+)\s*\(([^)]*)\)" r"(?:\s*->\s*(\S+))?",
    re.MULTILINE,
)
_RE_PUB_MOD = re.compile(r"^\s*pub(?:\(crate\))?\s+mod\s+(\w+)\s*;", re.MULTILINE)
_RE_IMPL = re.compile(r"^\s*impl(?:<[^>]*>)?\s+(\w+)", re.MULTILINE)
_RE_MOD_DECL = re.compile(r"^\s*(?:pub(?:\(crate\))?\s+)?mod\s+(\w+)\s*;", re.MULTILINE)
_RE_USE_CRATE = re.compile(r"^\s*use\s+(crate|super|self)(::[\w:]+)(?:\s*\{([^}]+)\})?\s*;", re.MULTILINE)
_RE_DOC_LINE = re.compile(r"^[ \t]*///[ \t]?(.*)$", re.MULTILINE)

_CONTAINER_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("pub struct", _RE_PUB_STRUCT),
    ("pub enum", _RE_PUB_ENUM),
    ("pub trait", _RE_PUB_TRAIT),
)


def _find_doc_blocks(source: str) -> list[tuple[int, int, str]]:
    """Maximal runs of consecutive ``///`` lines as ``(start, end, first_line)``.

    Only the first line of each contiguous run is kept as the
    description (matching the ``/// First line`` convention used
    throughout the outline).
    """
    lines = [(m.start(), m.end(), m.group(1).strip()) for m in _RE_DOC_LINE.finditer(source)]
    blocks: list[tuple[int, int, str]] = []
    i = 0
    while i < len(lines):
        block_start, block_end, first_line = lines[i]
        j = i + 1
        while j < len(lines) and lines[j][0] == block_end + 1:
            block_end = lines[j][1]
            j += 1
        blocks.append((block_start, block_end, first_line[:_SUMMARY_MAX_CHARS]))
        i = j
    return blocks


def _is_attribute_line(line: str) -> bool:
    """Whether ``line`` is a single-line attribute macro (``#[derive(...)]``,
    ``#[pyclass]``, etc.) — these commonly sit between a doc comment and
    the item it documents, and must not break the association."""
    stripped = line.strip()
    return stripped.startswith("#[") and stripped.endswith("]")


def _doc_for(source: str, docblocks: list[tuple[int, int, str]], decl_start: int) -> str:
    """Doc-comment first line preceding ``decl_start``, tolerating only
    blank lines and single-line attribute macros in between."""
    best = ""
    best_end = -1
    for _start, end, first_line in docblocks:
        if end >= decl_start or end <= best_end:
            continue
        gap_lines = source[end:decl_start].splitlines()
        if all(not ln.strip() or _is_attribute_line(ln) for ln in gap_lines):
            best_end = end
            best = first_line
    return best


def _extract_rust_imports(source: str) -> list[str]:
    """Raw ``mod``/``use crate|super|self`` specifiers, in source order."""
    imports: list[str] = []
    for match in _RE_MOD_DECL.finditer(source):
        imports.append(f"mod:{match.group(1)}")
    for match in _RE_USE_CRATE.finditer(source):
        root, path_part, group = match.groups()
        if group:
            base = f"{root}{path_part}".rstrip(":")
            for name in group.split(","):
                name = name.strip()
                if name:
                    imports.append(f"{base}::{name}")
        else:
            imports.append(f"{root}{path_part}")
    return imports


class RustScanner(LanguageScanner):
    """Deep extractor for ``.rs`` files."""

    name: ClassVar[str] = "rust"
    suffixes: ClassVar[frozenset[str]] = frozenset({".rs"})
    #: ``"ast-grep"`` after the structural seam served the most recent
    #: file, otherwise ``None`` (see :attr:`mode`). FEAT-498.
    _last_mode: str | None = None

    # -- outline --------------------------------------------------------

    def outline(self, source: str, rel_path: str) -> LanguageOutline:
        """Extract summary, API outline, and raw imports from Rust source.

        Args:
            source: Raw Rust source text.
            rel_path: POSIX-style path relative to the repository root
                (unused by this scanner — kept for interface parity).

        Returns:
            The extracted :class:`LanguageOutline`. Any extraction
            failure degrades to an empty outline rather than raising.
        """
        try:
            imports = _extract_rust_imports(source)
            if structural_enabled():
                structural = astgrep.extract(source, "rust", rel_path)
                if structural is not None:
                    self._last_mode = "ast-grep"
                    return LanguageOutline(
                        summary=structural.summary,
                        outline=render_outline(structural.symbols, "rust"),
                        imports=imports,
                        symbols=structural.symbols,
                        refs=structural.refs,
                    )
            self._last_mode = None
            parser = treesitter.get_parser("rust")
            if parser is not None:
                summary, lines = self._outline_treesitter(parser, source)
            else:
                summary, lines = self._outline_heuristic(source)
        except Exception as exc:  # noqa: BLE001 - degrade, never raise
            logger.debug("Rust outline extraction failed on %s: %s", rel_path, exc)
            return LanguageOutline()
        return LanguageOutline(summary=summary, outline=lines, imports=imports)

    def _outline_heuristic(self, source: str) -> tuple[str, list[str]]:
        """Bounded regex extraction — the fallback when tree-sitter is
        unavailable."""
        docblocks = _find_doc_blocks(source)

        containers: list[tuple[int, str, str]] = []  # pos, label, name
        for label, pattern in _CONTAINER_PATTERNS:
            for match in pattern.finditer(source):
                containers.append((match.start(), label, match.group(1)))

        impls: list[tuple[int, str]] = [(m.start(), m.group(1)) for m in _RE_IMPL.finditer(source)]

        fns: list[tuple[int, str, str, str]] = []  # pos, name, params, ret
        for match in _RE_PUB_FN.finditer(source):
            fns.append(
                (
                    match.start(),
                    match.group(1),
                    match.group(2).strip(),
                    match.group(3) or "",
                )
            )

        mods: list[tuple[int, str]] = [(m.start(), m.group(1)) for m in _RE_PUB_MOD.finditer(source)]

        owners = sorted(
            [(pos, "container", label, name) for pos, label, name in containers]
            + [(pos, "impl", "impl", name) for pos, name in impls],
            key=lambda e: e[0],
        )

        entries: list[tuple[int, str]] = []
        for pos, label, name in containers:
            doc = _doc_for(source, docblocks, pos)
            entries.append((pos, f"{label} {name}: {doc}".rstrip(": ")))
        for pos, name in impls:
            entries.append((pos, f"impl {name}:"))
        for pos, name in mods:
            entries.append((pos, f"pub mod {name}"))
        for pos, name, params, ret in fns:
            owner = self._enclosing_owner(source, owners, pos)
            doc = _doc_for(source, docblocks, pos)
            sig = f"pub fn {name}({params})" + (f" -> {ret}" if ret else "")
            if owner is not None:
                entries.append((pos, f"    {sig}: {doc}".rstrip(": ")))
            else:
                entries.append((pos, f"{sig}: {doc}".rstrip(": ")))

        entries.sort(key=lambda e: e[0])
        lines = [line for _pos, line in entries]

        first_pos = min((pos for pos, _line in entries), default=len(source))
        summary = ""
        if docblocks and docblocks[0][0] < first_pos:
            summary = docblocks[0][2]
        return summary, lines

    @staticmethod
    def _enclosing_owner(
        source: str,
        owners: list[tuple[int, str, str, str]],
        fn_pos: int,
    ) -> str | None:
        """Name of the container/impl block whose body directly encloses
        ``fn_pos`` (brace-depth heuristic, matching the PHP plugin's)."""
        fn_depth = source.count("{", 0, fn_pos) - source.count("}", 0, fn_pos)
        best_name: str | None = None
        best_pos = -1
        for pos, _kind, _label, name in owners:
            if pos >= fn_pos:
                continue
            owner_depth = source.count("{", 0, pos) - source.count("}", 0, pos)
            if owner_depth + 1 == fn_depth and pos > best_pos:
                best_pos = pos
                best_name = name
        return best_name

    def _outline_treesitter(self, parser: Any, source: str) -> tuple[str, list[str]]:
        """Best-effort tree-sitter outline using the ``tree_sitter_rust``
        grammar's node types. Exercised only when the optional
        ``ai-parrot[wiki-languages]`` extra is installed; any structural
        mismatch degrades to an empty outline via the caller's
        ``except Exception`` guard rather than raising.
        """
        tree = parser.parse(source.encode("utf-8"))
        root = tree.root_node
        source_bytes = source.encode("utf-8")
        lines: list[str] = []

        def _text(node: Any) -> str:
            return source_bytes[node.start_byte : node.end_byte].decode("utf-8", errors="replace")

        def _name_of(node: Any) -> str:
            name_node = node.child_by_field_name("name")
            return _text(name_node) if name_node is not None else ""

        def _leading_doc(node: Any) -> str:
            prev = node.prev_sibling
            # Attribute macros (`#[derive(...)]`, `#[pyclass]`, etc.) are
            # near-universal on public Rust items and commonly sit between
            # the doc comment and the item — walk past them.
            while prev is not None and prev.type == "attribute_item":
                prev = prev.prev_sibling
            if prev is not None and prev.type in ("line_comment", "doc_comment"):
                text = _text(prev)
                if text.startswith("///"):
                    return text[3:].strip()[:_SUMMARY_MAX_CHARS]
            return ""

        def _is_pub(node: Any) -> bool:
            first = node.children[0] if node.children else None
            return first is not None and first.type == "visibility_modifier"

        item_types = {
            "struct_item": "struct",
            "enum_item": "enum",
            "trait_item": "trait",
            "function_item": "fn",
            "mod_item": "mod",
        }

        def _walk(node: Any, in_impl: str | None) -> None:
            for child in node.children:
                kind = item_types.get(child.type)
                if kind == "fn":
                    if _is_pub(child) or in_impl is not None:
                        name = _name_of(child)
                        params_node = child.child_by_field_name("parameters")
                        params = _text(params_node).strip("()") if params_node else ""
                        doc = _leading_doc(child)
                        sig = f"pub fn {name}({params})"
                        if in_impl is not None:
                            lines.append(f"    {sig}: {doc}".rstrip(": "))
                        else:
                            lines.append(f"{sig}: {doc}".rstrip(": "))
                    _walk(child, in_impl=in_impl)
                elif kind in ("struct", "enum", "trait") and _is_pub(child):
                    name = _name_of(child)
                    doc = _leading_doc(child)
                    lines.append(f"pub {kind} {name}: {doc}".rstrip(": "))
                    _walk(child, in_impl=in_impl)
                elif kind == "mod" and _is_pub(child):
                    name = _name_of(child)
                    lines.append(f"pub mod {name}")
                    _walk(child, in_impl=in_impl)
                elif child.type == "impl_item":
                    name = _name_of(child)
                    lines.append(f"impl {name}:")
                    _walk(child, in_impl=name)
                else:
                    _walk(child, in_impl=in_impl)

        _walk(root, in_impl=None)

        summary = ""
        first_child = root.children[0] if root.children else None
        if first_child is not None and first_child.type in ("line_comment", "doc_comment"):
            text = _text(first_child)
            if text.startswith("///"):
                summary = text[3:].strip()[:_SUMMARY_MAX_CHARS]
        return summary, lines

    # -- reference resolution ---------------------------------------------

    def build_reference_index(self, rel_paths: Iterable[str]) -> Any:
        """Build a ``(file_set, crate_roots)`` pair over the repo file list.

        ``crate_roots`` maps a directory (POSIX string, ``""`` for the
        repository root) to the ``lib.rs``/``main.rs`` file that makes it
        a crate root.

        Args:
            rel_paths: POSIX-style relative paths of every scanned file.

        Returns:
            Opaque ``(frozenset[str], dict[str, str])`` index.
        """
        file_set: set[str] = set()
        crate_roots: dict[str, str] = {}
        for rp in rel_paths:
            p = PurePosixPath(rp)
            if p.suffix != ".rs":
                continue
            posix = p.as_posix()
            file_set.add(posix)
            if p.name in ("lib.rs", "main.rs"):
                crate_roots[p.parent.as_posix()] = posix
        return (frozenset(file_set), crate_roots)

    @staticmethod
    def _find_crate_root(from_file: str, crate_roots: dict[str, str]) -> str | None:
        """Nearest ancestor directory of ``from_file`` that is a crate root."""
        parts = PurePosixPath(from_file).parent.parts
        for depth in range(len(parts), -1, -1):
            candidate_dir = "/".join(parts[:depth])
            if candidate_dir in crate_roots:
                return candidate_dir
        return None

    def resolve_import(self, spec: str, from_file: str, index: Any) -> str | None:
        """Resolve a ``mod:``-prefixed or ``crate``/``super``/``self``
        specifier via Rust crate-layout conventions.

        Args:
            spec: Raw import specifier from :meth:`outline` — either
                ``mod:<name>`` (from a ``mod foo;`` declaration) or a
                ``crate::``/``super::``/``self::`` path.
            from_file: POSIX-relative path of the importing file.
            index: The ``(file_set, crate_roots)`` pair from
                :meth:`build_reference_index`.

        Returns:
            The resolved rel path, or ``None`` when unresolved.
        """
        file_set, crate_roots = index
        from_dir = PurePosixPath(from_file).parent.as_posix()

        if spec.startswith("mod:"):
            mod_name = spec[4:]
            return self._first_match(file_set, from_dir, mod_name)

        if spec.startswith("crate::"):
            parts = spec[len("crate::") :].split("::")
            crate_root_dir = self._find_crate_root(from_file, crate_roots)
            if crate_root_dir is None:
                return None
            return self._first_match(file_set, crate_root_dir, "/".join(parts[:-1]), parts[-1])

        if spec.startswith("self::"):
            parts = spec[len("self::") :].split("::")
            return self._first_match(file_set, from_dir, "/".join(parts[:-1]), parts[-1])

        if spec.startswith("super::"):
            parent_dir = PurePosixPath(from_dir).parent.as_posix()
            parts = spec[len("super::") :].split("::")
            return self._first_match(file_set, parent_dir, "/".join(parts[:-1]), parts[-1])

        return None

    @staticmethod
    def _first_match(
        file_set: frozenset[str],
        base_dir: str,
        *segments: str,
    ) -> str | None:
        """First of ``base_dir/.../seg.rs`` or ``.../seg/mod.rs`` in ``file_set``."""
        joined = "/".join(s for s in (base_dir, *segments) if s)
        for candidate in (f"{joined}.rs", f"{joined}/mod.rs"):
            if candidate in file_set:
                return candidate
        return None

    @property
    def mode(self) -> str:
        """``"tree-sitter"`` when the optional grammar loads, else
        ``"heuristic"``."""
        if self._last_mode == "ast-grep":
            return "ast-grep"
        if treesitter.get_parser("rust") is not None:
            return "tree-sitter"
        return "heuristic"
