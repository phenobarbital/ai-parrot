"""Unit tests for ``parrot.e2e.models`` and ``parrot.e2e.errors`` (TASK-3520, M2).

Covers success construction, invalid input rejection, prerequisite-failure
exit mapping and cleanup-state representation for every model named in
spec §2 "Data Models". No target/provider/process is spawned — these are
pure schema-validation tests.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from parrot.e2e.errors import (
    EXIT_BLOCKED,
    EXIT_CONFIG,
    EXIT_EVIDENCE,
    EXIT_FAILURE,
    E2EBudgetError,
    E2EConfigError,
    E2EError,
    E2EEvidenceError,
    E2EPrerequisiteError,
    E2ETargetError,
)
from parrot.e2e.models import (
    E2EPlan,
    E2EVerdict,
    LiveBudget,
    ProcessIdentity,
    RunState,
    ScenarioResult,
    ScenarioSpec,
    SourceIdentity,
    TargetConfig,
    VerificationResult,
)

_UTC_NOW = datetime(2026, 9, 19, 12, 0, 0, tzinfo=timezone.utc)
_SHA = "a" * 64


def _process_identity(*, owned: bool = True) -> ProcessIdentity:
    return ProcessIdentity(pid=100, pgid=100, create_time=_UTC_NOW, boot_id="boot-1", owned=owned)


def _target_config() -> TargetConfig:
    return TargetConfig(kind="mcp-stdio")


def _scenario(
    *,
    scenario_id: str = "scn-mcp-stdio",
    tier: str = "deterministic",
    required: bool = True,
    node_ids: list[str] | None = None,
    target_ids: list[str] | None = None,
    prerequisites: list[str] | None = None,
) -> ScenarioSpec:
    if node_ids is None:
        node_ids = ["tests/e2e/test_mcp_stdio.py::test_roundtrip"] if tier != "exploratory" else []
    return ScenarioSpec(
        id=scenario_id,
        tier=tier,
        target_ids=target_ids if target_ids is not None else ["stdio"],
        required=required,
        node_ids=node_ids,
        prerequisites=prerequisites or [],
    )


def _plan(**overrides) -> E2EPlan:
    kwargs = dict(
        feature_id="FEAT-581",
        spec_path="sdd/specs/agentic-e2e-testing.spec.md",
        policy="required",
        targets={"stdio": _target_config()},
        scenarios=[_scenario()],
        budget=LiveBudget(),
        run_timeout_s=600,
    )
    kwargs.update(overrides)
    return E2EPlan(**kwargs)


def _source_identity() -> SourceIdentity:
    return SourceIdentity(
        commit="a" * 40,
        manifest_sha256=_SHA,
        spec_sha256=_SHA,
        plan_sha256=_SHA,
        environment_sha256=_SHA,
        worktree="/repo/.claude/worktrees/feat-FEAT-581",
    )


def _run_state(**overrides) -> RunState:
    kwargs = dict(
        feature_id="FEAT-581",
        run_id="run-1",
        worktree="/repo/.claude/worktrees/feat-FEAT-581",
        owner_id="owner-1",
        controller_identity=_process_identity(),
        supervisor_identity=_process_identity(),
        process_identity=_process_identity(),
        target_id="stdio",
        status="ready",
        endpoint=None,
        control_socket="/repo/sdd/state/e2e/run-1/control.sock",
        started_at=_UTC_NOW,
        deadline=_UTC_NOW + timedelta(seconds=600),
        log_path="artifacts/logs/e2e/run-1/run.log",
    )
    kwargs.update(overrides)
    return RunState(**kwargs)


# ---------------------------------------------------------------------------
# Success: full construction round-trips for every named model
# ---------------------------------------------------------------------------


def test_full_plan_constructs_successfully() -> None:
    plan = _plan()
    assert plan.schema_version == 1
    assert plan.policy == "required"
    assert plan.scenarios[0].node_ids == ["tests/e2e/test_mcp_stdio.py::test_roundtrip"]


def test_run_state_and_source_identity_construct_successfully() -> None:
    run_state = _run_state()
    assert run_state.status == "ready"
    assert run_state.cleanup_complete is False
    assert run_state.shutdown_forced is False

    identity = _source_identity()
    assert identity.commit == "a" * 40


def test_scenario_result_and_verdict_construct_successfully() -> None:
    result = ScenarioResult(
        scenario_id="scn-mcp-stdio",
        node_id="tests/e2e/test_mcp_stdio.py::test_roundtrip",
        outcome="passed",
        setup_outcome="passed",
        call_outcome="passed",
        teardown_outcome="passed",
        exit_code=0,
        duration_s=1.5,
        target_run_ids=["run-1"],
        artifact_paths=["artifacts/logs/e2e/run-1/junit.xml"],
    )
    verdict = E2EVerdict(
        feature_id="FEAT-581",
        run_id="run-1",
        policy="required",
        source_identity_before=_source_identity(),
        source_identity_after=_source_identity(),
        selected_node_ids=[result.node_id],
        collected_node_ids=[result.node_id],
        results=[result],
        counts={"passed": 1},
        argv=["parrot", "e2e", "run", "--plan", "plan.md"],
        exit_code=0,
        cleanup_results={"run-1": True},
        artifact_hashes={"artifacts/logs/e2e/run-1/junit.xml": _SHA},
        status="PASS",
        gate_satisfied=True,
        started_at=_UTC_NOW,
        completed_at=_UTC_NOW + timedelta(seconds=5),
    )
    assert verdict.status == "PASS"
    assert verdict.cleanup_results["run-1"] is True

    verification = VerificationResult(status="PASS", gate_satisfied=True, reason_codes=[])
    assert verification.status == "PASS"


# ---------------------------------------------------------------------------
# Invalid input: enums, IDs, node IDs, paths, timestamps
# ---------------------------------------------------------------------------


def test_policy_rejects_malformed_value() -> None:
    with pytest.raises(ValidationError):
        _plan(policy="sometimes")


def test_target_kind_rejects_unknown_value() -> None:
    with pytest.raises(ValidationError):
        TargetConfig(kind="ssh-shell")


def test_scenario_tier_rejects_unknown_value() -> None:
    with pytest.raises(ValidationError):
        _scenario(tier="smoke")


def test_scenario_outcome_rejects_unknown_value() -> None:
    with pytest.raises(ValidationError):
        ScenarioResult(
            scenario_id="scn-mcp-stdio",
            node_id="tests/e2e/test_mcp_stdio.py::test_roundtrip",
            outcome="flaky",
            duration_s=1.0,
        )


@pytest.mark.parametrize(
    "bad_id",
    ["", "has space", "has/slash", "has:colon", "-leading-dash"],
)
def test_stable_ids_reject_unsafe_slugs(bad_id: str) -> None:
    with pytest.raises(ValidationError):
        _plan(feature_id=bad_id)


@pytest.mark.parametrize(
    "bad_node_id",
    [
        "",
        "tests/e2e/test_mcp_stdio.py",  # bare module, no "::" selector
        "tests/e2e/*",  # wildcard
        "tests/e2e/test_mcp_stdio.py::test_*",  # wildcard inside node id
        "tests/e2e/",  # directory
    ],
)
def test_node_id_rejects_wildcard_and_bare_directory(bad_node_id: str) -> None:
    with pytest.raises(ValidationError):
        _scenario(node_ids=[bad_node_id])


def test_node_ids_must_be_unique_within_scenario() -> None:
    node_id = "tests/e2e/test_mcp_stdio.py::test_roundtrip"
    with pytest.raises(ValidationError):
        _scenario(node_ids=[node_id, node_id])


def test_plan_rejects_duplicate_node_ids_across_scenarios() -> None:
    node_id = "tests/e2e/test_mcp_stdio.py::test_roundtrip"
    duplicate_scenario = _scenario(scenario_id="scn-duplicate", node_ids=[node_id])
    with pytest.raises(ValidationError, match="node IDs must belong to exactly one scenario"):
        _plan(scenarios=[_scenario(node_ids=[node_id]), duplicate_scenario])


def test_plan_rejects_duplicate_scenario_ids() -> None:
    with pytest.raises(ValidationError, match="scenario IDs must be unique"):
        _plan(scenarios=[_scenario(), _scenario()])


def test_plan_rejects_undeclared_target_reference() -> None:
    with pytest.raises(ValidationError, match="undeclared target_id"):
        _plan(scenarios=[_scenario(target_ids=["ghost-target"])])


def test_plan_rejects_undeclared_prerequisite() -> None:
    with pytest.raises(ValidationError, match="undeclared prerequisite"):
        _plan(scenarios=[_scenario(prerequisites=["ghost-scenario"])])


def test_scenario_rejects_self_as_prerequisite() -> None:
    with pytest.raises(ValidationError, match="cannot list itself as a prerequisite"):
        _scenario(scenario_id="self-ref", prerequisites=["self-ref"])


def test_plan_spec_path_rejects_absolute_and_traversal() -> None:
    with pytest.raises(ValidationError):
        _plan(spec_path="/etc/passwd")
    with pytest.raises(ValidationError):
        _plan(spec_path="../../etc/passwd")


def test_run_state_worktree_rejects_relative_and_traversal() -> None:
    with pytest.raises(ValidationError):
        _run_state(worktree="relative/path")
    with pytest.raises(ValidationError):
        _run_state(worktree="/repo/.claude/worktrees/../../etc")


def test_source_identity_rejects_bad_commit_and_digest() -> None:
    with pytest.raises(ValidationError):
        SourceIdentity(
            commit="not-a-sha",
            manifest_sha256=_SHA,
            spec_sha256=_SHA,
            plan_sha256=_SHA,
            environment_sha256=_SHA,
            worktree="/repo/worktree",
        )
    with pytest.raises(ValidationError):
        SourceIdentity(
            commit="a" * 40,
            manifest_sha256="too-short",
            spec_sha256=_SHA,
            plan_sha256=_SHA,
            environment_sha256=_SHA,
            worktree="/repo/worktree",
        )


def test_process_identity_rejects_naive_datetime() -> None:
    with pytest.raises(ValidationError):
        ProcessIdentity(pid=1, pgid=1, create_time=datetime(2026, 1, 1), boot_id="boot", owned=True)


def test_live_budget_rejects_nonpositive_limits() -> None:
    with pytest.raises(ValidationError):
        LiveBudget(max_calls=0)
    with pytest.raises(ValidationError):
        LiveBudget(max_output_tokens=-1)


def test_extra_fields_are_forbidden() -> None:
    with pytest.raises(ValidationError):
        LiveBudget(model="google:gemini-2.5-flash-lite", unexpected_field=True)


# ---------------------------------------------------------------------------
# Required-coverage / reject-required-exploration rules
# ---------------------------------------------------------------------------


def test_codified_scenario_requires_node_ids() -> None:
    with pytest.raises(ValidationError, match="requires explicit node_ids"):
        _scenario(tier="deterministic", node_ids=[])


def test_exploratory_scenario_cannot_be_required() -> None:
    with pytest.raises(ValidationError, match="cannot be required"):
        _scenario(tier="exploratory", required=True, node_ids=[])


def test_exploratory_scenario_must_declare_no_node_ids() -> None:
    with pytest.raises(ValidationError, match="must declare no node_ids"):
        _scenario(
            tier="exploratory",
            required=False,
            node_ids=["tests/e2e/test_mcp_stdio.py::test_roundtrip"],
        )


def test_exploratory_scenario_constructs_when_unrequired_and_no_nodes() -> None:
    scenario = _scenario(tier="exploratory", required=False, node_ids=[])
    assert scenario.tier == "exploratory"
    assert scenario.node_ids == []


def test_required_policy_demands_required_codified_scenario() -> None:
    optional_only = _scenario(required=False)
    with pytest.raises(ValidationError, match="required codified scenario"):
        _plan(scenarios=[optional_only])


def test_required_policy_satisfied_by_one_required_codified_scenario() -> None:
    plan = _plan(scenarios=[_scenario(required=True)])
    assert plan.policy == "required"


def test_optional_policy_does_not_require_a_required_scenario() -> None:
    plan = _plan(policy="optional", scenarios=[_scenario(required=False)])
    assert plan.policy == "optional"


def test_none_policy_allows_empty_scenarios() -> None:
    plan = _plan(policy="none", scenarios=[])
    assert plan.scenarios == []


# ---------------------------------------------------------------------------
# Cleanup-state representation (RunState / E2EVerdict)
# ---------------------------------------------------------------------------


def test_run_state_deadline_before_started_at_rejected() -> None:
    with pytest.raises(ValidationError, match="deadline must not precede started_at"):
        _run_state(deadline=_UTC_NOW - timedelta(seconds=1))


def test_run_state_records_forced_shutdown_and_incomplete_cleanup() -> None:
    run_state = _run_state(status="failed", shutdown_forced=True, cleanup_complete=False)
    assert run_state.shutdown_forced is True
    assert run_state.cleanup_complete is False


def test_run_state_records_verified_cleanup() -> None:
    run_state = _run_state(status="stopped", shutdown_forced=False, cleanup_complete=True)
    assert run_state.cleanup_complete is True


def test_verdict_completed_before_started_rejected() -> None:
    result = ScenarioResult(
        scenario_id="scn-mcp-stdio",
        node_id="tests/e2e/test_mcp_stdio.py::test_roundtrip",
        outcome="passed",
        duration_s=1.0,
    )
    with pytest.raises(ValidationError, match="completed_at must not precede started_at"):
        E2EVerdict(
            feature_id="FEAT-581",
            run_id="run-1",
            policy="required",
            source_identity_before=_source_identity(),
            source_identity_after=_source_identity(),
            results=[result],
            exit_code=0,
            status="PASS",
            gate_satisfied=True,
            started_at=_UTC_NOW,
            completed_at=_UTC_NOW - timedelta(seconds=1),
        )


def test_verdict_artifact_hashes_reject_malformed_digest() -> None:
    with pytest.raises(ValidationError):
        E2EVerdict(
            feature_id="FEAT-581",
            run_id="run-1",
            policy="required",
            source_identity_before=_source_identity(),
            source_identity_after=_source_identity(),
            results=[],
            exit_code=0,
            artifact_hashes={"junit.xml": "not-a-digest"},
            status="PASS",
            gate_satisfied=True,
            started_at=_UTC_NOW,
            completed_at=_UTC_NOW,
        )


def test_verdict_can_record_cleanup_failure_alongside_passed_results() -> None:
    """Cleanup failure is representable independently of test outcome (spec §2:
    'Target/runner cleanup failure fails the run even if test assertions passed.').
    The runner (out of this task's scope) is responsible for deriving ``status``
    from this; the schema only needs to hold both facts simultaneously.
    """
    result = ScenarioResult(
        scenario_id="scn-mcp-stdio",
        node_id="tests/e2e/test_mcp_stdio.py::test_roundtrip",
        outcome="passed",
        duration_s=1.0,
    )
    verdict = E2EVerdict(
        feature_id="FEAT-581",
        run_id="run-1",
        policy="required",
        source_identity_before=_source_identity(),
        source_identity_after=_source_identity(),
        results=[result],
        exit_code=1,
        cleanup_results={"run-1": False},
        status="FAIL",
        gate_satisfied=False,
        started_at=_UTC_NOW,
        completed_at=_UTC_NOW + timedelta(seconds=1),
    )
    assert verdict.results[0].outcome == "passed"
    assert verdict.cleanup_results["run-1"] is False
    assert verdict.status == "FAIL"


def test_verification_result_missing_is_not_a_fabricated_pass() -> None:
    result = VerificationResult(status="MISSING", gate_satisfied=False, reason_codes=["no_evidence_found"])
    assert result.status == "MISSING"
    assert result.gate_satisfied is False


# ---------------------------------------------------------------------------
# Typed errors and exit-code mapping
# ---------------------------------------------------------------------------


def test_config_error_maps_to_exit_2() -> None:
    error = E2EConfigError("unsafe path in plan", reason_code="unsafe_path")
    assert isinstance(error, E2EError)
    assert error.exit_code == EXIT_CONFIG
    assert error.reason_code == "unsafe_path"
    assert str(error) == "unsafe path in plan"


def test_prerequisite_error_maps_to_exit_3_blocked() -> None:
    error = E2EPrerequisiteError("redis-server not installed", reason_code="missing_redis")
    assert error.exit_code == EXIT_BLOCKED
    assert error.reason_code == "missing_redis"


def test_target_error_maps_to_exit_1() -> None:
    error = E2ETargetError("target teardown failed")
    assert error.exit_code == EXIT_FAILURE
    assert error.reason_code is None


def test_budget_error_maps_to_exit_1_and_is_non_retryable_by_type() -> None:
    error = E2EBudgetError("request byte ceiling exceeded", reason_code="budget_exhausted")
    assert error.exit_code == EXIT_FAILURE
    assert isinstance(error, E2EError)


def test_evidence_error_maps_to_exit_4() -> None:
    error = E2EEvidenceError("source manifest changed since run", reason_code="stale_source")
    assert error.exit_code == EXIT_EVIDENCE


def test_all_typed_errors_are_e2e_error_subclasses() -> None:
    for error_cls in (E2EConfigError, E2EPrerequisiteError, E2ETargetError, E2EBudgetError, E2EEvidenceError):
        assert issubclass(error_cls, E2EError)
        assert issubclass(error_cls, Exception)
