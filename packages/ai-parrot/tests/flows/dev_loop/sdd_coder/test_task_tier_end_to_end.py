"""FEAT-709: task-tier gate → same-seat repair → merge, end to end (fake seat, real git, real pytest)."""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Optional

import pytest

from parrot.flows.dev_loop.models import DevelopmentOutput
from parrot.flows.dev_loop.sdd_coder.engine import SddCoderEngine
from parrot.flows.dev_loop.sdd_coder.models import RosterConfig, RosterSeat, RunnerConfig
from parrot.flows.dev_loop.test_scope.datatypes import Failure, ValidationVerdict

pytestmark = pytest.mark.asyncio


# === Helpers from conftest.py (duplicated for hermetic test) ===

FEATURE_BRANCH = "feat-FEAT-709-demo"
FEATURE_ID = "FEAT-709"
FEATURE_SLUG = "demo"


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


_TASK_TEMPLATE = """# {task_id}: Demo task {n}

**Feature**: {feature_id} — demo
**Status**: pending
**Depends-on**: {depends_on}

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `pkg/t{n}.py` | CREATE | demo file for {task_id} |
| `tests/test_t{n}.py` | CREATE | test file for {task_id} |

## Complexity Contract

```json
{{
  "schema_version": 1,
  "targets": [
    {{
      "path": "pkg/t{n}.py",
      "action": "CREATE"
    }},
    {{
      "path": "tests/test_t{n}.py",
      "action": "CREATE"
    }}
  ],
  "contract_symbols": []
}}
```

## Acceptance Criteria

- [ ] Demo file created
- [ ] Test file created and passes
"""


# === Fixtures ===

