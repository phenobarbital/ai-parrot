"""Planner/policy unit tests (FEAT-563 M1)."""

from pathlib import Path

import pytest

from parrot.flows.dev_loop.test_scope import TestContract, TestTarget
from parrot.flows.dev_loop.test_scope.planner import OVERRIDE_MARKER_EXPRESSION, build_plan, marker_expression_for
from parrot.flows.dev_loop.test_scope.policy import AGENT_FLAGS, AGENT_MARKER_EXPRESSION, ScopePolicy


def _t(path, dist, reason="mirror"):
    return TestTarget(path=path, distribution=dist, reason=reason)


def test_plan_groups_per_distribution(tmp_path: Path):
    plan = build_plan(
        [_t("packages/a/tests/x", "a"), _t("packages/b/tests/test_y.py", "b"), _t("tests/test_r.py", "root")],
        tier="merge",
        worktree=tmp_path,
        policy=ScopePolicy(),
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
    plan = build_plan(
        [_t("packages/a/tests/x", "a"), _t("packages/b/tests/y", "b")], tier="merge", worktree=tmp_path, policy=policy
    )
    by = {i.distribution: i.argv for i in plan.invocations}
    assert "-n" in by["a"] and "-n" not in by["b"]


def test_nested_targets_pruned(tmp_path: Path):
    plan = build_plan(
        [_t("packages/a/tests", "a", "escalated"), _t("packages/a/tests/flows/test_z.py", "a")],
        tier="feature",
        worktree=tmp_path,
        policy=ScopePolicy(),
    )
    assert plan.invocations[0].argv[-1] == "packages/a/tests"
    assert len(plan.invocations[0].targets) == 1


def test_empty_targets_and_unknown_tier(tmp_path: Path):
    assert build_plan([], tier="task", worktree=tmp_path, policy=ScopePolicy()).invocations == ()
    with pytest.raises(ValueError):
        build_plan([], tier="nightly", worktree=tmp_path, policy=ScopePolicy())


def test_contract_targets_get_override_invocation(tmp_path: Path):
    contract = TestContract(schema=1, tests=("packages/a/tests/test_x.py",), markers=(), digest="sha256:test")
    plan = build_plan(
        [
            _t("packages/a/tests/test_y.py", "a", "mirror"),
            _t("packages/a/tests/test_x.py", "a", "contract"),
        ],
        tier="merge",
        worktree=tmp_path,
        policy=ScopePolicy(),
        contract=contract,
        mode="contract",
    )

    assert len(plan.invocations) == 2
    assert plan.invocations[0].argv[plan.invocations[0].argv.index("-m") + 1] == AGENT_MARKER_EXPRESSION
    assert plan.invocations[1].argv[plan.invocations[1].argv.index("-m") + 1] == OVERRIDE_MARKER_EXPRESSION
    assert plan.mode == "contract"


def test_contract_reason_wins_duplicate_path(tmp_path: Path):
    contract = TestContract(schema=1, tests=("packages/a/tests/test_x.py",), markers=(), digest="sha256:test")
    plan = build_plan(
        [
            _t("packages/a/tests/test_x.py", "a", "declared"),
            _t("packages/a/tests/test_x.py", "a", "contract"),
        ],
        tier="merge",
        worktree=tmp_path,
        policy=ScopePolicy(),
        contract=contract,
    )

    assert len(plan.invocations) == 1
    assert plan.invocations[0].targets[0].reason == "contract"
    assert plan.invocations[0].argv[plan.invocations[0].argv.index("-m") + 1] == OVERRIDE_MARKER_EXPRESSION


def test_contract_markers_add_distribution_sweep(tmp_path: Path):
    contract = TestContract(
        schema=1,
        tests=("packages/a/tests/test_x.py",),
        markers=("integration", "e2e"),
        digest="sha256:test",
    )
    plan = build_plan(
        [_t("packages/a/tests/test_x.py", "a", "contract")],
        tier="feature",
        worktree=tmp_path,
        policy=ScopePolicy(),
        contract=contract,
    )

    assert len(plan.invocations) == 2
    sweep = plan.invocations[1]
    assert sweep.targets == (_t("packages/a/tests", "a", "contract"),)
    assert sweep.argv[sweep.argv.index("-m") + 1] == "(integration or e2e) and not real_llm"


def test_marker_expression_requires_all_contract_targets():
    policy = ScopePolicy()
    contract = TestContract(schema=1, tests=("tests/test_x.py",), markers=(), digest="sha256:test")

    assert marker_expression_for([_t("tests/test_x.py", "root", "contract")], contract=contract, policy=policy) == (
        OVERRIDE_MARKER_EXPRESSION
    )
    assert marker_expression_for([_t("tests/test_x.py", "root", "mirror")], contract=contract, policy=policy) == (
        AGENT_MARKER_EXPRESSION
    )
