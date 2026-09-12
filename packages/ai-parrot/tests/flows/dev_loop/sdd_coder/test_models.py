import pytest
from pydantic import ValidationError

from parrot.flows.dev_loop.sdd_coder import (
    ERROR_CODES,
    CoderError,
    CoderRunChunkArgs,
    CoderWaitArgs,
    RosterSeat,
)
from parrot.flows.dev_loop.sdd_coder.models import AttemptRecord, TaskResult


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
        rec = AttemptRecord(
            attempt=1, seat_label="qwen", started_at="t", turn_series=[(7, None, None)]
        )
        assert rec.turn_series[0] == (7, None, None)

    def test_nested_in_task_result(self):
        rec = AttemptRecord(attempt=1, seat_label="qwen", started_at="t")
        assert TaskResult(task_id="TASK-1", outcome="merged", attempts=[rec]).attempts[0] is rec
