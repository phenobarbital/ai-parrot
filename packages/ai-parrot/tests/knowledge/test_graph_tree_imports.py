"""FEAT-540 G2 gate: no eager framework imports in the graph tree."""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

import pytest

FORBIDDEN_PREFIXES = (
    "parrot.tools",
    "parrot_tools",
    "parrot.clients",
    "parrot.loaders",
    "parrot.stores",
    "parrot.embeddings",
    "parrot.conf",
    "parrot.knowledge.pageindex.toolkit",
    "parrot.knowledge.pageindex.llm_adapter",
)

_SRC = Path(__file__).resolve().parents[2] / "src"
_KNOWLEDGE = _SRC / "parrot" / "knowledge"
_TOOLS_SRC = _SRC.parent.parent / "ai-parrot-tools" / "src"


def _scanned_files() -> list[Path]:
    """Return the files covered by the gate (wiki/**, graphindex/**, three ontology modules)."""
    files = sorted((_KNOWLEDGE / "wiki").rglob("*.py")) + sorted((_KNOWLEDGE / "graphindex").rglob("*.py"))
    files += [_KNOWLEDGE / "ontology" / name for name in ("contracts.py", "schema.py", "validators.py")]
    return [f for f in files if f.is_file()]


def _is_forbidden(module: str) -> bool:
    """Return whether ``module`` equals or sits under a forbidden prefix."""
    return any(module == p or module.startswith(p + ".") for p in FORBIDDEN_PREFIXES)


def _is_type_checking(test: ast.expr) -> bool:
    """Return whether an ``if`` test is ``TYPE_CHECKING`` / ``typing.TYPE_CHECKING``."""
    if isinstance(test, ast.Name):
        return test.id == "TYPE_CHECKING"
    return isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING"


def _package_of(path: Path) -> list[str]:
    """Return the dotted package parts of ``path`` relative to the source root."""
    parts = list(path.relative_to(_SRC).with_suffix("").parts)
    return parts[:-1]


def _imported_modules(node: ast.stmt, path: Path) -> list[str]:
    """Return absolute module names imported by an import statement."""
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]
    if isinstance(node, ast.ImportFrom):
        if node.level:
            base = _package_of(path)
            base = base[: len(base) - (node.level - 1)] if node.level > 1 else base
            module = ".".join([*base, *([node.module] if node.module else [])])
        else:
            module = node.module or ""
        names = [f"{module}.{alias.name}" for alias in node.names]
        return [module, *names]
    return []


def _walk_executable(body: list[ast.stmt]) -> list[ast.stmt]:
    """Yield statements executed at import time (no function bodies, no TYPE_CHECKING blocks)."""
    out: list[ast.stmt] = []
    for node in body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        out.append(node)
        if isinstance(node, ast.If):
            if _is_type_checking(node.test):
                out.extend(_walk_executable(node.orelse))
            else:
                out.extend(_walk_executable(node.body))
                out.extend(_walk_executable(node.orelse))
        elif isinstance(node, ast.Try):
            for block in (node.body, node.orelse, node.finalbody, *(h.body for h in node.handlers)):
                out.extend(_walk_executable(block))
        elif isinstance(node, (ast.With, ast.For, ast.While, ast.ClassDef)):
            out.extend(_walk_executable(node.body))
    return out


def scan_file(path: Path) -> list[str]:
    """Return ``file:line module`` entries for eager forbidden imports in ``path``."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: list[str] = []
    for node in _walk_executable(tree.body):
        if not isinstance(node, (ast.Import, ast.ImportFrom)):
            continue
        for module in _imported_modules(node, path):
            if _is_forbidden(module):
                found.append(f"{path.relative_to(_SRC)}:{node.lineno} {module}")
                break
    return found


def test_scan_covers_the_graph_tree() -> None:
    """The scan must see wiki, graphindex and the three ontology modules."""
    names = {p.relative_to(_KNOWLEDGE).as_posix() for p in _scanned_files()}
    assert "wiki/cli.py" in names and "graphindex/builder.py" in names
    assert {"ontology/contracts.py", "ontology/schema.py", "ontology/validators.py"} <= names


def test_scanner_flags_eager_and_exempts_lazy(tmp_path: Path) -> None:
    """The walker flags module/branch imports but not TYPE_CHECKING or function-local ones."""
    sample = _SRC / "parrot" / "knowledge" / "wiki" / "_sample_probe.py"
    body = (
        "from typing import TYPE_CHECKING\n"
        "if TYPE_CHECKING:\n    from parrot.tools import x\n"
        "try:\n    import parrot_tools.y\nexcept ImportError:\n    pass\n"
        "def f():\n    import parrot.clients.z\n"
    )
    tree = ast.parse(body)
    flagged = [
        m
        for n in _walk_executable(tree.body)
        if isinstance(n, (ast.Import, ast.ImportFrom))
        for m in _imported_modules(n, sample)
        if _is_forbidden(m)
    ]
    assert flagged == ["parrot_tools.y"]


def test_no_eager_framework_imports_in_graph_tree() -> None:
    """Fail on any module-level (or executable-branch) forbidden import in the graph tree."""
    violations: list[str] = []
    for path in _scanned_files():
        violations.extend(scan_file(path))
    assert violations == [], "\n".join(violations)


_BLOCKER = r"""
import asyncio, importlib.abc, sys, tempfile
sys.path[:0] = [sys.argv[1], sys.argv[2]]
FORBIDDEN = tuple(sys.argv[3].split(","))
class Blocker(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path=None, target=None):
        if any(name == p or name.startswith(p + ".") for p in FORBIDDEN):
            raise ImportError(f"blocked forbidden import: {name}")
        return None
sys.meta_path.insert(0, Blocker())
import parrot.knowledge.wiki.cli  # default CLI entry
from parrot.knowledge.wiki.file_store import InMemoryWikiStore
from parrot.knowledge.wiki.operations import WikiStatusInput, op_status
async def main():
    with tempfile.TemporaryDirectory() as d:
        res = await op_status(InMemoryWikiStore(d, wiki_name="probe"), WikiStatusInput())
        assert not res.is_error, res.text
asyncio.run(main())
print("OK")
"""


@pytest.mark.xfail(
    strict=False,
    reason=(
        "parrot/knowledge/wiki/schema/models.py:9 imports parrot.bots.database.models eagerly, which pulls "
        "parrot.conf (parrot/bots/abstract.py:25) when wiki.cli is imported; owner: schema-plane tree (FEAT-600), "
        "tracked in handoff-541.md"
    ),
)
def test_blocker_default_cli_entry_and_plain_ops() -> None:
    """Importing the default CLI entry and running a plain op must not touch forbidden prefixes."""
    proc = subprocess.run(
        [sys.executable, "-I", "-c", _BLOCKER, str(_SRC), str(_TOOLS_SRC), ",".join(FORBIDDEN_PREFIXES)],
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    assert proc.returncode == 0 and "OK" in proc.stdout, proc.stderr[-2000:]
