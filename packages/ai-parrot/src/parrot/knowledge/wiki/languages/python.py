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

from parrot.knowledge.wiki.languages.base import LanguageOutline, LanguageScanner


def _first_line(text: str, limit: int = 240) -> str:
    """Return the first non-empty line of ``text``, truncated."""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped[:limit]
    return ""


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
                        outline.append(
                            f"    def {item.name}{_sig(item)}: {idoc}".rstrip(": ")
                        )
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                doc = _first_line(ast.get_docstring(node) or "")
                outline.append(f"def {node.name}{_sig(node)}: {doc}".rstrip(": "))
        return LanguageOutline(summary=summary, outline=outline, imports=imports)

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
                parts = parts[parts.index("src") + 1:]
            if not parts:
                continue
            parts[-1] = PurePosixPath(parts[-1]).stem
            if parts[-1] == "__init__":
                parts = parts[:-1]
            if parts:
                index.setdefault(".".join(parts), rel)
        return index

    def resolve_import(
        self, spec: str, from_file: str, index: Any
    ) -> str | None:
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
