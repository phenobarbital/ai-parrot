"""Real, pinned-Pyright (1.1.414) integration tests (FEAT-580, TASK-3508).

Every test in this module drives a REAL ``pyright-langserver`` child process
-- never ``fake_server.py`` -- against real on-disk fixtures: aliases,
inheritance, duplicate names, PEP 420 namespace roots, and a non-target
dependency change. A missing/wrong-version pinned executable SKIPS these
tests in an ordinary offline run (never counted as integration acceptance
per spec sec5); set ``PARROT_LSP_REQUIRE_PYRIGHT=1`` to turn that into a
hard failure instead, e.g. in a CI lane that provisions the pinned
toolchain.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from parrot_tools.lsp.models import LSPConfig
from parrot_tools.lsp.toolkit import LSPToolkit

_EXPECTED_VERSION = "1.1.414"
_REQUIRE_ENV = "PARROT_LSP_REQUIRE_PYRIGHT"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _column_of(line_text: str, needle: str) -> int:
    """1-based Unicode column of the first occurrence of ``needle`` on a line."""
    idx = line_text.index(needle)
    return idx + 1


def _line_of(text: str, needle: str) -> tuple[int, str]:
    """1-based line number and text of the first line containing ``needle``."""
    for lineno, line in enumerate(text.splitlines(), start=1):
        if needle in line:
            return lineno, line
    raise AssertionError(f"{needle!r} not found in fixture text")


def _pinned_pyright_version() -> str | None:
    """The version string a real, on-PATH ``pyright`` binary reports, or ``None``."""
    binary = shutil.which("pyright")
    if not binary:
        return None
    try:
        result = subprocess.run([binary, "--version"], capture_output=True, text=True, timeout=15, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    output = (result.stdout or result.stderr or "").strip()
    return output or None


def _require_or_skip() -> None:
    """Skip an ordinary offline run, or hard-fail under ``PARROT_LSP_REQUIRE_PYRIGHT=1``,
    when the pinned executable is unavailable or the wrong version.

    A skip here NEVER counts as integration acceptance -- spec sec5:
    "missing executable skips ordinary offline runs only, never qualifies
    acceptance."
    """
    version_output = _pinned_pyright_version()
    langserver = shutil.which("pyright-langserver")
    ok = bool(version_output and _EXPECTED_VERSION in version_output and langserver)
    if ok:
        return
    reason = (
        f"pinned pyright {_EXPECTED_VERSION} / pyright-langserver not available "
        f"(pyright --version: {version_output!r}, pyright-langserver: {langserver!r})"
    )
    if os.environ.get(_REQUIRE_ENV) == "1":
        pytest.fail(f"{_REQUIRE_ENV}=1: {reason}")
    pytest.skip(reason)


@pytest.fixture(autouse=True)
def _require_real_pyright() -> None:
    _require_or_skip()


def _real_config(repo_root: Path, **overrides: object) -> LSPConfig:
    fields: dict[str, object] = {
        "repo_root": repo_root,
        "environment_id": "real-pyright-integration",
        "expected_server_version": _EXPECTED_VERSION,
    }
    fields.update(overrides)
    return LSPConfig(**fields)


@pytest.fixture
def real_fixture_repo(tmp_path: Path) -> Path:
    """Real on-disk fixtures: aliases, inheritance, duplicate names, a PEP
    420 namespace root, and a non-target dependency change."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")

    # Duplicate function names across two modules -- navigation must resolve
    # the definition site actually queried, not a same-named sibling.
    (repo / "dup_a.py").write_text("def handler():\n    return 'a'\n")
    (repo / "dup_b.py").write_text("def handler():\n    return 'b'\n")

    # Alias / re-export chain: a third file's usage of the re-exported name
    # must resolve back to base.py's real definition, not reexport.py.
    (repo / "base.py").write_text("def original():\n    return 1\n")
    (repo / "reexport.py").write_text("from base import original as renamed\n")
    (repo / "use_alias.py").write_text("from reexport import renamed\n\nresult = renamed()\n")

    # Inheritance: a call through a subclass instance resolves to the base
    # class's method definition.
    (repo / "shapes.py").write_text(
        "class Base:\n"
        "    def area(self) -> float:\n"
        "        return 0.0\n"
        "\n"
        "\n"
        "class Circle(Base):\n"
        "    pass\n"
        "\n"
        "\n"
        "def use(c: Circle) -> float:\n"
        "    return c.area()\n"
    )

    # PEP 420 namespace root: a distribution-style source root without
    # __init__.py, imported cross-distribution via `source_roots`.
    ns_root = repo / "packages" / "pkg-a" / "src"
    (ns_root / "pkg_ns").mkdir(parents=True)
    (ns_root / "pkg_ns" / "helper.py").write_text("def cross_dist_helper():\n    return 42\n")
    (repo / "consumer.py").write_text("from pkg_ns.helper import cross_dist_helper\n\nuse_it = cross_dist_helper()\n")

    # A non-target dependency change: editing dep.py must not corrupt
    # navigation/diagnostics for the unrelated target.py that imports it.
    (repo / "dep.py").write_text("VALUE = 1\n")
    (repo / "target.py").write_text("from dep import VALUE\n\nresult = VALUE + 1\n")

    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "init")
    return repo


