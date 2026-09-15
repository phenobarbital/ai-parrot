"""Shared fixtures for sdd_coder tests (FEAT-549).

`git_sandbox_feature` extends the `git_sandbox` pattern of
`test_worktree_manager.py:36-52` with the SDD artifacts the engine reads:
a per-spec index and a handful of TASK files under `sdd/tasks/active/`.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from parrot.flows.dev_loop.sdd_coder.models import RosterConfig, RosterSeat
from parrot.flows.dev_loop.sdd_coder.roster import RosterProbe

FEATURE_BRANCH = "feat-FEAT-549-demo"
FEATURE_ID = "FEAT-549"
FEATURE_SLUG = "demo"

_TASK_TEMPLATE = """# {task_id}: Demo task {n}

**Feature**: {feature_id} — demo
**Status**: pending
**Depends-on**: {depends_on}

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `pkg/t{n}.py` | CREATE | demo file for {task_id} |
"""


async def _run_git(*args: str, cwd: Path) -> None:
    proc = await asyncio.create_subprocess_exec(
        "git", *args, cwd=str(cwd), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    out, err = await proc.communicate()
    assert proc.returncode == 0, f"git {' '.join(args)} failed in {cwd}: {err.decode()}\n{out.decode()}"


async def _write_and_commit(repo: Path, filename: str, content: str, message: str) -> None:
    path = repo / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    await _run_git("add", filename, cwd=repo)
    await _run_git("commit", "-m", message, cwd=repo)


def _task_entry(task_id: str, n: int, depends_on: list[str]) -> dict:
    return {
        "id": task_id,
        "feature_id": FEATURE_ID,
        "feature": FEATURE_SLUG,
        "status": "pending",
        "depends_on": depends_on,
        "file": f"sdd/tasks/active/{task_id}-demo.md",
    }


@pytest.fixture
async def git_sandbox_feature(tmp_path):
    """Temp repo with `dev` + `feat-FEAT-549-demo` branches, a per-spec index
    (5 tasks: 3 independent, 2 depending on the first two), and TASK files
    with '## Files to Create / Modify' sections.

    Returns (worktree: Path, feature_branch: str, base_path: Path, index_path: Path).
    """
    base_path = tmp_path / "wt"
    worktree = base_path / FEATURE_BRANCH
    worktree.mkdir(parents=True)

    await _run_git("init", "-b", "dev", cwd=worktree)
    await _run_git("config", "user.email", "test@example.com", cwd=worktree)
    await _run_git("config", "user.name", "Test", cwd=worktree)
    await _write_and_commit(worktree, "README.md", "hello\n", "initial commit")
    await _write_and_commit(worktree, "pkg/__init__.py", "", "add pkg")

    await _run_git("checkout", "-b", FEATURE_BRANCH, cwd=worktree)

    tasks = [
        _task_entry("TASK-0001", 1, []),
        _task_entry("TASK-0002", 2, []),
        _task_entry("TASK-0003", 3, []),
        _task_entry("TASK-0004", 4, ["TASK-0001"]),
        _task_entry("TASK-0005", 5, ["TASK-0002"]),
    ]
    index = {
        "feature": FEATURE_SLUG,
        "feature_id": FEATURE_ID,
        "spec": "sdd/specs/demo.spec.md",
        "type": "feature",
        "base_branch": "dev",
        "created_at": "2026-09-10T00:00:00+00:00",
        "completed_at": None,
        "tasks": tasks,
    }
    index_path_rel = "sdd/tasks/index/demo.json"
    await _write_and_commit(worktree, index_path_rel, json.dumps(index, indent=2) + "\n", "add index")

    for n in range(1, 6):
        task_id = f"TASK-000{n}"
        body = _TASK_TEMPLATE.format(task_id=task_id, n=n, feature_id=FEATURE_ID, depends_on="none")
        await _write_and_commit(worktree, f"sdd/tasks/active/{task_id}-demo.md", body, f"add {task_id}")

    index_path = worktree / index_path_rel
    return worktree, FEATURE_BRANCH, base_path, index_path


@pytest.fixture
def three_seat_roster() -> RosterConfig:
    return RosterConfig(
        seats=[
            RosterSeat(label="a", backend="nova"),
            RosterSeat(label="b", backend="google-compat"),
            RosterSeat(label="c", backend="codex"),
        ]
    )


@pytest.fixture
def noop_probe() -> RosterProbe:
    return RosterProbe(config_getter=lambda k, fallback=None: "x", which=lambda b: "/usr/bin/" + b, smoke=None)
