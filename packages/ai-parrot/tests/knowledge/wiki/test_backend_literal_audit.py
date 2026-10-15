"""No ``"arangodb"`` literal meaning "server-hosted" survives (FEAT-540 M7)."""

from __future__ import annotations

import ast
from pathlib import Path


_REPO_ROOT = Path(__file__).parents[5]
_AUDITED_FILES = {
    "packages/ai-parrot/src/parrot/knowledge/wiki/cli.py": {
        "_open_store",
        "_open_sources",
        "_resolve_read_store",
        "_probe_backend_reachable",
    },
    "packages/ai-parrot/src/parrot/knowledge/wiki/sync.py": {"_open_plane", "_open_remote"},
    "packages/ai-parrot/src/parrot/knowledge/wiki/federation.py": {
        "_open_project_plane",
        "open_namespace_store",
    },
    "packages/ai-parrot/src/parrot/knowledge/wiki/sources.py": {"SourceCollectionManager"},
    "packages/ai-parrot-tools/src/parrot_tools/wiki/toolkit.py": {"LLMWikiToolkit.__init__"},
}


class _ArangoComparisonVisitor(ast.NodeVisitor):
    """Collect comparisons against the Arango backend literal by function."""

    def __init__(self) -> None:
        """Initialise an empty comparison collection."""
        self.functions: list[str] = []
        self.comparisons: list[tuple[str, int]] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        """Visit methods with their containing class name."""
        self.functions.append(node.name)
        self.generic_visit(node)
        self.functions.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        """Visit a function while retaining its qualified name."""
        self.functions.append(node.name)
        self.generic_visit(node)
        self.functions.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        """Visit an async function while retaining its qualified name."""
        self.visit_FunctionDef(node)

    def visit_Compare(self, node: ast.Compare) -> None:
        """Record comparisons that directly name the Arango backend."""
        if any(isinstance(item, ast.Constant) and item.value == "arangodb" for item in node.comparators):
            self.comparisons.append((".".join(self.functions), node.lineno))
        self.generic_visit(node)


def test_arango_comparisons_are_limited_to_arango_specific_paths() -> None:
    """Ensure server-hosted branches use ``is_server_backend`` instead of names."""
    violations: list[str] = []
    for relative_path, allowed_functions in _AUDITED_FILES.items():
        visitor = _ArangoComparisonVisitor()
        visitor.visit(ast.parse((_REPO_ROOT / relative_path).read_text()))
        for function, line in visitor.comparisons:
            is_allowed_source_path = any(function.startswith(prefix + ".") for prefix in allowed_functions)
            if function not in allowed_functions and not is_allowed_source_path:
                violations.append(f"{relative_path}:{line} ({function})")
    assert not violations, "unexpected server-hosted Arango comparison(s): " + ", ".join(violations)


def test_backend_choice_reads_the_registry_at_conversion_time() -> None:
    """Ensure the CLI's custom Click type consults ``wiki_backend_names``."""
    tree = ast.parse(
        (_REPO_ROOT / "packages/ai-parrot/src/parrot/knowledge/wiki/cli.py").read_text(),
    )
    backend_choice = next(
        node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "_BackendChoice"
    )
    assert any(
        isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "wiki_backend_names"
        for node in ast.walk(backend_choice)
    )
