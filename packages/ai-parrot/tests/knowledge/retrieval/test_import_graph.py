"""Import-graph assertion (spec §13, AC #1): L0 is consumed read-only.

"``parrot.knowledge.retrieval`` exists and imports cleanly with no
dependency on ``parrot.knowledge.graphindex`` write paths — L0 is
consumed read-only (§1.2), verified by an import-graph assertion."

This test statically scans every source file under
``parrot/knowledge/retrieval`` (never test files — fixtures legitimately
build L0 test data via `SQLitePersistence.persist_graph`, which is not a
production code path) for references to L0's write-side surface:
`SQLitePersistence.persist_graph`/`replace_document_slice`, and the
write-orchestrating `GraphIndexBuilder`/`GraphPublisher` classes.
"""

from __future__ import annotations

import ast
from pathlib import Path

import parrot.knowledge.retrieval as retrieval_pkg

#: L0 write-path symbols this package must never import or call (spec §1.2).
_WRITE_PATH_NAMES = frozenset(
    {
        "persist_graph",
        "replace_document_slice",
        "GraphIndexBuilder",
        "GraphPublisher",
    }
)


def _iter_retrieval_source_files() -> list[Path]:
    pkg_dir = Path(retrieval_pkg.__file__).parent
    return sorted(pkg_dir.rglob("*.py"))


def test_retrieval_package_imports_cleanly() -> None:
    """AC #1, part 1: the package itself imports with no error."""
    import importlib

    importlib.reload(retrieval_pkg)


def test_no_l0_write_path_references_in_source() -> None:
    """AC #1, part 2: no source file references an L0 write-path symbol.

    Uses `ast` (not a substring grep) so a mention inside a docstring or
    comment — which several files legitimately have, explaining WHY a
    write path is out of scope — does not false-positive.
    """
    violations: list[str] = []

    for path in _iter_retrieval_source_files():
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        for node in ast.walk(tree):
            name = None
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    if alias.name in _WRITE_PATH_NAMES:
                        name = alias.name
            elif isinstance(node, ast.Name) and node.id in _WRITE_PATH_NAMES:
                name = node.id
            elif isinstance(node, ast.Attribute) and node.attr in _WRITE_PATH_NAMES:
                name = node.attr
            if name is not None:
                violations.append(f"{path.name}:{node.lineno}: references {name!r}")

    assert not violations, "L0 write-path references found:\n" + "\n".join(violations)
