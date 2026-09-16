import json

import pytest
from pydantic import ValidationError

from parrot.flows.dev_loop.sdd_coder import (
    ERROR_CODES,
    CoderError,
    CoderRunChunkArgs,
    CoderWaitArgs,
    RosterSeat,
)
from parrot.flows.dev_loop.sdd_coder.complexity_models import (
    ComplexityAssessment,
    ComplexityBlock,
    ComplexityContract,
    ComplexityEvidence,
    ComplexityPolicy,
    ComplexityTarget,
    MetricEvidence,
    StrongModelIdentity,
)
from parrot.flows.dev_loop.sdd_coder.models import (
    AttemptRecord,
    CoderPlan,
    NativePrep,
    PlannedTask,
    RosterConfig,
    TaskResult,
)


def test_roster_config_requires_backend_for_mcp():
    with pytest.raises(ValidationError):
        RosterSeat(label="x", kind="mcp")
    assert RosterSeat(label="h", kind="native").backend is None
    assert RosterSeat(label="q", backend="nova").kind == "mcp"


def test_roster_native_rejects_backend():
    with pytest.raises(ValidationError):
        RosterSeat(label="h", kind="native", backend="nova")


def test_coder_result_error_codes_closed_set():
    with pytest.raises(ValidationError):
        CoderError(code="bogus", message="m")
    for code in ERROR_CODES:
        assert CoderError(code=code, message="m").code == code


@pytest.mark.parametrize(
    "kwargs",
    [
        dict(feature="f", worktree="rel/path", task_ids=["TASK-1"]),
        dict(feature="f", worktree="/abs", task_ids=["nope"]),
        dict(feature="f", worktree="/abs", task_ids=["TASK-1"], extra=1),
    ],
)
def test_run_chunk_args_reject_bad_input(kwargs):
    with pytest.raises(ValidationError):
        CoderRunChunkArgs(**kwargs)


def test_run_chunk_args_accepts_good_input():
    args = CoderRunChunkArgs(feature="f", worktree="/abs/path", task_ids=["TASK-1", "TASK-22"])
    assert args.task_ids == ["TASK-1", "TASK-22"]


def test_wait_args_cap():
    with pytest.raises(ValidationError):
        CoderWaitArgs(job_id="j", timeout_seconds=900)
    assert CoderWaitArgs(job_id="j").timeout_seconds == 120


class TestAttemptRecordTelemetryFields:
    def test_pre_feat554_kwargs_still_validate(self):
        rec = AttemptRecord(attempt=1, seat_label="qwen", started_at="2026-09-12T00:00:00+00:00")
        assert rec.attempt_uid == ""
        assert rec.turn_series == []
        assert rec.budget_report == {}
        assert rec.declared_files is None
        assert rec.declared_files_known is False
        assert rec.terminal == "completed"

    def test_turn_series_accepts_unknown_usage(self):
        rec = AttemptRecord(attempt=1, seat_label="qwen", started_at="t", turn_series=[(7, None, None)])
        assert rec.turn_series[0] == (7, None, None)

    def test_nested_in_task_result(self):
        rec = AttemptRecord(attempt=1, seat_label="qwen", started_at="t")
        assert TaskResult(task_id="TASK-1", outcome="merged", attempts=[rec]).attempts[0] is rec


