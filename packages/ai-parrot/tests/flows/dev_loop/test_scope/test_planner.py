"""Planner/policy unit tests (FEAT-563 M1)."""
from pathlib import Path

import pytest

from parrot.flows.dev_loop.test_scope import TestTarget
from parrot.flows.dev_loop.test_scope.planner import build_plan
from parrot.flows.dev_loop.test_scope.policy import AGENT_FLAGS, AGENT_MARKER_EXPRESSION, ScopePolicy


def _t(path, dist, reason="mirror"):
    return TestTarget(path=path, distribution=dist, reason=reason)


def test_plan_groups_per_distribution(tmp_path: Path):
    plan = build_plan(
        [_t("packages/a/tests/x", "a"), _t("packages/b/tests/test_y.py", "b"), _t("tests/test_r.py", "root")],
        tier="merge", worktree=tmp_path, policy=ScopePolicy(),
    )
    assert [i.distribution for i in plan.invocations] == ["a", "b", "root"]
    for inv in plan.invocations:
        assert all(t.distribution == inv.distribution for t in inv.targets)


def test_plan_flags_and_marker_expression(tmp_path: Path):
    plan = build_plan([_t("packages/a/tests/x", "a")], tier="task", worktree=tmp_path, policy=ScopePolicy())
    argv = plan.invocations[0].argv
    assert argv[0] == "pytest"
    assert tuple(argv[1 : 1 + len(AGENT_FLAGS)]) == AGENT_FLAGS
    assert argv[argv.index("-m") + 1] == AGENT_MARKER_EXPRESSION


def test_xdist_only_for_allowlisted_dist(tmp_path: Path):
    policy = ScopePolicy(xdist_safe=frozenset({"a"}))
    plan = build_plan([_t("packages/a/tests/x", "a"), _t("packages/b/tests/y", "b")], tier="merge", worktree=tmp_path, policy=policy)
    by = {i.distribution: i.argv for i in plan.invocations}
    assert "-n" in by["a"] and "-n" not in by["b"]


def test_nested_targets_pruned(tmp_path: Path):
    plan = build_plan(
        [_t("packages/a/tests", "a", "escalated"), _t("packages/a/tests/flows/test_z.py", "a")],
        tier="feature", worktree=tmp_path, policy=ScopePolicy(),
    )
    assert plan.invocations[0].argv[-1] == "packages/a/tests"
    assert len(plan.invocations[0].targets) == 1


def test_empty_targets_and_unknown_tier(tmp_path: Path):
    assert build_plan([], tier="task", worktree=tmp_path, policy=ScopePolicy()).invocations == ()
    with pytest.raises(ValueError):
        build_plan([], tier="nightly", worktree=tmp_path, policy=ScopePolicy())
