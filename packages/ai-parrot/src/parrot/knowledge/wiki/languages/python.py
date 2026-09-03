"""Python plugin for the wiki repo scanner.

Relocates the pre-existing ``ast``-based outline/import extraction from
``repo_scan.py`` behind the :class:`LanguageScanner` ABC (FEAT-394). The
logic is moved verbatim — including its ``rstrip(": ")`` quirk — so
output stays byte-identical to the legacy ``_python_outline``/
``_module_index`` functions that still live in ``repo_scan.py`` until
TASK-2012 wires this plugin in.
"""

from __future__ import annotations

import ast
from collections.abc import Iterable
from pathlib import PurePosixPath
from typing import Any, ClassVar

from parrot.knowledge.wiki.languages import astgrep
from parrot.knowledge.wiki.languages.base import LanguageOutline, LanguageScanner
from parrot.knowledge.wiki.languages.render import structural_enabled
from parrot.knowledge.wiki.symbols import (
    SymbolKind,
    SymbolRecord,
    SymbolRef,
    sha1_of_text,
)

#: Maximum symbol nesting depth persisted for Python files (FEAT-498):
#: ``1`` = top-level classes/functions only, ``2`` (default) = direct
#: class members too, ``3+`` = nested defs. Bound to
#: ``WikiProjectConfig.symbol_depth`` by the scan entry point —
#: ``LanguageScanner.outline(source, rel_path)`` is a frozen two-argument
#: signature (TASK-2010) with no room for a config parameter, so this
#: module-level flag is read instead (same pattern as
#: ``languages/render.py``'s ``structural_enabled()``).
_symbol_depth: int = 2


def set_symbol_depth(depth: int) -> None:
    """Set the maximum symbol nesting depth for Python (FEAT-498).

    Args:
        depth: New value, normally ``WikiProjectConfig.symbol_depth``.
    """
    global _symbol_depth
    _symbol_depth = depth


def get_symbol_depth() -> int:
    """Return the maximum symbol nesting depth for Python (FEAT-498).

    Returns:
        ``2`` by default, or the value set by :func:`set_symbol_depth`.
    """
    return _symbol_depth


def _first_line(text: str, limit: int = 240) -> str:
    """Return the first non-empty line of ``text``, truncated."""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped[:limit]
    return ""


def _byte_offsets(source: str) -> list[int]:
    """Cumulative UTF-8 byte offset of each line start.

    Args:
        source: Full file source text.

    Returns:
        ``offs`` where ``offs[i]`` is the byte offset of the start of
        line ``i + 1`` (1-based ``lineno``); ``offs[0] == 0``.
    """
    offs = [0]
    total = 0
    for line in source.splitlines(keepends=True):
        total += len(line.encode("utf-8"))
        offs.append(total)
    return offs


#: The three node types stdlib ``ast`` uses for a def statement.
_DefNode = ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef


def _node_byte_range(node: _DefNode, offsets: list[int]) -> tuple[int, int]:
    """Byte ``(start, end)`` of ``node`` in the source ``offsets`` was built from.

    ``col_offset``/``end_col_offset`` are already UTF-8 byte offsets in
    CPython (>=3.8), so no re-encoding of the column is needed — only the
    line-start offset must be looked up.
    """
    start = offsets[node.lineno - 1] + node.col_offset
    end = offsets[node.end_lineno - 1] + node.end_col_offset  # type: ignore[operator]
    return start, end


def _decorators(node: _DefNode) -> list[str]:
    """``ast.unparse`` of every decorator on a class/function def node."""
    return [ast.unparse(d) for d in node.decorator_list]


def _signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    """Full parameter (+ return type) signature, as written.

    Unlike the outline's own ``_sig()`` (arg names only, for the rendered
    ``## API outline`` line), this is the full ``ast.unparse`` of the
    node's ``args``, plus ``" -> " + unparse(returns)`` when annotated.
    """
    sig = f"({ast.unparse(node.args)})"
    if node.returns is not None:
        sig = f"{sig} -> {ast.unparse(node.returns)}"
    return sig


