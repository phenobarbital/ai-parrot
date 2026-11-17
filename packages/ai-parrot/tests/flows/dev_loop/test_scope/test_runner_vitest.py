"""Tests for the FEAT-709 Vitest runner adapter."""

from __future__ import annotations

from pathlib import Path

import pytest

from parrot.flows.dev_loop.test_scope.datatypes import TestTarget
from parrot.flows.dev_loop.test_scope.policy import ScopePolicy
from parrot.flows.dev_loop.test_scope.runners.vitest import ADAPTER

FIXTURES = Path(__file__).parent / "fixtures"


def test_vitest_invocation_uses_spec_argv_and_configured_cwd(tmp_path: Path) -> None:
    """The adapter builds the fixed pnpm command with stable, de-duplicated paths."""
    targets = (
        TestTarget("src/z.test.ts", "admin-ui", "declared", runner="vitest"),
        TestTarget("src/a.test.ts", "admin-ui", "mirror", runner="vitest"),
        TestTarget("src/a.test.ts", "admin-ui", "declared", runner="vitest"),
    )

    invocation = ADAPTER.invocation(
        targets,
        distribution="admin-ui",
        worktree=tmp_path,
        settings={"cwd": "packages/ui"},
        policy=ScopePolicy(),
        report_path="/tmp/vitest.xml",
    )

    assert invocation.argv == (
        "pnpm",
        "exec",
        "vitest",
        "run",
        "--reporter=junit",
        "--outputFile=/tmp/vitest.xml",
        "src/a.test.ts",
        "src/z.test.ts",
    )
    assert invocation.cwd == "packages/ui"
    assert invocation.targets == targets
    assert invocation.runner == "vitest"


def test_vitest_broadness_uses_positional_operands() -> None:
    """Vitest and ``vitest run`` are broad only when no file operand exists."""
    assert ADAPTER.is_broad(["vitest"], worktree=None)
    assert ADAPTER.is_broad(["vitest", "run", "--reporter=junit"], worktree=None)
    assert not ADAPTER.is_broad(["vitest", "run", "src/form.test.ts"], worktree=None)
    assert ADAPTER.operands(["pytest", "test_form.py"]) is None


def test_vitest_mirror_targets_are_existing_files_relative_to_cwd(tmp_path: Path) -> None:
    """UI sources map only to existing sibling tests beneath the configured cwd."""
    cwd = tmp_path / "packages" / "ui"
    source_dir = cwd / "src" / "lib"
    source_dir.mkdir(parents=True)
    (source_dir / "form.test.ts").write_text("test")
    (source_dir / "panel.spec.ts").write_text("test")
    (source_dir / "widget.test.js").write_text("test")
    outside = tmp_path / "src"
    outside.mkdir()
    (outside / "ignored.test.ts").write_text("test")

    targets = ADAPTER.mirror_targets(
        [
            "packages/ui/src/lib/form.ts",
            "packages/ui/src/lib/panel.svelte",
            "packages/ui/src/lib/widget.svelte.ts",
            "packages/ui/src/lib/form.ts",
            "src/ignored.ts",
            "packages/ui/src/lib/readme.md",
        ],
        worktree=tmp_path,
        settings={"cwd": "packages/ui"},
    )

    assert targets == ["src/lib/form.test.ts", "src/lib/panel.spec.ts", "src/lib/widget.test.js"]


def test_vitest_junit_fixture_parses_nodes_and_failure_text() -> None:
    """The shared Vitest fixture yields three nodes and one detailed failure."""
    report = ADAPTER.parse_report(
        report_path=FIXTURES / "vitest-junit.xml",
        exit_code=1,
        stdout="",
        stderr="",
        duration_s=0.42,
        timed_out=False,
        suite="vitest:admin-ui",
    )

    assert report.tests == 3
    assert len(report.nodes) == 3
    assert report.failed == 1
    assert report.status == "failed"
    nodeid = "src/lib/form.test.ts::validates required"
    assert "expected true to be false" in report.failure_text[nodeid]


def test_vitest_missing_report_is_red() -> None:
    """A missing report path cannot produce a green result."""
    report = ADAPTER.parse_report(
        report_path=None,
        exit_code=1,
        stdout="",
        stderr="failure",
        duration_s=0.1,
        timed_out=False,
        suite="vitest:admin-ui",
    )
    assert report.status == "no_report"
    assert report.tests == 0


def test_vitest_settings_require_cwd_with_package_json(tmp_path: Path) -> None:
    """Settings validation requires a cwd containing a package manifest."""
    assert ADAPTER.validate_settings({}, worktree=tmp_path) == ["vitest: cwd is required"]
    assert ADAPTER.validate_settings({"cwd": "ui"}, worktree=tmp_path)
    ui = tmp_path / "ui"
    ui.mkdir()
    (ui / "package.json").write_text("{}")
    assert ADAPTER.validate_settings({"cwd": "ui"}, worktree=tmp_path) == []


def test_vitest_distribution_defaults_to_admin_ui() -> None:
    """Distribution settings override the stable admin UI default."""
    assert ADAPTER.distribution_of("src/form.test.ts", settings={}) == "admin-ui"
    assert ADAPTER.distribution_of("src/form.test.ts", settings={"distribution": "web"}) == "web"


@pytest.mark.parametrize("cwd", ["/etc", "../outside", "ui/../../outside"])
def test_vitest_rejects_cwd_outside_worktree(tmp_path: Path, cwd: str) -> None:
    """mirror_targets and invocation refuse an escaping cwd; validate_settings reports it."""
    worktree = tmp_path / "wt"
    worktree.mkdir()
    settings = {"cwd": cwd}
    with pytest.raises(ValueError, match="must stay inside the worktree"):
        ADAPTER.mirror_targets(["ui/src/a.ts"], worktree=worktree, settings=settings)
    with pytest.raises(ValueError, match="must stay inside the worktree"):
        ADAPTER.invocation(
            (TestTarget("src/a.test.ts", "admin-ui", "declared", runner="vitest"),),
            distribution="admin-ui",
            worktree=worktree,
            settings=settings,
            policy=ScopePolicy(),
            report_path="/tmp/vitest.xml",
        )
    assert ADAPTER.validate_settings(settings, worktree=worktree) == ["vitest: cwd must stay inside the worktree"]


def test_vitest_rejects_symlinked_cwd_outside_worktree(tmp_path: Path) -> None:
    """A cwd that is a symlink pointing outside the worktree is refused too."""
    worktree = tmp_path / "wt"
    worktree.mkdir()
    (tmp_path / "outside").mkdir()
    (worktree / "ui").symlink_to(tmp_path / "outside")
    with pytest.raises(ValueError, match="must stay inside the worktree"):
        ADAPTER.mirror_targets(["ui/src/a.ts"], worktree=worktree, settings={"cwd": "ui"})
