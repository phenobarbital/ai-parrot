"""Engine-owned per-task lint pass (ruff --fix + formatter at the merge boundary)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from parrot.flows.dev_loop.sdd_coder.engine import SddCoderEngine
from parrot.flows.dev_loop.sdd_coder.lint import detect_formatter, parse_unified_hunks, resolve_bin, run_lint_pass
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


# --- FEAT-702: formatter scoped to the task's changed lines --------------------------------

_UNCLEAN_BASE = "y = {'b':2}\n"
_UNCLEAN_ADDED = "x = {'a':1}\n"


def test_parse_unified_hunks():
    diff = "@@ -1,0 +2,3 @@\n+a\n+b\n+c\n@@ -5 +5 @@\n-x\n+y\n@@ -7,2 +7,0 @@\n-p\n-q\n"
    assert parse_unified_hunks(diff) == [(2, 4), (5, 5)]
    assert parse_unified_hunks("") == []


_MODIFY_TASK = """# TASK-0006: Append to an existing file

**Feature**: FEAT-549 — demo
**Status**: pending
**Depends-on**: none

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `pkg/base.py` | MODIFY | append one line |

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "pkg/base.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": []
}
```

## Acceptance Criteria

- [ ] Line appended
"""


async def _merge_unclean_base_with_appended_line(git_sandbox_feature, noop_probe, lint: LintConfig):
    """Commit an unclean base file on the feature branch; a MODIFY task appends one unclean line; merge.

    The sandbox's stock tasks are all CREATE-shaped, so a sixth MODIFY task is added to the
    index (the planner routes a CREATE whose target already exists away from the native seat).
    """
    worktree, feature_branch, base_path, index_path = git_sandbox_feature
    filename, task_id = "pkg/base.py", "TASK-0006"
    await _write_and_commit(worktree, "ruff.toml", _RUFF_CFG, "ruff config")
    await _write_and_commit(worktree, filename, _UNCLEAN_BASE, "unclean base file")
    await _write_and_commit(worktree, f"sdd/tasks/active/{task_id}-demo.md", _MODIFY_TASK, f"add {task_id}")
    index = json.loads(index_path.read_text())
    index["tasks"].append(
        {
            "id": task_id,
            "feature_id": index["feature_id"],
            "feature": index["feature"],
            "status": "pending",
            "depends_on": [],
            "file": f"sdd/tasks/active/{task_id}-demo.md",
        }
    )
    await _write_and_commit(
        worktree, str(index_path.relative_to(worktree)), json.dumps(index, indent=2) + "\n", f"index {task_id}"
    )
    engine = SddCoderEngine(
        roster=RosterConfig(seats=[RosterSeat(label="h", kind="native")], lint=lint),
        probe=noop_probe,
        worktree_base_path=str(base_path),
    )
    prep = await engine.prepare_native("demo", str(worktree), task_id)
    await _write_and_commit(Path(prep.worktree_path), filename, _UNCLEAN_BASE + _UNCLEAN_ADDED, f"implement {task_id}")
    result = await engine.merge("demo", str(worktree), task_id)
    assert result.outcome == "merged", result.diagnostics
    assert result.lint is not None
    return worktree, feature_branch, filename, result


async def test_merge_formats_only_changed_lines(git_sandbox_feature, noop_probe):
    worktree, feature_branch, filename, result = await _merge_unclean_base_with_appended_line(
        git_sandbox_feature, noop_probe, LintConfig()
    )

    assert result.lint.formatter == "ruff"
    assert result.lint.fixed_files == [filename] and result.lint.commit
    assert result.lint.tool_error == ""
    # The task's line is formatted; the untouched unclean base line is left alone.
    assert (worktree / filename).read_text() == _UNCLEAN_BASE + 'x = {"a": 1}\n'
    _rc, log, _err = await _git("log", "--oneline", feature_branch, cwd=worktree)
    assert "TASK-0006 — engine lint autofix" in log
    assert (await _git("status", "--porcelain", cwd=worktree))[1].strip() == ""


async def test_merge_format_scope_file_reformats_whole_file(git_sandbox_feature, noop_probe):
    worktree, _feature_branch, filename, result = await _merge_unclean_base_with_appended_line(
        git_sandbox_feature, noop_probe, LintConfig(format_scope="file")
    )

    assert result.lint.fixed_files == [filename] and result.lint.commit
    assert (worktree / filename).read_text() == 'y = {"b": 2}\nx = {"a": 1}\n'


async def _repo_with_unclean_base(tmp_path: Path, config_name: str, config_text: str) -> tuple[Path, str]:
    """A throwaway repo: formatter config + an unclean ``t.py`` at the base, one unclean line appended on HEAD."""
    repo = tmp_path / "repo"
    repo.mkdir()
    assert (await _git("init", "-q", "-b", "main", cwd=repo))[0] == 0
    await _git("config", "user.email", "test@example.com", cwd=repo)
    await _git("config", "user.name", "Test", cwd=repo)
    await _write_and_commit(repo, config_name, config_text, "formatter config")
    await _write_and_commit(repo, "t.py", _UNCLEAN_BASE, "unclean base")
    _rc, base_sha, _err = await _git("rev-parse", "HEAD", cwd=repo)
    await _write_and_commit(repo, "t.py", _UNCLEAN_BASE + _UNCLEAN_ADDED, "append a line")
    return repo, base_sha.strip()


@pytest.mark.skipif(resolve_bin("black") is None, reason="black not installed")
async def test_black_formats_only_changed_lines(tmp_path):
    repo, base_sha = await _repo_with_unclean_base(tmp_path, "pyproject.toml", "[tool.black]\nline-length = 120\n")

    report = await run_lint_pass(str(repo), ["t.py"], config=LintConfig(), commit_message="style", diff_base=base_sha)

    assert report.formatter == "black"
    assert report.fixed_files == ["t.py"] and report.commit and report.tool_error == ""
    assert (repo / "t.py").read_text() == _UNCLEAN_BASE + 'x = {"a": 1}\n'


async def test_unusable_diff_base_falls_back_to_whole_file(tmp_path):
    repo, _base_sha = await _repo_with_unclean_base(tmp_path, "ruff.toml", _RUFF_CFG)

    report = await run_lint_pass(
        str(repo), ["t.py"], config=LintConfig(), commit_message="style", diff_base="not-a-ref"
    )

    assert report.fixed_files == ["t.py"] and report.commit
    assert "line ranges unavailable for t.py" in report.tool_error
    assert (repo / "t.py").read_text() == 'y = {"b": 2}\nx = {"a": 1}\n'


async def test_file_added_by_the_task_is_formatted_whole(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    assert (await _git("init", "-q", "-b", "main", cwd=repo))[0] == 0
    await _git("config", "user.email", "test@example.com", cwd=repo)
    await _git("config", "user.name", "Test", cwd=repo)
    await _write_and_commit(repo, "ruff.toml", _RUFF_CFG, "formatter config")
    _rc, base_sha, _err = await _git("rev-parse", "HEAD", cwd=repo)
    await _write_and_commit(repo, "new.py", _UNCLEAN_BASE + _UNCLEAN_ADDED, "add a file")

    report = await run_lint_pass(
        str(repo), ["new.py"], config=LintConfig(), commit_message="style", diff_base=base_sha.strip()
    )

    assert report.fixed_files == ["new.py"] and report.tool_error == ""
    assert (repo / "new.py").read_text() == 'y = {"b": 2}\nx = {"a": 1}\n'