def _build_symbol(
    node: _DefNode,
    *,
    kind: SymbolKind,
    qualname: str,
    parent: str | None,
    depth: int,
    rel_path: str,
    source: str,
    offsets: list[int],
) -> SymbolRecord:
    """Build a :class:`SymbolRecord` for one class/function def node."""
    doc = _first_line(ast.get_docstring(node) or "")
    start_byte, end_byte = _node_byte_range(node, offsets)
    segment = ast.get_source_segment(source, node) or ""
    signature = "" if isinstance(node, ast.ClassDef) else _signature(node)
    return SymbolRecord(
        rel_path=rel_path,
        language="python",
        kind=kind,
        name=node.name,
        qualname=qualname,
        parent=parent,
        signature=signature,
        doc=doc,
        exported=not node.name.startswith("_"),
        is_async=isinstance(node, ast.AsyncFunctionDef),
        start_line=node.lineno,
        end_line=node.end_lineno,  # type: ignore[arg-type]
        start_byte=start_byte,
        end_byte=end_byte,
        node_kind=type(node).__name__,
        decorators=_decorators(node),
        content_hash=sha1_of_text(segment),
        depth=depth,
    )


def _collect_symbols(
    nodes: list[ast.stmt],
    *,
    parent: str | None,
    in_class: bool,
    depth: int,
    max_depth: int,
    rel_path: str,
    source: str,
    offsets: list[int],
) -> list[SymbolRecord]:
    """Recursively collect ``SymbolRecord``s from a list of statements.

    Args:
        nodes: Statement list to scan (a module body, class body, or
            function body).
        parent: Qualname of the immediately enclosing class/function, or
            ``None`` at module level.
        in_class: Whether ``nodes`` is a class body — determines whether
            an immediate function child is a ``METHOD`` or a ``FUNCTION``.
        depth: Nesting depth of ``nodes`` itself (``1`` = module level).
        max_depth: Symbols whose depth would exceed this are dropped
            (`WikiProjectConfig.symbol_depth` via :func:`get_symbol_depth`).
        rel_path: POSIX path relative to the repository root.
        source: Full file source text.
        offsets: Cumulative line-start byte offsets (:func:`_byte_offsets`).

    Returns:
        Symbol records for every class/function def in ``nodes`` and,
        depth permitting, their nested defs.
    """
    if depth > max_depth:
        return []
    symbols: list[SymbolRecord] = []
    for node in nodes:
        if isinstance(node, ast.ClassDef):
            qualname = f"{parent}.{node.name}" if parent else node.name
            symbols.append(
                _build_symbol(
                    node,
                    kind=SymbolKind.CLASS,
                    qualname=qualname,
                    parent=parent,
                    depth=depth,
                    rel_path=rel_path,
                    source=source,
                    offsets=offsets,
                )
            )
            symbols.extend(
                _collect_symbols(
                    node.body,
                    parent=qualname,
                    in_class=True,
                    depth=depth + 1,
                    max_depth=max_depth,
                    rel_path=rel_path,
                    source=source,
                    offsets=offsets,
                )
            )
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            qualname = f"{parent}.{node.name}" if parent else node.name
            kind = SymbolKind.METHOD if in_class else SymbolKind.FUNCTION
            symbols.append(
                _build_symbol(
                    node,
                    kind=kind,
                    qualname=qualname,
                    parent=parent,
                    depth=depth,
                    rel_path=rel_path,
                    source=source,
                    offsets=offsets,
                )
            )
            symbols.extend(
                _collect_symbols(
                    node.body,
                    parent=qualname,
                    in_class=False,
                    depth=depth + 1,
                    max_depth=max_depth,
                    rel_path=rel_path,
                    source=source,
                    offsets=offsets,
                )
            )
    return symbols


