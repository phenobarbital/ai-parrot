"""Packaging and dependency-boundary tests for FEAT-539 (TASK-3052).

``rapidfuzz>=3.0`` is the *only* dependency this feature adds, and only to
the core ``graphindex`` optional extra. These tests also pin the boundary
rules the spec relies on: core contracts modules never import
``parrot_tools`` or ``parrot.scheduler``, and no SQLite backend appears.
"""

from __future__ import annotations

import ast
import tomllib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[5]
CORE_PYPROJECT = REPO_ROOT / "packages" / "ai-parrot" / "pyproject.toml"
TOOLS_PYPROJECT = REPO_ROOT / "packages" / "ai-parrot-tools" / "pyproject.toml"
CONTRACTS_SRC = REPO_ROOT / "packages" / "ai-parrot" / "src" / "parrot" / "knowledge" / "contracts"


def _load(path: Path) -> dict:
    """Parse one pyproject.toml."""
    return tomllib.loads(path.read_text())


@pytest.fixture(scope="module")
def core_project() -> dict:
    return _load(CORE_PYPROJECT)


def test_repo_layout_anchor_is_correct():
    assert CORE_PYPROJECT.is_file()
    assert CONTRACTS_SRC.is_dir()


def test_rapidfuzz_is_declared_in_the_graphindex_extra(core_project):
    extras = core_project["project"]["optional-dependencies"]
    graphindex = extras["graphindex"]
    assert any(item.replace(" ", "").startswith("rapidfuzz>=3.0") for item in graphindex), graphindex


def test_rapidfuzz_is_not_a_core_runtime_dependency(core_project):
    core = core_project["project"]["dependencies"]
    assert not any("rapidfuzz" in item for item in core)


def test_rapidfuzz_is_added_to_exactly_one_core_extra(core_project):
    extras = core_project["project"]["optional-dependencies"]
    holders = [name for name, items in extras.items() if any("rapidfuzz" in item for item in items)]
    assert holders == ["graphindex"], holders


def test_tools_scraping_extra_is_untouched():
    extras = _load(TOOLS_PYPROJECT)["project"]["optional-dependencies"]
    assert any("rapidfuzz>=3.0" in item for item in extras["scraping"])


def test_graphindex_postgres_extra_still_carries_the_catalog_dependencies(core_project):
    extras = core_project["project"]["optional-dependencies"]
    postgres = " ".join(extras["graphindex-postgres"])
    assert "asyncpg>=0.29" in postgres
    assert "pgvector>=0.2" in postgres


def test_no_sqlite_backend_reaches_the_contracts_extras(core_project):
    """The contracts pilot ships no SQLite catalog backend.

    ``aiosqlite`` remains a pre-existing *core* dependency of wikitoolkit
    (FEAT-471) and is deliberately untouched; what must stay clean are the
    two extras this feature installs for the catalog.
    """
    extras = core_project["project"]["optional-dependencies"]
    for name in ("graphindex", "graphindex-postgres"):
        joined = " ".join(extras[name]).lower()
        assert "sqlite" not in joined, (name, joined)


def test_scheduler_dependency_stays_in_its_pre_existing_extra(core_project):
    """This feature adds no scheduler infrastructure.

    ``apscheduler`` is the pre-existing FEAT-453 ``scheduler`` extra; the
    contracts jobs are plain async callables the deploying agent wires up,
    so it must not appear in the extras the catalog installs.
    """
    extras = core_project["project"]["optional-dependencies"]
    holders = [name for name, items in extras.items() if any("apscheduler" in i for i in items)]
    assert holders == ["scheduler"], holders
    assert not any("apscheduler" in item for item in core_project["project"]["dependencies"])


# --------------------------------------------------------------------------
# Import boundaries of the core contracts package
# --------------------------------------------------------------------------


def _imported_modules(path: Path) -> set[str]:
    """Return every absolute module name imported by one source file."""
    tree = ast.parse(path.read_text())
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module)
    return names


@pytest.mark.parametrize("module_path", sorted(CONTRACTS_SRC.glob("*.py")), ids=lambda p: p.name)
def test_core_contracts_never_import_tools_or_scheduler(module_path: Path):
    for name in _imported_modules(module_path):
        assert not name.startswith("parrot_tools"), f"{module_path.name} -> {name}"
        assert not name.startswith("parrot.scheduler"), f"{module_path.name} -> {name}"
        assert not name.startswith("sqlite3"), f"{module_path.name} -> {name}"


@pytest.mark.parametrize("module_path", sorted(CONTRACTS_SRC.glob("*.py")), ids=lambda p: p.name)
def test_optional_dependencies_are_imported_lazily(module_path: Path):
    """asyncpg / rapidfuzz must never be imported at module import time."""
    tree = ast.parse(module_path.read_text())
    optional = {"asyncpg", "rapidfuzz"}
    for node in tree.body:  # module level only
        if isinstance(node, ast.Import):
            assert not optional & {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            assert node.module.split(".")[0] not in optional
        elif isinstance(node, ast.If):
            # `if TYPE_CHECKING:` blocks are type-only and never executed.
            assert ast.unparse(node.test) in {"TYPE_CHECKING", "typing.TYPE_CHECKING"}


def test_contracts_package_imports_without_optional_extras():
    """Importing the package must not pull in asyncpg or rapidfuzz.

    Runs in a subprocess: purging ``sys.modules`` in-process would leave
    other suites holding classes from a stale module object.
    """
    import subprocess
    import sys

    code = (
        "import sys;"
        "import parrot.knowledge.contracts as contracts;"
        "assert contracts.ContractCard is not None;"
        "leaked = [name for name in ('asyncpg', 'rapidfuzz') if name in sys.modules];"
        "print(contracts.__file__);"
        "print('LEAKED=' + ','.join(leaked))"
    )
    # Pin the subprocess to *this* worktree. Inheriting the ambient
    # PYTHONPATH would silently test whichever `parrot` happens to be
    # installed, so the guard could pass while proving nothing about the
    # branch under test — or fail for reasons unrelated to it.
    import os

    src_roots = [
        str(REPO_ROOT / "packages" / "ai-parrot" / "src"),
        str(REPO_ROOT / "packages" / "ai-parrot-tools" / "src"),
    ]
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(src_roots)

    completed = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert completed.returncode == 0, completed.stderr[-2000:]
    assert "LEAKED=\n" in completed.stdout or completed.stdout.strip().endswith("LEAKED=")
    # The module actually under test must be the one in this worktree.
    assert str(REPO_ROOT) in completed.stdout, completed.stdout


def test_the_answering_layer_also_imports_without_optional_extras():
    """``parrot_tools.contracts`` must not pull asyncpg/rapidfuzz either.

    The core guard above covers only ``parrot.knowledge.contracts``; the
    answering layer is a separate distribution with its own import graph.
    """
    import os
    import subprocess
    import sys

    code = (
        "import sys;"
        "import parrot_tools.contracts as contracts;"
        "leaked = [n for n in ('asyncpg', 'rapidfuzz') if n in sys.modules];"
        "print('LEAKED=' + ','.join(leaked))"
    )
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        [
            str(REPO_ROOT / "packages" / "ai-parrot" / "src"),
            str(REPO_ROOT / "packages" / "ai-parrot-tools" / "src"),
        ]
    )
    completed = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert completed.returncode == 0, completed.stderr[-2000:]
    assert completed.stdout.strip().endswith("LEAKED="), completed.stdout
