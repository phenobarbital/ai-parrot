import pytest
from pydantic import ValidationError

from parrot.flows.dev_loop.sdd_coder import (
    ERROR_CODES,
    CoderError,
    CoderRunChunkArgs,
    CoderWaitArgs,
    RosterSeat,
)
from parrot.flows.dev_loop.sdd_coder.models import (
    AttemptRecord,
    CoderFeedbackReportArgs,
    CoderPlanArgs,
    CoderPrepareNativeArgs,
    ExecutionPoolView,
    ExecutionSnapshot,
    PoolSeatView,
    RosterConfig,
    SeatProbeResult,
    SuspendModelArgs,
    TaskResult,
)
from parrot.knowledge.wiki.ledger.coder_suspensions import ModelKey, SuspensionPolicy

VALID_UUID = "11111111-1111-4111-8111-111111111111"


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
        dict(feature="f", worktree="rel/path", task_ids=["TASK-1"], execution_id=VALID_UUID),
        dict(feature="f", worktree="/abs", task_ids=["nope"], execution_id=VALID_UUID),
        dict(feature="f", worktree="/abs", task_ids=["TASK-1"], execution_id=VALID_UUID, extra=1),
        dict(feature="f", worktree="/abs", task_ids=["TASK-1"], execution_id="not-a-uuid"),
    ],
)
def test_run_chunk_args_reject_bad_input(kwargs):
    with pytest.raises(ValidationError):
        CoderRunChunkArgs(**kwargs)


def test_run_chunk_args_accepts_good_input():
    args = CoderRunChunkArgs(feature="f", worktree="/abs/path", task_ids=["TASK-1", "TASK-22"], execution_id=VALID_UUID)
    assert args.task_ids == ["TASK-1", "TASK-22"]
    assert args.execution_id == VALID_UUID


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
        assert rec.execution_id == ""  # FEAT-559: pre-existing records still parse without one.

    def test_turn_series_accepts_unknown_usage(self):
        rec = AttemptRecord(attempt=1, seat_label="qwen", started_at="t", turn_series=[(7, None, None)])
        assert rec.turn_series[0] == (7, None, None)

    def test_nested_in_task_result(self):
        rec = AttemptRecord(attempt=1, seat_label="qwen", started_at="t")
        assert TaskResult(task_id="TASK-1", outcome="merged", attempts=[rec]).attempts[0] is rec


def test_task_result_accepts_not_dispatched_with_no_synthetic_attempt():
    """FEAT-559: a task that lost its seat before admission is `not_dispatched`, never a fake attempt."""
    result = TaskResult(
        task_id="TASK-1", outcome="not_dispatched", diagnostics="not_dispatched: seat suspended before admission"
    )
    assert result.outcome == "not_dispatched"
    assert result.attempts == []


def test_roster_config_default_suspension_policy():
    """FEAT-559: every roster carries a usable default cooldown/summary-budget policy."""
    cfg = RosterConfig(seats=[RosterSeat(label="q", backend="nova")])
    assert cfg.suspension_policy == SuspensionPolicy()


def test_seat_probe_result_records_failed_primary_probe_metadata():
    """A primary probe can fail (structured metadata) while a configured fallback still succeeds."""
    result = SeatProbeResult(
        label="q",
        kind="mcp",
        backend="nova",
        available=True,
        model_used="qwen-fallback",
        fallback_used=True,
        probe_uid="probe-1",
        probe_observed_at="2026-09-16T00:00:00+00:00",
        probe_duration_s=1.2,
        probe_exception_class="TimeoutError",
    )
    assert result.available is True
    assert result.fallback_used is True
    assert result.probe_exception_class == "TimeoutError"


class TestExecutionModels:
    """FEAT-559 `ExecutionPoolView`/`PoolSeatView`/`ExecutionSnapshot` contracts."""

    def test_execution_models_reject_invalid_uuid_and_extra_fields(self):
        with pytest.raises(ValidationError):
            ExecutionPoolView(
                execution_id="not-a-uuid", feature_id="FEAT-559", worktree_path="/abs", status="active", generation=0
            )
        with pytest.raises(ValidationError):
            ExecutionSnapshot(
                execution_id="not-a-uuid",
                feature_id="FEAT-559",
                worktree_path="/abs",
                roster_fingerprint="fp",
                status="active",
                generation=0,
            )
        with pytest.raises(ValidationError):
            ExecutionPoolView(
                execution_id=VALID_UUID,
                feature_id="FEAT-559",
                worktree_path="/abs",
                status="active",
                generation=0,
                extra_field="nope",
            )
        with pytest.raises(ValidationError):
            PoolSeatView(label="q", kind="mcp", extra_field="nope")

        seat = PoolSeatView(
            label="q",
            kind="mcp",
            backend="nova",
            configured_model="qwen",
            resolved_key=ModelKey(backend="nova", model="qwen"),
            available=True,
        )
        view = ExecutionPoolView(
            execution_id=VALID_UUID,
            feature_id="FEAT-559",
            worktree_path="/abs",
            status="active",
            generation=0,
            seats=[seat],
        )
        assert view.seats[0].resolved_key.model == "qwen"

    def test_missing_execution_rejected_by_scoped_args(self):
        """Seven scoped tool schemas require execution_id; feedback_report never does (AC-1, AC-15)."""
        with pytest.raises(ValidationError):
            CoderPlanArgs(feature="f", worktree="/abs")
        with pytest.raises(ValidationError):
            CoderRunChunkArgs(feature="f", worktree="/abs", task_ids=["TASK-1"])
        with pytest.raises(ValidationError):
            CoderPrepareNativeArgs(feature="f", worktree="/abs", task_id="TASK-1")
        with pytest.raises(ValidationError):
            SuspendModelArgs(attempt_uid="a1", reason="timeout")
        with pytest.raises(ValidationError):
            CoderPlanArgs(feature="f", worktree="/abs", execution_id="not-a-uuid")

        good = CoderPlanArgs(feature="f", worktree="/abs", execution_id=VALID_UUID)
        assert good.execution_id == VALID_UUID

        # A repository-wide feedback report never starts or requires an execution.
        report_args = CoderFeedbackReportArgs(feature="f", worktree="/abs")
        assert report_args.feature == "f"
        assert not hasattr(report_args, "execution_id")
