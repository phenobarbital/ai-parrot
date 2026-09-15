"""Engine-owned per-task lint pass (ruff --fix + formatter at the merge boundary)."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from parrot.flows.dev_loop.sdd_coder.engine import SddCoderEngine
from parrot.flows.dev_loop.sdd_coder.lint import detect_formatter, resolve_bin, run_lint_pass
from parrot.flows.dev_loop.sdd_coder.models import LintConfig, RosterConfig, RosterSeat

pytestmark = pytest.mark.skipif(resolve_bin("ruff") is None, reason="ruff not installed")


async def _git(*args: str, cwd: Path) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
        "git", *args, cwd=str(cwd), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    out, err = await proc.communicate()
    return proc.returncode or 0, out.decode(), err.decode()


async def _write_and_commit(repo: Path, filename: str, content: str, message: str) -> None:
    path = repo / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    assert (await _git("add", filename, cwd=repo))[0] == 0
    rc, _out, err = await _git("commit", "-m", message, cwd=repo)
    assert rc == 0, err


_RUFF_CFG = '[lint]\nselect = ["F401", "E9", "F63", "F7", "F82"]\n[format]\nquote-style = "double"\n'


def test_detect_formatter(tmp_path):
    assert detect_formatter(str(tmp_path), "auto") == "none"
    (tmp_path / "ruff.toml").write_text(_RUFF_CFG)
    assert detect_formatter(str(tmp_path), "auto") == "ruff"
    (tmp_path / "pyproject.toml").write_text("[tool.black]\nline-length = 120\n")
    assert detect_formatter(str(tmp_path), "auto") == "black"
    assert detect_formatter(str(tmp_path), "none") == "none"


async def test_lint_pass_no_python_files(tmp_path):
    report = await run_lint_pass(str(tmp_path), ["README.md"], config=LintConfig(), commit_message="x")
    assert report.commit == "" and report.errors == [] and report.residual_count == 0


async def test_merge_autofixes_formats_and_commits(git_sandbox_feature, noop_probe):
    worktree, feature_branch, base_path, _index_path = git_sandbox_feature
    await _write_and_commit(worktree, "ruff.toml", _RUFF_CFG, "ruff config")
    engine = SddCoderEngine(
        roster=RosterConfig(seats=[RosterSeat(label="h", kind="native")]),
        probe=noop_probe,
        worktree_base_path=str(base_path),
    )
    prep = await engine.prepare_native("demo", str(worktree), "TASK-0001")
    await _write_and_commit(Path(prep.worktree_path), "pkg/t1.py", "import os\nx = {'a':1}\n", "implement TASK-0001")

    result = await engine.merge("demo", str(worktree), "TASK-0001")

    assert result.outcome == "merged"
    assert result.lint is not None
    assert result.lint.formatter == "ruff"
    assert result.lint.fixed_files == ["pkg/t1.py"] and result.lint.commit
    assert result.lint.errors == [] and result.lint.residual_count == 0
    assert (worktree / "pkg/t1.py").read_text() == 'x = {"a": 1}\n'
    _rc, log, _err = await _git("log", "--oneline", feature_branch, cwd=worktree)
    assert "TASK-0001 — engine lint autofix" in log
    assert (await _git("status", "--porcelain", cwd=worktree))[1].strip() == ""


async def test_merge_reports_correctness_errors_without_blocking(git_sandbox_feature, noop_probe):
    worktree, _feature_branch, base_path, _index_path = git_sandbox_feature
    engine = SddCoderEngine(
        roster=RosterConfig(seats=[RosterSeat(label="h", kind="native")], lint=LintConfig(formatter="none")),
        probe=noop_probe,
        worktree_base_path=str(base_path),
    )
    prep = await engine.prepare_native("demo", str(worktree), "TASK-0002")
    await _write_and_commit(Path(prep.worktree_path), "pkg/t2.py", "print(undefined_name)\n", "implement TASK-0002")

    result = await engine.merge("demo", str(worktree), "TASK-0002")

    assert result.outcome == "merged"
    assert result.lint is not None and result.lint.commit == ""
    assert any("F821" in e and e.startswith("pkg/t2.py:1:") for e in result.lint.errors)
    assert all("F821" not in r for r in result.lint.residual)


async def test_merge_with_autofix_disabled_leaves_branch_untouched(git_sandbox_feature, noop_probe):
    worktree, feature_branch, base_path, _index_path = git_sandbox_feature
    await _write_and_commit(worktree, "ruff.toml", _RUFF_CFG, "ruff config")
    engine = SddCoderEngine(
        roster=RosterConfig(seats=[RosterSeat(label="h", kind="native")], lint=LintConfig(autofix=False)),
        probe=noop_probe,
        worktree_base_path=str(base_path),
    )
    prep = await engine.prepare_native("demo", str(worktree), "TASK-0003")
    await _write_and_commit(Path(prep.worktree_path), "pkg/t3.py", "import os\n", "implement TASK-0003")

    result = await engine.merge("demo", str(worktree), "TASK-0003")

    assert result.outcome == "merged" and result.lint is not None
    assert result.lint.commit == "" and result.lint.residual_count == 1
    _rc, log, _err = await _git("log", "--oneline", feature_branch, cwd=worktree)
    assert "engine lint autofix" not in log
