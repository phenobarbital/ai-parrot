"""Regression tests: the ``wikitoolkit`` import chain's third-party deps
are declared in core ``dependencies`` (FEAT-471).

``wikitoolkit`` ships in core ``ai-parrot`` (``[project.scripts]``) but its
import chain (``wiki/cli.py`` -> ``wiki/documents.py`` ->
``graphindex/__init__.py`` -> ``signals.py`` / ``communities.py`` /
``builder.py`` / ``sqlite_reader.py`` / ``assemble.py``) imports several
third-party packages unconditionally at module level. If one of those
packages is ever declared only in an optional extra (as ``rustworkx``,
``networkx``, ``pathspec``, ``aiosqlite`` and ``orjson`` originally were),
a bare ``uv pip install ai-parrot`` / ``uv sync`` crashes with
``ModuleNotFoundError`` on every ``wikitoolkit`` subcommand.

These tests statically parse the chain files and the ``pyproject.toml``
declarations to guard against that defect recurring, and independently
confirm the chain actually imports in a fresh interpreter.
"""

import ast
import re
import subprocess
import sys
import tomllib
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PYPROJECT = REPO / "packages/ai-parrot/pyproject.toml"

CHAIN_FILES = [
    "packages/ai-parrot/src/parrot/knowledge/wiki/cli.py",
    "packages/ai-parrot/src/parrot/knowledge/wiki/documents.py",
    "packages/ai-parrot/src/parrot/knowledge/graphindex/__init__.py",
    "packages/ai-parrot/src/parrot/knowledge/graphindex/signals.py",
    "packages/ai-parrot/src/parrot/knowledge/graphindex/communities.py",
    "packages/ai-parrot/src/parrot/knowledge/graphindex/builder.py",
    "packages/ai-parrot/src/parrot/knowledge/graphindex/sqlite_reader.py",
    "packages/ai-parrot/src/parrot/knowledge/graphindex/assemble.py",
]

# Import name -> distribution name, for import names whose PyPI
# distribution name differs from the module name.
NAME_MAP = {
    "yaml": "pyyaml",
    "click": "click",
    "pydantic": "pydantic",
    "rustworkx": "rustworkx",
    "networkx": "networkx",
    "pathspec": "pathspec",
    "aiosqlite": "aiosqlite",
    "orjson": "orjson",
}

# Third-party module-level imports on the chain that are satisfied
# transitively by other core dependencies rather than being declared
# directly (e.g. "aiohttp" via aiohttp-swagger3/aiohttp-cors/navigator-api,
# "numpy" via pandas/rustworkx itself). Not part of the FEAT-471 defect —
# these were already transitively guaranteed before this feature.
KNOWN_TRANSITIVE = {"aiohttp", "numpy"}

# First-party (not third-party) top-level module names to ignore.
FIRST_PARTY = {"parrot", "parrot_tools"}


def _req_name(req: str) -> str:
    """Normalize a PEP 508 requirement string to a bare distribution name.

    Args:
        req: A requirement string, e.g. ``"rustworkx>=0.15"``.

    Returns:
        The distribution name, lowercased with underscores folded to
        hyphens, e.g. ``"rustworkx"``.
    """
    name = re.split(r"[<>=!~;\[ ]", req.strip(), 1)[0]
    return name.lower().replace("_", "-")


def _module_level_imports(path: Path) -> set[str]:
    """Collect top-level ``import`` / ``from ... import`` module names.

    Only statements at the module's top level are considered — anything
    nested inside ``if``, ``try``, or function/class bodies is skipped,
    matching the "unguarded at import time" definition used by the spec.

    Args:
        path: Path to the Python source file to parse.

    Returns:
        The set of top-level module names (first path segment only).
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module.split(".")[0])
    return names


def _core_dependencies() -> list[str]:
    """Return the raw core ``dependencies`` requirement strings."""
    data = tomllib.load(PYPROJECT.open("rb"))
    return data["project"]["dependencies"]


def _graphindex_extra() -> list[str]:
    """Return the raw ``graphindex`` optional-dependency requirement strings."""
    data = tomllib.load(PYPROJECT.open("rb"))
    return data["project"]["optional-dependencies"]["graphindex"]


def test_wiki_cli_imports_in_subprocess():
    """``import parrot.knowledge.wiki.cli`` succeeds in a fresh interpreter."""
    result = subprocess.run(
        [sys.executable, "-c", "import parrot.knowledge.wiki.cli"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_wiki_chain_third_party_imports_are_core_deps():
    """Every third-party module-level import on the wikitoolkit chain is a core dep."""
    core_names = {_req_name(dep) for dep in _core_dependencies()}
    stdlib_names = set(getattr(sys, "stdlib_module_names", set()))

    for rel_path in CHAIN_FILES:
        path = REPO / rel_path
        module_names = _module_level_imports(path)
        for name in module_names:
            if name in stdlib_names:
                continue
            if name in FIRST_PARTY:
                continue
            if name.startswith("_"):
                continue
            if name in KNOWN_TRANSITIVE:
                continue
            dist_name = NAME_MAP.get(name, name.lower().replace("_", "-"))
            assert dist_name in core_names, (
                f"{rel_path}: module-level import {name!r} "
                f"(distribution {dist_name!r}) is not declared in "
                f"packages/ai-parrot/pyproject.toml core dependencies"
            )


def test_graphindex_extra_has_no_duplicates_of_core():
    """No package is declared both in core dependencies and the graphindex extra."""
    core_names = {_req_name(dep) for dep in _core_dependencies()}
    extra_names = {_req_name(dep) for dep in _graphindex_extra()}
    assert not (core_names & extra_names), core_names & extra_names
