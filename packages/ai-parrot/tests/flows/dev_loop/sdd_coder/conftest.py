"""Shared fixtures for sdd_coder tests (FEAT-549, FEAT-559).

`git_sandbox_feature` extends the `git_sandbox` pattern of
`test_worktree_manager.py:36-52` with the SDD artifacts the engine reads:
a per-spec index and a handful of TASK files under `sdd/tasks/active/`.

FEAT-559 adds execution-pool fixtures with explicit model IDs, isolated
suspension stores and fake clocks for deterministic testing.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from unittest.mock import patch

import pytest

from parrot.flows.dev_loop.sdd_coder.models import RosterConfig, RosterSeat
from parrot.flows.dev_loop.sdd_coder.roster import RosterProbe
from parrot.knowledge.wiki.ledger.coder_suspensions import CoderSuspensionStore

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

## Complexity Contract

```json
{{
  "schema_version": 1,
  "targets": [
    {{
      "path": "pkg/t{n}.py",
      "action": "CREATE"
    }}
  ],
  "contract_symbols": []
}}
```

## Acceptance Criteria

- [ ] Demo file created
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
    # Real checkouts ignore `artifacts/` (repo-root .gitignore); the sandbox
    # needs its own so `collect_complexity`'s persisted-assessment writes
    # (spec: "Do not commit runtime artifacts automatically") don't dirty
    # `git status` in tests that assert a clean worktree post-merge.
    await _write_and_commit(worktree, ".gitignore", "artifacts/\n", "add gitignore")
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
    # FEAT-559 TASK-3277's model_identity_required rule excludes any seat with
    # an empty `model` from every probe/plan, so each seat needs an explicit
    # (deterministic, test-only) model id -- otherwise engine.open()/plan()
    # raises roster_empty for every caller of this fixture.
    return RosterConfig(
        seats=[
            RosterSeat(label="a", backend="nova", model="model-a"),
            RosterSeat(label="b", backend="google-compat", model="model-b"),
            RosterSeat(label="c", backend="codex", model="model-c"),
        ]
    )


@pytest.fixture
def noop_probe() -> RosterProbe:
    return RosterProbe(config_getter=lambda k, fallback=None: "x", which=lambda b: "/usr/bin/" + b, smoke=None)


@pytest.fixture
async def git_sandbox_feature_with_complex_task(tmp_path):
    """Temp repo with a complex task that has many acceptance criteria and dependencies."""
    base_path = tmp_path / "wt"
    worktree = base_path / FEATURE_BRANCH
    worktree.mkdir(parents=True)

    await _run_git("init", "-b", "dev", cwd=worktree)
    await _run_git("config", "user.email", "test@example.com", cwd=worktree)
    await _run_git("config", "user.name", "Test", cwd=worktree)
    await _write_and_commit(worktree, "README.md", "hello\n", "initial commit")
    # Real checkouts ignore `artifacts/` (repo-root .gitignore); the sandbox
    # needs its own so `collect_complexity`'s persisted-assessment writes
    # (spec: "Do not commit runtime artifacts automatically") don't dirty
    # `git status` in tests that assert a clean worktree post-merge.
    await _write_and_commit(worktree, ".gitignore", "artifacts/\n", "add gitignore")
    await _write_and_commit(worktree, "pkg/__init__.py", "", "add pkg")

    await _run_git("checkout", "-b", FEATURE_BRANCH, cwd=worktree)

    # Create a complex task with many acceptance criteria
    complex_task_body = """# TASK-9999: Complex demo task

**Feature**: FEAT-549 — demo
**Status**: pending
**Depends-on**: []

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `pkg/complex_module.py` | CREATE | Complex module with many functions |
| `pkg/utils.py` | MODIFY | Utility functions |
| `tests/test_complex.py` | CREATE | Tests for complex module |

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "pkg/complex_module.py",
      "action": "CREATE"
    },
    {
      "path": "pkg/utils.py",
      "action": "MODIFY"
    },
    {
      "path": "tests/test_complex.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:pkg/utils.py#some_function",
    "sym:pkg/utils.py#another_function"
  ]
}
```

## Acceptance Criteria

- [ ] Implement complex algorithm with proper error handling
- [ ] Add comprehensive unit tests with 100% coverage
- [ ] Update documentation with examples
- [ ] Handle edge cases and invalid inputs
- [ ] Optimize performance for large datasets
- [ ] Add logging for debugging purposes
- [ ] Validate input parameters thoroughly
- [ ] Implement retry logic for transient failures
- [ ] Add metrics collection for monitoring
- [ ] Write integration tests with other modules
"""

    tasks = [
        _task_entry("TASK-9999", 9999, []),
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

    await _write_and_commit(worktree, "sdd/tasks/active/TASK-9999-demo.md", complex_task_body, "add complex task")
    await _write_and_commit(
        worktree, "pkg/utils.py", "# utils\ndef some_function(): pass\ndef another_function(): pass\n", "add utils"
    )

    index_path = worktree / index_path_rel
    return worktree, FEATURE_BRANCH, base_path, index_path


# FEAT-559 fixtures for execution lifecycle testing


@pytest.fixture
def explicit_model_roster() -> RosterConfig:
    """Roster with explicit, deterministic model IDs for testing.

    Uses 'model-a', 'model-b', 'model-c' instead of empty models,
    so exclusion matching works reliably in tests.
    """
    return RosterConfig(
        seats=[
            RosterSeat(label="a", backend="nova", model="model-a"),
            RosterSeat(label="b", backend="google-compat", model="model-b"),
            RosterSeat(label="c", backend="codex", model="model-c"),
        ]
    )


@pytest.fixture
def fake_utc_clock():
    """Fake UTC clock for deterministic time-based tests.

    Returns a function that returns a fixed datetime, and a way to
    advance the clock for testing expiry behavior.
    """
    current_time = datetime(2026, 9, 16, 12, 0, 0, tzinfo=timezone.utc)

    def _now() -> datetime:
        return current_time

    def _advance(seconds: int) -> None:
        nonlocal current_time
        current_time = datetime.fromtimestamp(current_time.timestamp() + seconds, tzinfo=timezone.utc)

    # Patch datetime in the suspensions module
    with patch("parrot.knowledge.wiki.ledger.coder_suspensions.datetime") as mock_dt:
        mock_dt.now.return_value = current_time
        mock_dt.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)
        yield _now, _advance


@pytest.fixture
async def isolated_suspension_store(tmp_path) -> CoderSuspensionStore:
    """Isolated suspension store with no pre-existing history.

    Creates a fresh temporary directory for the ledger, ensuring
    tests don't inherit any real suspension history.
    """
    store = CoderSuspensionStore.from_root(tmp_path)
    return store
