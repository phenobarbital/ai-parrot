"""Decision matrix for test_scope.guard (FEAT-563 TASK-3309)."""

from __future__ import annotations

import pytest

from parrot.flows.dev_loop.test_scope import guard as guard_mod
from parrot.flows.dev_loop.test_scope.datatypes import Invocation, ScopePlan
from parrot.flows.dev_loop.test_scope.guard import VERDICT_ARGV, guard_argv, guard_bash


def _plan(*argvs: tuple[str, ...]) -> ScopePlan:
    return ScopePlan(
        tier="task",
        invocations=tuple(Invocation(distribution="a", argv=a, targets=()) for a in argvs),
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


def test_guard_returns_verdict_for_broad_pytest(tmp_path, with_plan):
    with_plan(_plan(("pytest", "-q", "packages/a/tests/test_x.py")))
    outcome = guard_argv(["pytest", "packages/a/tests"], worktree=tmp_path)
    assert outcome.action == "verdict"
    assert outcome.argvs == ((*VERDICT_ARGV, "--worktree", str(tmp_path)),)


def test_guard_blocks_empty_plan(tmp_path, with_plan):
    with_plan(_plan())
    assert guard_argv(["python", "-m", "pytest"], worktree=tmp_path).action == "block"


def test_scoped_command_is_allowed(tmp_path, with_plan):
    with_plan(_plan(("pytest", "x")))
    assert guard_argv(["pytest", "packages/a/tests/test_x.py::t"], worktree=tmp_path).action == "allow"


def test_guard_bash_compound_and_unparseable(tmp_path, with_plan):
    with_plan(_plan(("pytest", "a.py"), ("pytest", "b.py")))
    outcome, rewritten = guard_bash("cd sub && pytest packages/a/tests | tail -n 5", worktree=tmp_path)
    assert outcome.action == "allow" and rewritten is None
    outcome, rewritten = guard_bash("pytest $(echo tests)", worktree=tmp_path)
    assert outcome.action == "allow" and rewritten is None


def test_guard_bash_returns_verdict_command(tmp_path, with_plan):
    with_plan(_plan(("pytest", "a.py")))
    outcome, rewritten = guard_bash("pytest packages/a/tests", worktree=tmp_path)
    assert outcome.action == "verdict"
    assert (
        rewritten
        == f"cd {tmp_path} && python scripts/sdd/select_tests.py --tier task --run --verdict --worktree {tmp_path}"
    )


# --- Hardening regressions: env-var prefix, `uv run`, `--maxfail`, multi-segment compounds ---
# `.claude/rules/worktree-management.md` §4 documents `PYTHONPATH=packages/ai-parrot/src pytest ...`
# and `uv run --no-sync <tool>` as the sanctioned ways to run tests inside a worktree; a guard that
# only recognizes a bare `pytest`/`python -m pytest` argv[0] silently allows the over-broad form
# through unscoped the moment either idiom is used.


def test_env_prefixed_pytest_is_recognized_for_verdict(tmp_path, with_plan):
    with_plan(_plan(("pytest", "packages/a/tests/test_x.py")))
    outcome = guard_argv(["PYTHONPATH=packages/ai-parrot/src", "pytest", "packages/ai-parrot/tests"], worktree=tmp_path)
    assert outcome.action == "verdict"


def test_env_prefixed_pytest_bash_uses_verdict(tmp_path, with_plan):
    with_plan(_plan(("pytest", "a.py")))
    outcome, rewritten = guard_bash(
        "PYTHONPATH=packages/ai-parrot/src pytest packages/ai-parrot/tests", worktree=tmp_path
    )
    assert outcome.action == "verdict"
    assert "select_tests.py" in rewritten


def test_uv_run_pytest_is_recognized(tmp_path, with_plan):
    with_plan(_plan(("pytest", "a.py")))
    outcome = guard_argv(["uv", "run", "pytest", "packages/ai-parrot/tests"], worktree=tmp_path)
    assert outcome.action == "verdict"


def test_uv_run_no_sync_pytest_is_recognized(tmp_path, with_plan):
    with_plan(_plan(("pytest", "a.py")))
    outcome = guard_argv(["uv", "run", "--no-sync", "pytest", "packages/ai-parrot/tests"], worktree=tmp_path)
    assert outcome.action == "verdict"


def test_maxfail_space_form_does_not_defeat_broad_detection(tmp_path, with_plan):
    with_plan(_plan())
    # `--maxfail 1` (space-separated) used to be parsed as operand "1" -> looked "narrow" -> allowed.
    outcome = guard_argv(["pytest", "packages/ai-parrot/tests", "--maxfail", "1"], worktree=tmp_path)
    assert outcome.action == "block"


def test_guard_bash_allows_compound_broad_runner_commands(tmp_path, with_plan):
    with_plan(_plan(("pytest", "a.py")))
    outcome, rewritten = guard_bash(
        "pytest packages/ai-parrot/tests && pytest packages/a-parrot/tests", worktree=tmp_path
    )
    assert outcome.action == "allow"
    assert rewritten is None


def test_absolute_path_to_a_broad_directory_uses_verdict(tmp_path, with_plan):
    with_plan(_plan(("pytest", "a.py")))
    broad_abs = str(tmp_path / "packages" / "ai-parrot" / "tests")
    outcome = guard_argv(["pytest", broad_abs], worktree=tmp_path)
    assert outcome.action == "verdict"


def test_guard_returns_verdict_for_broad_vitest(tmp_path, with_plan):
    with_plan(_plan(("pytest", "a.py")))
    outcome = guard_argv(["vitest", "run"], worktree=tmp_path)
    assert outcome.action == "verdict"