class PythonScanner(LanguageScanner):
    """Deep extractor for ``.py``/``.pyi`` files using stdlib ``ast``."""

    name: ClassVar[str] = "python"
    suffixes: ClassVar[frozenset[str]] = frozenset({".py", ".pyi"})

    def outline(self, source: str, rel_path: str) -> LanguageOutline:
        """Extract summary, API outline, and imports from Python source.

        Args:
            source: Raw Python source text.
            rel_path: POSIX-style path relative to the repository root
                (unused by this scanner — kept for interface parity).

        Returns:
            The extracted :class:`LanguageOutline`. On a syntax error
            every field degrades to empty.
        """
        try:
            tree = ast.parse(source, filename=rel_path or "<unknown>")
        except (SyntaxError, ValueError):
            return LanguageOutline()

        summary = _first_line(ast.get_docstring(tree) or "")
        outline: list[str] = []
        imports: list[str] = []

        def _sig(node: ast.AST) -> str:
            args = getattr(node, "args", None)
            names = [a.arg for a in args.args] if args else []
            return f"({', '.join(names)})"

        for node in tree.body:
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                imports.append(node.module)
            elif isinstance(node, ast.ClassDef):
                doc = _first_line(ast.get_docstring(node) or "")
                outline.append(f"class {node.name}: {doc}".rstrip(": "))
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        idoc = _first_line(ast.get_docstring(item) or "")
                        outline.append(f"    def {item.name}{_sig(item)}: {idoc}".rstrip(": "))
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                doc = _first_line(ast.get_docstring(node) or "")
                outline.append(f"def {node.name}{_sig(node)}: {doc}".rstrip(": "))

        # FEAT-498: SymbolRecords are always derived from `ast` — Python
        # `sym:` pages exist without any optional extra. ast-grep, when
        # available, only ever *adds* `calls` refs; it never replaces
        # this symbol list (resolved decision, spec §2 "Python exception").
        offsets = _byte_offsets(source)
        symbols = _collect_symbols(
            tree.body,
            parent=None,
            in_class=False,
            depth=1,
            max_depth=get_symbol_depth(),
            rel_path=rel_path,
            source=source,
            offsets=offsets,
        )
        refs: list[SymbolRef] = []
        if structural_enabled():
            structural = astgrep.extract(source, "python", rel_path)
            if structural is not None:
                refs = structural.refs

        return LanguageOutline(
            summary=summary,
            outline=outline,
            imports=imports,
            symbols=symbols,
            refs=refs,
        )

    def build_reference_index(self, rel_paths: Iterable[str]) -> Any:
        """Map importable dotted module names to relative file paths.

        Handles both flat layouts (``pkg/mod.py`` -> ``pkg.mod``) and src
        layouts (``packages/x/src/pkg/mod.py`` -> ``pkg.mod`` — everything
        up to and including a ``src`` component is stripped).

        Args:
            rel_paths: POSIX-style relative paths of every scanned file.

        Returns:
            A ``dict[str, str]`` mapping dotted module name to rel path.
        """
        index: dict[str, str] = {}
        for rel in rel_paths:
            p = PurePosixPath(rel)
            if p.suffix not in {".py", ".pyi"}:
                continue
            parts = list(p.parts)
            if "src" in parts:
                parts = parts[parts.index("src") + 1 :]
            if not parts:
                continue
            parts[-1] = PurePosixPath(parts[-1]).stem
            if parts[-1] == "__init__":
                parts = parts[:-1]
            if parts:
                index.setdefault(".".join(parts), rel)
        return index

    def resolve_import(self, spec: str, from_file: str, index: Any) -> str | None:
        """Resolve a dotted module specifier via dotted-prefix matching.

        Args:
            spec: Dotted module name (e.g. ``"pkg.mod"``).
            from_file: POSIX-relative path of the importing file (edges
                to self are dropped).
            index: The ``dict[str, str]`` built by
                :meth:`build_reference_index`.

        Returns:
            The resolved rel path, or ``None`` when unresolved or when
            the only match is the importing file itself.
        """
        parts = spec.split(".")
        target: str | None = None
        for depth in range(len(parts), 0, -1):
            target = index.get(".".join(parts[:depth]))
            if target:
                break
        if target and target != from_file:
            return target
        return None

    @property
    def mode(self) -> str:
        """Always ``"ast"`` — Python never uses tree-sitter or heuristics."""
        return "ast"