class TestComplexityModels:
    """Tests for complexity models (spec §2-§4)."""

    def test_metric_evidence_ok_requires_value(self):
        with pytest.raises(ValidationError, match="state 'ok' requires a value"):
            MetricEvidence(state="ok", reason="measured", source="test")
        # Valid ok state
        ev = MetricEvidence(state="ok", value=10, reason="measured", source="test")
        assert ev.value == 10

    def test_metric_evidence_non_ok_rejects_value(self):
        with pytest.raises(ValidationError, match="state .* requires value to be None"):
            MetricEvidence(state="unknown", value=10, reason="tool failed", source="test")
        with pytest.raises(ValidationError, match="state .* requires value to be None"):
            MetricEvidence(state="not_applicable", value=0, reason="not applicable", source="test")

    def test_metric_evidence_unknown_with_lower_bound(self):
        # Unknown can carry an observed lower bound via value
        ev = MetricEvidence(state="unknown", value=5, reason="tool timeout, saw at least 5", source="test")
        assert ev.state == "unknown"
        assert ev.value == 5

    def test_complexity_target_extra_fields_forbidden(self):
        with pytest.raises(ValidationError):
            ComplexityTarget(path="x.py", action="CREATE", extra="forbidden")

    def test_complexity_contract_schema_version_must_be_1(self):
        contract = ComplexityContract(
            targets=(ComplexityTarget(path="x.py", action="CREATE"),),
            contract_symbols=("sym:x#Y",),
        )
        assert contract.schema_version == 1
        # Cannot set other schema versions
        with pytest.raises(ValidationError):
            ComplexityContract(schema_version=2, targets=())

    def test_complexity_contract_symbols_none_vs_empty(self):
        # None means legacy missing coverage
        contract_none = ComplexityContract(targets=(), contract_symbols=None)
        assert contract_none.contract_symbols is None
        # Empty tuple is explicit declaration
        contract_empty = ComplexityContract(targets=(), contract_symbols=())
        assert contract_empty.contract_symbols == ()

    def test_complexity_policy_default_bands_match_spec(self):
        policy = ComplexityPolicy()
        # Verify spec §2 default bands
        assert policy.bands["cyclomatic_max"] == (0, 10)
        assert policy.bands["blast_symbols"] == (0, 9)
        assert policy.bands["weighted_files"] == (0, 3)
        assert policy.bands["modules"] == (0, 1)
        assert policy.bands["acceptance_criteria"] == (0, 4)
        assert policy.bands["downstream_tasks"] == (0, 1)

    def test_complexity_policy_default_hard_limits_match_spec(self):
        policy = ComplexityPolicy()
        # Verify spec §2 hard limits
        assert policy.hard_limits["cyclomatic_max"] == 21
        assert policy.hard_limits["blast_symbols"] == 30
        assert policy.hard_limits["downstream_tasks"] == 5

    def test_complexity_policy_rejects_negative_bands(self):
        with pytest.raises(ValidationError, match="negative bound"):
            ComplexityPolicy(bands={"cyclomatic_max": (-1, 10)})

    def test_complexity_policy_rejects_non_ascending_bands(self):
        with pytest.raises(ValidationError, match="non-ascending"):
            ComplexityPolicy(bands={"cyclomatic_max": (15, 10)})

    def test_complexity_policy_rejects_unknown_hard_limit_key(self):
        with pytest.raises(ValidationError, match="unknown metric"):
            ComplexityPolicy(hard_limits={"unknown_metric": 10})

    def test_complexity_policy_rejects_non_positive_hard_limit(self):
        with pytest.raises(ValidationError, match="must be positive"):
            ComplexityPolicy(hard_limits={"cyclomatic_max": 0})

    def test_complexity_policy_rejects_ambiguous_model_mapping(self):
        with pytest.raises(ValidationError, match="ambiguous model mapping"):
            ComplexityPolicy(
                strong_models=(
                    StrongModelIdentity(canonical_model="gpt-5.6-terra", backend="codex", model="gpt-5.6-terra"),
                    StrongModelIdentity(canonical_model="other", backend="codex", model="gpt-5.6-terra"),
                )
            )

    def test_complexity_policy_accepts_valid_model_mapping(self):
        policy = ComplexityPolicy(
            strong_models=(
                StrongModelIdentity(canonical_model="gpt-5.6-terra", backend="codex", model="gpt-5.6-terra"),
                StrongModelIdentity(canonical_model="sonnet-5", backend="claude", model="sonnet-5"),
            )
        )
        assert len(policy.strong_models) == 2

    def test_complexity_evidence_validates_create_hashes(self):
        contract = ComplexityContract(
            targets=(ComplexityTarget(path="new.py", action="CREATE"),)
        )
        # Missing CREATE hash should fail
        with pytest.raises(ValidationError, match="CREATE target .* missing"):
            ComplexityEvidence(
                task_id="TASK-1",
                contract=contract,
                metrics={},
                head_sha="abc",
                task_sha256="abc",
                index_sha256="abc",
                policy_sha256="abc",
                target_hashes={},  # Missing for CREATE
                wiki_evidence_hashes={},
                collector_versions={},
                details={},
            )
        # None is explicit absence for CREATE
        evidence = ComplexityEvidence(
            task_id="TASK-1",
            contract=contract,
            metrics={},
            head_sha="abc",
            task_sha256="abc",
            index_sha256="abc",
            policy_sha256="abc",
            target_hashes={"new.py": None},
            wiki_evidence_hashes={},
            collector_versions={},
            details={},
        )
        assert evidence.target_hashes["new.py"] is None

    def test_complexity_assessment_freezes_evidence(self):
        """Mutation of caller-owned input cannot change an assessment snapshot."""
        contract = ComplexityContract(targets=())
        evidence = ComplexityEvidence(
            task_id="TASK-1",
            contract=contract,
            metrics={},
            head_sha="abc",
            task_sha256="abc",
            index_sha256="abc",
            policy_sha256="abc",
            target_hashes={},
            wiki_evidence_hashes={},
            collector_versions={},
            details={},
        )
        assessment = ComplexityAssessment(
            policy_version="v1",
            task_id="TASK-1",
            classification="standard",
            total_points=0,
            component_points={},
            reason_codes=(),
            evidence=evidence,
            assessment_id="test-id",
        )
        # Mutate original evidence
        evidence.metrics["test"] = MetricEvidence(state="ok", value=1, reason="x", source="y")
        # Assessment's evidence should be unchanged (frozen)
        assert "test" not in assessment.evidence.metrics

    def test_complexity_block_error_codes_in_error_codes_set(self):
        """Every new complexity error code validates and unknown codes remain rejected."""
        new_codes = [
            "complexity_contract_invalid",
            "complexity_plan_stale",
            "complex_model_unavailable",
            "complexity_audit_failed",
        ]
        for code in new_codes:
            assert code in ERROR_CODES
            block = ComplexityBlock(
                task_id="TASK-1",
                assessment_id="assess-1",
                code=code,
                message="test",
            )
            assert block.code == code
        # Unknown code should still be rejected
        with pytest.raises(ValidationError, match="unknown error code"):
            ComplexityBlock(task_id="TASK-1", code="unknown_code", message="test")


