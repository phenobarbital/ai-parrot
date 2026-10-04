"""knowledge/common must stay domain-neutral (FEAT-601 M1)."""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[5]
COMMON_SRC = REPO_ROOT / "packages" / "ai-parrot" / "src" / "parrot" / "knowledge" / "common"
FORBIDDEN = ("parrot.knowledge.contracts", "parrot_tools", "asyncpg", "arango")
_PACKAGE = ("parrot", "knowledge", "common")


def _imported_modules(path: Path) -> set[str]:
    """Absolute module names imported by one file (relative imports resolved against knowledge.common)."""
    tree = ast.parse(path.read_text())
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0:
                if node.module:
                    names.add(node.module)
                continue
            base = _PACKAGE[: len(_PACKAGE) - node.level + 1]
            if node.module:
                names.add(".".join((*base, *node.module.split("."))))
            else:
                names.update(".".join((*base, alias.name)) for alias in node.names)
    return names


def test_common_import_boundary() -> None:
    """Common modules do not import contracts, satellites, or database drivers."""
    assert COMMON_SRC.is_dir()
    for module_path in COMMON_SRC.glob("*.py"):
        for name in _imported_modules(module_path):
            assert not name.startswith(FORBIDDEN), f"{module_path.name} -> {name}"