@pytest.fixture
async def git_sandbox_feature(tmp_path):
    """Temp repo with `dev` + `feat-FEAT-709-demo` branches, a per-spec index."""
    base_path = tmp_path / "wt"
    worktree = base_path / FEATURE_BRANCH
    worktree.mkdir(parents=True)

    await _run_git("init", "-b", "dev", cwd=worktree)
    await _run_git("config", "user.email", "test@example.com", cwd=worktree)
    await _run_git("config", "user.name", "Test", cwd=worktree)
    await _write_and_commit(worktree, "README.md", "hello\n", "initial commit")
    await _write_and_commit(worktree, ".gitignore", "artifacts/\n", "add gitignore")
    await _write_and_commit(worktree, "pkg/__init__.py", "", "add pkg")
    await _write_and_commit(worktree, "tests/__init__.py", "", "add tests")

    await _run_git("checkout", "-b", FEATURE_BRANCH, cwd=worktree)

    tasks = [
        _task_entry("TASK-0001", 1, []),
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

    for n in range(1, 2):
        task_id = f"TASK-000{n}"
        body = _TASK_TEMPLATE.format(task_id=task_id, n=n, feature_id=FEATURE_ID, depends_on="none")
        await _write_and_commit(worktree, f"sdd/tasks/active/{task_id}-demo.md", body, f"add {task_id}")

    index_path = worktree / index_path_rel
    return worktree, FEATURE_BRANCH, base_path, index_path


# === Fake components ===

class FakeDispatcher:
    """Fulfils the dispatcher Protocol's `dispatch()` shape.

    `behaviour` per instance:
      - "ok": writes the task's listed file in `cwd`, commits, returns a DevelopmentOutput.
      - "fail": raises RuntimeError.
      - "banned": writes a banned import (`import httpx`) into the task's listed file.
    """

    def __init__(self, behaviour: str = "ok", *, fail_on_first: bool = False) -> None:
        self.behaviour = behaviour
        self.fail_on_first = fail_on_first
        self.calls: list[dict] = []
        self._attempt_count = 0

    async def dispatch(self, *, brief, profile, output_model, run_id, node_id, cwd, session_host=None, labels=None):
        self.calls.append({"brief": brief, "profile": profile, "node_id": node_id, "cwd": cwd, "labels": labels})
        self._attempt_count += 1

        if self.behaviour == "fail" or (self.fail_on_first and self._attempt_count == 1):
            raise RuntimeError("boom")

        task_id = brief.task_id
        n = task_id.rsplit("-", 1)[-1].lstrip("0") or "0"
        pkg_file = f"pkg/t{int(n)}.py"
        test_file = f"tests/test_t{int(n)}.py"

        (Path(cwd) / "pkg").mkdir(parents=True, exist_ok=True)
        (Path(cwd) / "tests").mkdir(parents=True, exist_ok=True)

        # Write the implementation file
        (Path(cwd) / pkg_file).write_text(f"# {task_id}\ndef foo():\n    return 42\n")

        # Write a test file - first attempt has a failing test, second has a passing one
        if self._attempt_count == 1:
            # First attempt: failing test
            (Path(cwd) / test_file).write_text(
                f"import pytest\nfrom pkg.t{int(n)} import foo\n\n"
                f"def test_foo():\n    assert foo() == 100, 'expected 100 but got 42'\n"
            )
        else:
            # Second attempt: passing test
            (Path(cwd) / test_file).write_text(
                f"import pytest\nfrom pkg.t{int(n)} import foo\n\n"
                f"def test_foo():\n    assert foo() == 42\n"
            )

        await _run_git("add", pkg_file, cwd=Path(cwd))
        await _run_git("add", test_file, cwd=Path(cwd))
        await _run_git("commit", "-m", f"impl {task_id}", cwd=Path(cwd))
        return DevelopmentOutput(
            files_changed=[pkg_file, test_file],
            commit_shas=["deadbeef"],
            summary=task_id
        )


def fake_builder_factory(behaviour: str = "ok", *, fail_on_first: bool = False):
    """(DevAgentSpec, **kwargs) -> (FakeDispatcher, profile) — keyword-compatible with build_dispatcher."""
    from parrot.flows.dev_loop.models import LLMCodeDispatchProfile

    dispatcher = FakeDispatcher(behaviour, fail_on_first=fail_on_first)

    def _builder(spec, *, redis_url, max_concurrent, stream_ttl_seconds):
        profile = LLMCodeDispatchProfile()
        return dispatcher, profile

    _builder.dispatcher = dispatcher  # type: ignore[attr-defined]
    return _builder


def _roster(*labels_backends: tuple[str, str]) -> RosterConfig:
    return RosterConfig(
        seats=[
            RosterSeat(label=lbl, backend=backend, model=f"model-{lbl}")  # type: ignore[arg-type]
            for lbl, backend in labels_backends
        ]
    )


def _noop_probe():
    from parrot.flows.dev_loop.sdd_coder.roster import RosterProbe
    return RosterProbe(config_getter=lambda k, fallback=None: "x", which=lambda b: "/usr/bin/" + b, smoke=None)


class FakeSupervisor:
    """Stands in for `ValidationSupervisor`: scripted verdict status per gate run."""

    def __init__(self, statuses: list[str]) -> None:
        self.statuses = list(statuses)
        self.starts: list[dict] = []

    async def start(self, **kwargs):
        self.starts.append(kwargs)
        return SimpleNamespace(handle=f"h{len(self.starts)}")

    async def wait_verdict(self, execution_id, handle, timeout_s):
        status = self.statuses.pop(0) if self.statuses else "passed"
        failures = () if status == "passed" else (
            Failure("pytest", "tests/test_t1.py::test_foo", "new_red", "expected 100 but got 42"),
        )
        return ValidationVerdict(
            schema=1, status=status, tier="task", runners=(), failures=failures,
            notes=(), cached=(), evidence=()
        )


# === The test ===

async def test_task_tier_end_to_end_pytest(git_sandbox_feature):
    """Red gate on attempt 1, repaired by the same seat on attempt 2, merged once green."""
    worktree, feature_branch, base_path, _index_path = git_sandbox_feature

    # Build engine with fake dispatcher that fails on first attempt
    builder = fake_builder_factory("ok", fail_on_first=True)
    roster = _roster(("a", "nova"), ("b", "codex"), ("c", "google-compat"))
    roster = roster.model_copy(update={"runners": RunnerConfig(same_seat_repair=True)})

    engine = SddCoderEngine(
        roster=roster,
        probe=_noop_probe(),
        worktree_base_path=str(base_path),
        dispatcher_builder=builder,
    )

    # Inject fake supervisor: first run fails (red), second passes (green)
    engine._validation_supervisor = FakeSupervisor(["failed", "passed"])
    # Give every branch an execution ID so the gate runs
    engine._execution_for = lambda branch: "12345678-1234-4234-8234-123456789abc"

    # Run the task
    job = await engine.run_chunk("demo", str(worktree), ["TASK-0001"])
    result = await engine.wait(job.job_id, 30)

    task = result.tasks[0]

    # Assertions
    assert task.outcome == "merged", f"Expected merged, got {task.outcome}: {task.diagnostics}"
    assert [a.attempt for a in task.attempts] == [1, 2], f"Expected 2 attempts, got {[a.attempt for a in task.attempts]}"
    assert task.attempts[0].seat_label == task.attempts[1].seat_label, "Same seat should handle both attempts"

    # Verify validation verdict is in the repair brief
    calls = builder.dispatcher.calls
    assert len(calls) == 2, f"Expected 2 dispatch calls, got {len(calls)}"
    assert calls[0]["brief"].validation_verdict == "", "First attempt should have no verdict"
    assert calls[1]["brief"].validation_verdict.startswith("## Validation verdict") or "test_foo" in calls[1]["brief"].validation_verdict, \
        "Second attempt should have validation verdict in brief"

    # Verify the branch history: attempt-1 commit is ancestor of attempt-2 branch
    rc, _out, _ = await _run_git(
        "merge-base", "--is-ancestor", f"{feature_branch}--TASK-0001-a1", "HEAD",
        cwd=worktree
    )
    assert rc == 0, "Attempt 1 branch should be ancestor of attempt 2 branch (repair is seeded from failed branch)"