class TestBackwardCompatibility:
    """Backward compatibility tests for old payloads."""

    def test_roster_config_without_complexity_field(self):
        """Old roster config without complexity field should deserialize."""
        # Simulate old JSON without complexity field
        old_json = '{"seats": [{"label": "test", "kind": "native"}]}'
        config = RosterConfig.model_validate_json(old_json)
        assert config.complexity is not None  # Gets default
        assert config.complexity.version == "v1"

    def test_planned_task_without_assessment_id(self):
        """Old planned task without assessment_id should deserialize."""
        old_json = '{"task_id": "TASK-1", "task_file": "x.md", "seat_label": "s1"}'
        task = PlannedTask.model_validate_json(old_json)
        assert task.assessment_id == ""

    def test_attempt_record_without_assessment_id(self):
        """Old attempt record without assessment_id should deserialize."""
        old_json = '{"attempt": 1, "seat_label": "s1", "started_at": "2026-01-01T00:00:00Z"}'
        rec = AttemptRecord.model_validate_json(old_json)
        assert rec.assessment_id == ""

    def test_native_prep_without_assessment_id(self):
        """Old native prep without assessment_id should deserialize."""
        old_json = '{"task_id": "TASK-1", "task_file": "x.md", "branch": "b", "worktree_path": "/tmp/wt", "seat_label": "s1"}'
        prep = NativePrep.model_validate_json(old_json)
        assert prep.assessment_id == ""

    def test_coder_plan_without_assessments_and_blocks(self):
        """Old coder plan without assessments/routing_blocks should deserialize."""
        old_json = '{"feature_id": "F1", "feature": "feat", "feature_branch": "feat-F1", "index_path": "idx.json", "pending": [], "blocked": [], "chunks": [], "roster": [], "orphan_branches": []}'
        plan = CoderPlan.model_validate_json(old_json)
        assert plan.assessments == {}
        assert plan.routing_blocks == []

    def test_new_fields_survive_json_round_trip(self):
        """New fields survive JSON serialization/deserialization."""
        config = RosterConfig(seats=[RosterSeat(label="s1", kind="native")])
        json_str = config.model_dump_json()
        restored = RosterConfig.model_validate_json(json_str)
        assert restored.complexity.version == "v1"
        assert restored.complexity.score_threshold == 5

        task = PlannedTask(task_id="TASK-1", task_file="x.md", seat_label="s1", assessment_id="assess-1")
        json_str = task.model_dump_json()
        restored = PlannedTask.model_validate_json(json_str)
        assert restored.assessment_id == "assess-1"

        rec = AttemptRecord(attempt=1, seat_label="s1", started_at="t", assessment_id="assess-1")
        json_str = rec.model_dump_json()
        restored = AttemptRecord.model_validate_json(json_str)
        assert restored.assessment_id == "assess-1"

        prep = NativePrep(
            task_id="TASK-1",
            task_file="x.md",
            branch="b",
            worktree_path="/tmp/wt",
            seat_label="s1",
            assessment_id="assess-1",
        )
        json_str = prep.model_dump_json()
        restored = NativePrep.model_validate_json(json_str)
        assert restored.assessment_id == "assess-1"
