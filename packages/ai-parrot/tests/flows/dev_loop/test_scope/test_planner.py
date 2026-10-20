"""Planner/policy unit tests (FEAT-563 M1)."""

from pathlib import Path

import pytest

from parrot.flows.dev_loop.test_scope import TestContract, TestTarget
from parrot.flows.dev_loop.test_scope.datatypes import Invocation, RunnerContract
from parrot.flows.dev_loop.test_scope.planner import OVERRIDE_MARKER_EXPRESSION, build_plan, marker_expression_for
from parrot.flows.dev_loop.test_scope.policy import AGENT_FLAGS, AGENT_MARKER_EXPRESSION, ScopePolicy
from parrot.flows.dev_loop.test_scope.runners.registry import RunnerRegistry
from parrot.flows.dev_loop.test_scope.select import plan_tests


def _t(path, dist, reason="mirror"):
    return TestTarget(path=path, distribution=dist, reason=reason)


class FakeAdapter:
    """Minimal non-pytest adapter used to exercise runner-aware grouping."""

    kind = "fake"
    binaries = ("fake-test",)
    default_tiers = frozenset({"task", "merge", "feature"})
    report_format = "exit-code"

    def matches(self, argv):
        return bool(argv) and argv[0] == "fake-test"

    def operands(self, argv):
        return list(argv[1:]) if self.matches(argv) else None

    def is_broad(self, argv, *, worktree):
        return False

    def mirror_targets(self, changed, *, worktree, settings):
        return []

    def distribution_of(self, target, *, settings):
        return "root"

    def invocation(self, targets, *, distribution, worktree, settings, policy, report_path):
        return Invocation(
            distribution=distribution,
            argv=("fake-test", *(target.path for target in targets)),
            targets=tuple(targets),
            runner=self.kind,
            report_format=self.report_format,
        )

    def parse_report(self, *, report_path, exit_code, stdout, stderr, duration_s, timed_out, suite):
        raise AssertionError("not exercised")

    def validate_settings(self, settings, *, worktree):
        return []


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
    assert sweep.argv[sweep.argv.index("-m") + 1] == "(e2e or integration) and not real_llm"


def test_marker_expression_requires_all_contract_targets():
    policy = ScopePolicy()
    contract = TestContract(schema=1, tests=("tests/test_x.py",), markers=(), digest="sha256:test")

    assert marker_expression_for([_t("tests/test_x.py", "root", "contract")], contract=contract, policy=policy) == (
        OVERRIDE_MARKER_EXPRESSION
    )
    assert marker_expression_for([_t("tests/test_x.py", "root", "mirror")], contract=contract, policy=policy) == (
        AGENT_MARKER_EXPRESSION
    )


def test_plan_groups_contract_targets_by_runner_and_distribution(tmp_path: Path):
    registry = RunnerRegistry({"fake": FakeAdapter()}, {})
    contract = TestContract(
        schema=2,
        runners=(
            RunnerContract(kind="pytest", targets=("tests/test_pytest.py",)),
            RunnerContract(kind="fake", targets=("tests/test_fake.py",)),
        ),
        digest="sha256:test",
    )
    for path in ("tests/test_pytest.py", "tests/test_fake.py"):
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("")

    plan = plan_tests(worktree=tmp_path, changed_files=[], tier="merge", contract=contract, registry=registry)

    assert [(invocation.runner, invocation.distribution) for invocation in plan.invocations] == [
        ("fake", "root"),
        ("pytest", "root"),
    ]


def test_non_pytest_declared_command_produces_runner_target(tmp_path: Path):
    registry = RunnerRegistry({"fake": FakeAdapter()}, {})

    plan = plan_tests(
        worktree=tmp_path,
        changed_files=[],
        tier="task",
        declared=(("fake-test", "tests/test_fake.py"),),
        registry=registry,
    )

    assert plan.invocations[0].runner == "fake"
    assert plan.invocations[0].targets == (TestTarget("tests/test_fake.py", "root", "declared", runner="fake"),)
