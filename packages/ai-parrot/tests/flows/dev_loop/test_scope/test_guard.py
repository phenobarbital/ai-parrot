"""Decision matrix for test_scope.guard (FEAT-563 TASK-3309)."""

from __future__ import annotations

import subprocess

import pytest

from parrot.flows.dev_loop.test_scope import guard as guard_mod
from parrot.flows.dev_loop.test_scope.datatypes import PytestInvocation, ScopePlan
from parrot.flows.dev_loop.test_scope.guard import guard_argv, guard_bash


def _plan(*argvs: tuple[str, ...]) -> ScopePlan:
    return ScopePlan(
        tier="task",
        invocations=tuple(PytestInvocation(distribution="a", argv=a, targets=()) for a in argvs),
        escalated=(),
        core_hits=(),
        skipped_escalations=(),
        notes=(),
    )


@pytest.fixture
def with_plan(monkeypatch):
    def _set(plan):
        monkeypatch.setattr(guard_mod, "_task_plan", lambda worktree: plan)

    return _set


def test_guard_inactive_without_context(tmp_path, with_plan):
    with_plan(None)
    assert guard_argv(["pytest"], worktree=tmp_path).action == "allow"


def test_guard_rewrites_to_declared_and_mirror(tmp_path, with_plan):
    with_plan(_plan(("pytest", "-q", "packages/a/tests/test_x.py")))
    outcome = guard_argv(["pytest", "packages/a/tests"], worktree=tmp_path)
    assert outcome.action == "rewrite" and outcome.argvs[0][-1] == "packages/a/tests/test_x.py"


def test_guard_blocks_empty_plan(tmp_path, with_plan):
    with_plan(_plan())
    assert guard_argv(["python", "-m", "pytest"], worktree=tmp_path).action == "block"


def test_scoped_command_is_allowed(tmp_path, with_plan):
    with_plan(_plan(("pytest", "x")))
    assert guard_argv(["pytest", "packages/a/tests/test_x.py::t"], worktree=tmp_path).action == "allow"


def test_guard_bash_compound_and_unparseable(tmp_path, with_plan):
    with_plan(_plan(("pytest", "a.py"), ("pytest", "b.py")))
    outcome, rewritten = guard_bash("cd sub && pytest packages/a/tests | tail -n 5", worktree=tmp_path)
    assert outcome.action == "rewrite" and rewritten.startswith("cd sub && (") and rewritten.endswith("| tail -n 5")
    outcome, rewritten = guard_bash("pytest $(echo tests)", worktree=tmp_path)
    assert outcome.action == "allow" and rewritten is None


def test_rewritten_bash_propagates_failure(tmp_path, with_plan):
    with_plan(_plan(("false",), ("true",)))
    outcome, rewritten = guard_bash("pytest packages/a/tests", worktree=tmp_path)
    assert outcome.action == "rewrite"
    result = subprocess.run(["bash", "-c", rewritten], capture_output=True, text=True, check=False)
    assert result.returncode != 0
