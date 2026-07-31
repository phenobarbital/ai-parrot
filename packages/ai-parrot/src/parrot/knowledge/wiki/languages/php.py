"""PHP plugin for the wiki repo scanner.

Deep extractor for ``.php`` files (FEAT-394): an API outline (classes,
interfaces, traits, enums, functions, methods, with their PHPDoc first
line) via tree-sitter when the optional ``ai-parrot[wiki-languages]``
extra is installed, or a bounded, line-safe regex heuristic otherwise.
Import extraction (``use`` statements and ``require``/``include`` paths)
is regex-based in both modes. Reference resolution understands two PHP
idioms: namespaced ``use`` targets (via a repo ``composer.json`` PSR-4
autoload map, falling back to namespace-tail ↔ path matching) and
``require``/``include`` paths resolved relative to the importing file.

.. note::
    The heuristic patterns below intentionally use a "not preceded by a
    word character" lookbehind rather than strict line-start anchoring
    (``^`` + ``re.MULTILINE``): PHP files may open with arbitrary HTML
    before the first ``<?php`` tag, so a declaration can legitimately
    share a line with other markup. The lookbehind still keeps every
    pattern bounded (fixed-width classes only, no nested quantifiers) —
    the property that actually prevents catastrophic backtracking.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterable
from pathlib import Path, PurePosixPath
from typing import Any, ClassVar

from parrot.knowledge.wiki.languages import treesitter
from parrot.knowledge.wiki.languages.base import LanguageOutline, LanguageScanner

logger = logging.getLogger(__name__)

_SUMMARY_MAX_CHARS = 240

# ---------------------------------------------------------------------------
# Heuristic patterns — bounded, no nested quantifiers (no catastrophic
# backtracking), anchored on a "not part of a longer identifier" lookbehind
# instead of line-start so embedded PHP (after leading HTML) still matches.
# ---------------------------------------------------------------------------

_RE_DOCBLOCK = re.compile(r"/\*\*(.*?)\*/", re.DOTALL)
_RE_CLASS = re.compile(r"(?<![\w$])(?:abstract\s+|final\s+)?class\s+(\w+)")
_RE_INTERFACE = re.compile(r"(?<![\w$])interface\s+(\w+)")
_RE_TRAIT = re.compile(r"(?<![\w$])trait\s+(\w+)")
_RE_ENUM = re.compile(r"(?<![\w$])enum\s+(\w+)")
_RE_FUNCTION = re.compile(r"(?<![\w$])function\s+(\w+)\s*\(([^)]*)\)")
_RE_USE = re.compile(r"(?<![\w$])use\s+([\w\\]+)(?:\\?\{([^}]+)\})?\s*;")
_RE_REQUIRE = re.compile(
    r"(?<![\w$])(?:require_once|include_once|require|include)\s+"
    r"(?:__DIR__\s*\.\s*)?['\"]([^'\"]+)['\"]"
)

#: Visibility/abstractness keywords allowed between a docblock and the
#: declaration it documents (only whitespace + these tokens tolerated).
_MODIFIER_TOKENS = frozenset(
    {"abstract", "final", "public", "protected", "private", "static"}
)

#: Container keyword -> rendered outline label, in the exact style used by
#: the existing Python outline (``kind Name: doc``).
_CONTAINER_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("class", _RE_CLASS),
    ("interface", _RE_INTERFACE),
    ("trait", _RE_TRAIT),
    ("enum", _RE_ENUM),
)


def _docblock_first_line(doc_body: str) -> str:
    """First non-empty line of a PHPDoc block, ``*``-prefix stripped."""
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


def _gap_is_modifiers_only(gap: str) -> bool:
    """Whether ``gap`` (text between a docblock and a declaration) is only
    whitespace and visibility/abstractness keywords."""
    return all(tok in _MODIFIER_TOKENS for tok in gap.split())


def _extract_php_imports(source: str) -> list[str]:
    """Raw ``use``/``require``/``include`` specifiers, in source order."""
    imports: list[str] = []
    for match in _RE_USE.finditer(source):
        base = match.group(1).strip("\\")
        group = match.group(2)
        if group:
            for name in group.split(","):
                name = name.strip().strip("\\")
                if name:
                    imports.append(f"{base}\\{name}")
        elif base:
            imports.append(base)
    for match in _RE_REQUIRE.finditer(source):
        imports.append(match.group(1))
    return imports


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


class PhpScanner(LanguageScanner):
    """Deep extractor for ``.php`` files."""

    name: ClassVar[str] = "php"
    suffixes: ClassVar[frozenset[str]] = frozenset({".php"})

    # -- outline ----------------------------------------------------------

    def outline(self, source: str, rel_path: str) -> LanguageOutline:
        """Extract summary, API outline, and raw imports from PHP source.

        Args:
            source: Raw PHP source text (may open with HTML before the
                first ``<?php`` tag).
            rel_path: POSIX-style path relative to the repository root
                (unused by this scanner — kept for interface parity).

        Returns:
            The extracted :class:`LanguageOutline`. Any extraction
            failure degrades to an empty outline rather than raising.
        """
        try:
            imports = _extract_php_imports(source)
            parser = treesitter.get_parser("php")
            if parser is not None:
                summary, lines = self._outline_treesitter(parser, source)
            else:
                summary, lines = self._outline_heuristic(source)
        except Exception as exc:  # noqa: BLE001 - degrade, never raise
            logger.debug("PHP outline extraction failed on %s: %s", rel_path, exc)
            return LanguageOutline()
        return LanguageOutline(summary=summary, outline=lines, imports=imports)

    def _outline_heuristic(self, source: str) -> tuple[str, list[str]]:
        """Bounded regex extraction — the fallback when tree-sitter is
        unavailable, and PHP's *only* mode when it always is."""
        docblocks = _find_docblocks(source)

        containers: list[tuple[int, str, str, str]] = []  # pos, kind, name, doc
        for kind, pattern in _CONTAINER_PATTERNS:
            for match in pattern.finditer(source):
                doc = self._doc_for(source, docblocks, match.start())
                containers.append((match.start(), kind, match.group(1), doc))

        functions: list[tuple[int, str, str]] = []  # pos, name, params
        for match in _RE_FUNCTION.finditer(source):
            functions.append((match.start(), match.group(1), match.group(2).strip()))

        containers.sort(key=lambda c: c[0])
        lines: list[str] = []
        entries: list[tuple[int, str]] = [(pos, "container") for pos, *_ in containers]
        entries += [(pos, "function") for pos, *_ in functions]
        entries.sort()

        container_by_pos = {pos: (kind, nm, doc) for pos, kind, nm, doc in containers}
        function_by_pos = {pos: (nm, params) for pos, nm, params in functions}

        for pos, kind_marker in entries:
            if kind_marker == "container":
                kind, cname, cdoc = container_by_pos[pos]
                lines.append(f"{kind} {cname}: {cdoc}".rstrip(": "))
            else:
                fname, fparams = function_by_pos[pos]
                owner = self._enclosing_container(source, containers, pos)
                doc = self._doc_for(source, docblocks, pos)
                if owner is not None:
                    lines.append(
                        f"    def {fname}({fparams}): {doc}".rstrip(": ")
                    )
                else:
                    lines.append(
                        f"function {fname}({fparams}): {doc}".rstrip(": ")
                    )

        first_keyword_pos = min(
            (pos for pos, _ in entries), default=len(source)
        )
        summary = ""
        if docblocks and docblocks[0][0] < first_keyword_pos:
            summary = docblocks[0][2]
        return summary, lines

    @staticmethod
    def _doc_for(
        source: str, docblocks: list[tuple[int, int, str]], decl_start: int
    ) -> str:
        """PHPDoc first line immediately preceding ``decl_start``, if any."""
        best = ""
        best_end = -1
        for _start, end, first_line in docblocks:
            if end <= decl_start and end > best_end:
                gap = source[end:decl_start]
                if _gap_is_modifiers_only(gap):
                    best_end = end
                    best = first_line
        return best

    @staticmethod
    def _enclosing_container(
        source: str,
        containers: list[tuple[int, str, str, str]],
        fn_pos: int,
    ) -> str | None:
        """Name of the container whose body directly encloses ``fn_pos``.

        Heuristic brace-depth check: the nearest preceding container whose
        interior depth (its own depth-before + 1) equals the function's
        depth-before is treated as its owner.
        """
        fn_depth = source.count("{", 0, fn_pos) - source.count("}", 0, fn_pos)
        best_name: str | None = None
        best_pos = -1
        for pos, _kind, cname, _doc in containers:
            if pos >= fn_pos:
                continue
            container_depth = source.count("{", 0, pos) - source.count("}", 0, pos)
            if container_depth + 1 == fn_depth and pos > best_pos:
                best_pos = pos
                best_name = cname
        return best_name

    def _outline_treesitter(self, parser: Any, source: str) -> tuple[str, list[str]]:
        """Best-effort tree-sitter outline using the ``tree_sitter_php``
        grammar's node types. Exercised only when the optional
        ``ai-parrot[wiki-languages]`` extra is installed; any structural
        mismatch degrades to an empty outline via the caller's
        ``except Exception`` guard rather than raising.
        """
        tree = parser.parse(source.encode("utf-8"))
        root = tree.root_node
        lines: list[str] = []

        def _text(node: Any) -> str:
            return source.encode("utf-8")[node.start_byte:node.end_byte].decode(
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

        container_types = {
            "class_declaration": "class",
            "interface_declaration": "interface",
            "trait_declaration": "trait",
            "enum_declaration": "enum",
        }

        def _walk(node: Any, in_container: bool) -> None:
            for child in node.children:
                if child.type in container_types:
                    kind = container_types[child.type]
                    cname = _name_of(child)
                    doc = _leading_doc(child)
                    lines.append(f"{kind} {cname}: {doc}".rstrip(": "))
                    _walk(child, in_container=True)
                elif child.type in ("function_definition", "method_declaration"):
                    fname = _name_of(child)
                    params_node = child.child_by_field_name("parameters")
                    params = _text(params_node).strip("()") if params_node else ""
                    doc = _leading_doc(child)
                    if in_container:
                        lines.append(f"    def {fname}({params}): {doc}".rstrip(": "))
                    else:
                        lines.append(f"function {fname}({params}): {doc}".rstrip(": "))
                    _walk(child, in_container=in_container)
                else:
                    _walk(child, in_container=in_container)

        _walk(root, in_container=False)

        summary = ""
        first_child = root.children[0] if root.children else None
        if first_child is not None and first_child.type == "comment":
            text = _text(first_child)
            if text.startswith("/**"):
                body = text[3:-2] if text.endswith("*/") else text[3:]
                summary = _docblock_first_line(body)
        return summary, lines

    # -- reference resolution ----------------------------------------------

    def build_reference_index(self, rel_paths: Iterable[str]) -> Any:
        """Build a ``(psr4_map, file_set)`` pair over the repo file list.

        ``psr4_map`` maps a PSR-4 namespace prefix to its directory
        prefix, parsed from a ``composer.json`` in ``rel_paths`` when one
        is present and readable; it is empty (never raises) when absent,
        unreadable, or malformed — :meth:`resolve_import` then falls back
        to namespace-tail matching.

        Args:
            rel_paths: POSIX-style relative paths of every scanned file.

        Returns:
            Opaque ``(dict[str, str], frozenset[str])`` index.
        """
        file_set = frozenset(PurePosixPath(p).as_posix() for p in rel_paths)
        return (self._load_psr4_map(file_set), file_set)

    @staticmethod
    def _load_psr4_map(file_set: frozenset[str]) -> dict[str, str]:
        """Parse the first readable ``composer.json``'s PSR-4 autoload map.

        ``build_reference_index`` only receives relative-path strings — no
        repository root (the :class:`LanguageScanner` ABC is frozen) — so
        ``composer.json`` is read relative to the root
        :func:`~parrot.knowledge.wiki.languages.set_scan_root` recorded for
        the scan in progress. Falls back to the process CWD (the pre-fix
        behaviour) when no scan has set one, e.g. a scanner method called
        directly outside :func:`~parrot.knowledge.wiki.repo_scan.scan_repository`.
        """
        # Local import: `parrot.knowledge.wiki.languages` (the package
        # __init__) imports this module during its own initialization, so
        # a module-level import of a sibling name from it here would be
        # circular. By call time, package init has long finished.
        from parrot.knowledge.wiki.languages import get_scan_root

        scan_root = get_scan_root()
        for candidate in sorted(file_set):
            if PurePosixPath(candidate).name != "composer.json":
                continue
            path = (scan_root / candidate) if scan_root is not None else Path(candidate)
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                logger.debug("Could not read/parse %s: %s", candidate, exc)
                continue
            psr4 = (data.get("autoload") or {}).get("psr-4") or {}
            if not isinstance(psr4, dict) or not psr4:
                continue
            base_dir = PurePosixPath(candidate).parent.as_posix()
            result: dict[str, str] = {}
            for namespace, directory in psr4.items():
                if not isinstance(directory, str):
                    continue
                joined = directory if base_dir == "." else f"{base_dir}/{directory}"
                result[namespace] = joined.rstrip("/") + "/"
            if result:
                return result
        return {}

    def resolve_import(
        self, spec: str, from_file: str, index: Any
    ) -> str | None:
        """Resolve a ``use`` namespace or a ``require``/``include`` path.

        Args:
            spec: Raw import specifier from :meth:`outline` — either a
                namespaced ``use`` target (contains ``\\``) or a bare
                ``require``/``include`` path.
            from_file: POSIX-relative path of the importing file.
            index: The ``(psr4_map, file_set)`` pair from
                :meth:`build_reference_index`.

        Returns:
            The resolved rel path, or ``None`` when unresolved.
        """
        psr4_map, file_set = index
        if "\\" in spec:
            clean = spec.strip("\\")
            for ns_prefix, dir_prefix in psr4_map.items():
                if clean.startswith(ns_prefix):
                    tail = clean[len(ns_prefix):].replace("\\", "/")
                    candidate = f"{dir_prefix.rstrip('/')}/{tail}.php".lstrip("/")
                    if candidate in file_set:
                        return candidate
            tail_name = clean.rsplit("\\", 1)[-1]
            matches = sorted(
                p for p in file_set
                if PurePosixPath(p).suffix == ".php"
                and PurePosixPath(p).stem == tail_name
            )
            return matches[0] if matches else None

        base = PurePosixPath(from_file).parent
        candidate = _normalize_posix(base / spec.lstrip("/"))
        return candidate if candidate in file_set else None

    @property
    def mode(self) -> str:
        """``"tree-sitter"`` when the optional grammar loads, else
        ``"heuristic"``."""
        if treesitter.get_parser("php") is not None:
            return "tree-sitter"
        return "heuristic"