# ---------------------------------------------------------------------------
# test_pyright_pinned_navigation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pyright_pinned_navigation(real_fixture_repo: Path) -> None:
    """Real pinned Pyright resolves aliases, inheritance and duplicate names correctly."""
    toolkit = LSPToolkit(_real_config(real_fixture_repo))
    try:
        alias_text = (real_fixture_repo / "use_alias.py").read_text()
        lineno, line_text = _line_of(alias_text, "renamed()")
        result = await toolkit.lsp_definition(
            path="use_alias.py",
            line=lineno,
            column=_column_of(line_text, "renamed()"),
            expected_sha256=_sha256(alias_text),
        )
        assert result.status == "ok"
        assert any(loc.range.path == "base.py" for loc in result.locations), (
            f"alias chain use_alias.renamed -> reexport.renamed did not resolve to "
            f"base.py's 'original': {result.locations!r}"
        )

        shapes_text = (real_fixture_repo / "shapes.py").read_text()
        lineno, line_text = _line_of(shapes_text, "c.area()")
        inherited = await toolkit.lsp_definition(
            path="shapes.py",
            line=lineno,
            column=_column_of(line_text, "area()"),
            expected_sha256=_sha256(shapes_text),
        )
        assert inherited.status == "ok"
        assert any(loc.range.path == "shapes.py" for loc in inherited.locations)

        dup_a_text = (real_fixture_repo / "dup_a.py").read_text()
        lineno, line_text = _line_of(dup_a_text, "def handler")
        dup_result = await toolkit.lsp_definition(
            path="dup_a.py",
            line=lineno,
            column=_column_of(line_text, "handler"),
            expected_sha256=_sha256(dup_a_text),
        )
        assert dup_result.status == "ok"
        # The queried definition site itself, never the same-named sibling
        # in dup_b.py.
        assert all(loc.range.path != "dup_b.py" for loc in dup_result.locations)

        consumer_text = (real_fixture_repo / "consumer.py").read_text()
        lineno, line_text = _line_of(consumer_text, "cross_dist_helper()")
        ns_config = _real_config(real_fixture_repo, source_roots=[real_fixture_repo / "packages" / "pkg-a" / "src"])
        ns_toolkit = LSPToolkit(ns_config)
        try:
            ns_result = await ns_toolkit.lsp_definition(
                path="consumer.py",
                line=lineno,
                column=_column_of(line_text, "cross_dist_helper()"),
                expected_sha256=_sha256(consumer_text),
            )
            assert ns_result.status == "ok"
            assert any(
                "helper.py" in loc.range.path for loc in ns_result.locations
            ), f"PEP 420 namespace root import did not resolve: {ns_result.locations!r}"
        finally:
            await ns_toolkit._close()
    finally:
        await toolkit._close()


# ---------------------------------------------------------------------------
# test_pyright_saved_edit_diagnostic_delta
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pyright_saved_edit_diagnostic_delta(real_fixture_repo: Path) -> None:
    """A real saved edit is reflected in a subsequent diagnostic baseline delta.

    Exercises baseline -> error -> removal transitions against a real
    pinned Pyright, including a versioned empty publication (a clean file
    after the introduced error is fixed) -- an "unknown" result must never
    be reported as clean.
    """
    toolkit = LSPToolkit(_real_config(real_fixture_repo))
    try:
        target = real_fixture_repo / "target.py"

        baseline = await toolkit.lsp_diagnostics(paths=["target.py"])
        assert baseline.status == "ok"
        baseline_id = baseline.snapshot_id
        assert baseline_id

        # Introduce a real, Pyright-detectable error (undefined name).
        target.write_text("from dep import VALUE\n\nresult = VALUE + undefined_name\n")
        error_delta = await toolkit.lsp_diagnostic_delta(baseline_id=baseline_id, paths=["target.py"])
        assert error_delta.status == "ok"
        assert error_delta.added, "expected the introduced error to appear as an added diagnostic"

        error_snapshot_id = error_delta.snapshot_id
        assert error_snapshot_id

        # Fix it -- the resulting versioned EMPTY publication (a clean file)
        # must be distinguishable from an unknown/timeout result.
        target.write_text("from dep import VALUE\n\nresult = VALUE + 1\n")
        removal_delta = await toolkit.lsp_diagnostic_delta(baseline_id=error_snapshot_id, paths=["target.py"])
        assert removal_delta.status == "ok"
        assert removal_delta.removed, "expected the fixed error to appear as a removed diagnostic"
    finally:
        await toolkit._close()


# ---------------------------------------------------------------------------
# test_pyright_dependency_restart
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pyright_dependency_restart(real_fixture_repo: Path) -> None:
    """Editing a non-target dependency invalidates the session; navigation still resolves.

    A changed workspace must never reuse an earlier generation's semantic
    evidence (spec sec5) -- editing dep.py (not the queried file) must force
    a fresh session/generation, at real cold-restart cost, before
    target.py's navigation is trusted again.
    """
    toolkit = LSPToolkit(_real_config(real_fixture_repo))
    try:
        target_text = (real_fixture_repo / "target.py").read_text()
        lineno, line_text = _line_of(target_text, "VALUE + 1")
        before = await toolkit.lsp_definition(
            path="target.py",
            line=lineno,
            column=_column_of(line_text, "VALUE"),
            expected_sha256=_sha256(target_text),
        )
        assert before.status == "ok"
        generation_before = toolkit._session_generation

        # Edit the dependency the queried file imports, not the queried
        # file itself.
        (real_fixture_repo / "dep.py").write_text("VALUE = 2\n")

        after = await toolkit.lsp_definition(
            path="target.py",
            line=lineno,
            column=_column_of(line_text, "VALUE"),
            expected_sha256=_sha256(target_text),
        )
        assert after.status == "ok"
        assert any(loc.range.path == "dep.py" for loc in after.locations)
        assert (
            toolkit._session_generation > generation_before
        ), "a dependency change must invalidate the session, not silently reuse stale evidence"
    finally:
        await toolkit._close()
