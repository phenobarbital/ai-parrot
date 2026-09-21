"""Regression scenarios for FEAT-584; use isolated fixtures, never live providers."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from parrot.flows.dev_loop.sdd_coder.evidence import ExecutionEvidenceStore
from parrot.flows.dev_loop.sdd_coder.models import (
    AttemptRecord,
    CoderJob,
    CoderJobView,
    CoderPlan,
    NativePrep,
    OrphanBranch,
    PlanChunk,
    PlannedTask,
    SeatProbeResult,
    TaskResult,
)
from parrot.flows.dev_loop.sdd_coder.summary import summarize_job_seats
from parrot.flows.dev_loop.sdd_coder.views import COMPACT_VIEW_BUDGET_BYTES, project_response

EXECUTION_ID = "11111111-1111-4111-8111-111111111111"
FOREIGN_EXECUTION_ID = "22222222-2222-4222-8222-222222222222"


def _seat(label: str) -> SeatProbeResult:
    return SeatProbeResult(label=label, kind="mcp", backend="nova", available=True)


def _small_plan(*, pending: list[str], blocked: list[str]) -> CoderPlan:
    chunk = PlanChunk(
        index=0,
        tasks=[
            PlannedTask(task_id=t, task_file=f"sdd/tasks/active/{t}.md", seat_label="a", assessment_id=f"asm-{t}")
            for t in pending
        ],
    )
    return CoderPlan(
        feature_id="FEAT-584",
        feature="demo",
        feature_branch="feat-FEAT-584-demo",
        index_path="sdd/tasks/index/demo.json",
        pending=pending,
        blocked=blocked,
        chunks=[chunk],
        roster=[_seat("a"), _seat("b")],
        orphan_branches=[OrphanBranch(task_id="TASK-9999", branch="demo--TASK-9999-a1")],
        execution_id=EXECUTION_ID,
        pool_generation=3,
    )


def _job_view_with_heavy_attempts(n_tasks: int, turns_per_task: int) -> CoderJobView:
    tasks = []
    for i in range(n_tasks):
        task_id = f"TASK-{1000 + i}"
        attempt = AttemptRecord(
            attempt=1,
            seat_label="a",
            backend="nova",
            model="qwen",
            started_at="2026-09-21T00:00:00+00:00",
            ended_at="2026-09-21T00:05:00+00:00",
            duration_s=300.0,
            usage={"input_tokens": 1000, "output_tokens": 500, "cache_read_tokens": 200},
            attempt_uid=f"attempt-{i}",
            turns=turns_per_task,
            # The heavy, per-turn telemetry a compact view must drop (recoverable
            # in full from the durable snapshot artifact instead).
            turn_series=[(n, 100 + n, 50 + n) for n in range(turns_per_task)],
            budget_report={"window": 200000, "used": 12345, "detail": "x" * 200},
        )
        tasks.append(TaskResult(task_id=task_id, outcome="merged", branch=f"demo--{task_id}-a1", attempts=[attempt]))
    job = CoderJob(
        job_id="job-1",
        feature_id="FEAT-584",
        chunk_task_ids=[t.task_id for t in tasks],
        state="done",
        started_at="2026-09-21T00:00:00+00:00",
        ended_at="2026-09-21T00:05:00+00:00",
        tasks=tasks,
        execution_id=EXECUTION_ID,
    )
    return CoderJobView(**job.model_dump(), seats=summarize_job_seats([job]))


def _canonical_bytes(data: dict) -> int:
    return len(json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode("utf-8"))


async def _read_full(store: ExecutionEvidenceStore, execution_id: str, artifact_id: str) -> str:
    """Walk every page of one artifact (16 KiB reads) and reassemble its full content."""
    parts: list[str] = []
    offset = 0
    while True:
        page = await store.read_artifact(execution_id, artifact_id, offset=offset, limit=16384)
        parts.append(page["content"])
        if page["eof"]:
            return "".join(parts)
        offset = page["next_offset"]


async def test_full_default_wire_compatibility(tmp_path: Path) -> None:
    """Omitting response_mode preserves old plan/status/wait payloads and native feedback."""
    store = ExecutionEvidenceStore(tmp_path)
    plan = _small_plan(pending=["TASK-1", "TASK-2"], blocked=["TASK-3"])

    result = await project_response(plan, mode="full", execution_id=EXECUTION_ID, store=store)

    assert result == plan.model_dump(mode="json")
    # No projection metadata leaks into the unmodified full contract.
    assert "evidence_ref" not in result
    assert "required_pages_remaining" not in result
    assert "projection" not in result

    # `coder_prepare_native` never routes through response_mode at all -- confirm a
    # generic full projection still never touches/truncates a long coder_feedback.
    long_feedback = "binding lesson: " + ("do not truncate this. " * 200)
    prep = NativePrep(
        task_id="TASK-1",
        task_file="sdd/tasks/active/TASK-1.md",
        branch="demo--TASK-1-a1",
        worktree_path="/tmp/demo--TASK-1-a1",
        seat_label="h",
        coder_feedback=long_feedback,
        execution_id=EXECUTION_ID,
    )
    prep_result = await project_response(prep, mode="full", execution_id=EXECUTION_ID, store=store)
    assert prep_result["coder_feedback"] == long_feedback


async def test_mandatory_pages_and_roundtrip(tmp_path: Path) -> None:
    """Huge blocker sets stay fully recoverable and prevent dispatch before pages are read."""
    store = ExecutionEvidenceStore(tmp_path)
    full_blocked = [f"TASK-{n:05d}" for n in range(6000)]
    plan = _small_plan(pending=["TASK-1"], blocked=full_blocked)

    result = await project_response(plan, mode="compact", execution_id=EXECUTION_ID, store=store)

    # The compact view itself always respects the 16 KiB budget (spec AC4).
    assert _canonical_bytes(result) <= COMPACT_VIEW_BUDGET_BYTES

    # The inline copy was truncated -- a caller must not treat it as the whole set.
    assert len(result["blocked"]) < len(full_blocked)
    assert result["required_pages_remaining"], "an oversized blocked list must publish a mandatory page"
    page_ref = next(p for p in result["required_pages_remaining"] if p["field"] == "blocked")

    # Recovering the page reconstructs the COMPLETE, untruncated original list -- no id
    # is ever silently dropped, only paginated into its own durable artifact.
    recovered_text = await _read_full(store, EXECUTION_ID, page_ref["artifact_id"])
    assert json.loads(recovered_text)["ids"] == full_blocked

    # The plan's own full snapshot is ALSO recoverable via the same mechanism.
    full_ref = result["evidence_ref"]
    full_text = await _read_full(store, EXECUTION_ID, full_ref["artifact_id"])
    recovered_plan = json.loads(full_text)
    assert recovered_plan["blocked"] == full_blocked


async def test_byte_reduction_and_foreign_artifact(tmp_path: Path) -> None:
    """Representative plan shrinks at least 50 percent; cross-execution artifact access fails."""
    store = ExecutionEvidenceStore(tmp_path)
    job = _job_view_with_heavy_attempts(n_tasks=20, turns_per_task=50)

    full_dump = job.model_dump(mode="json")
    full_bytes = _canonical_bytes(full_dump)

    result = await project_response(job, mode="compact", execution_id=EXECUTION_ID, store=store)
    compact_bytes = _canonical_bytes(result)

    assert compact_bytes <= full_bytes * 0.5, (full_bytes, compact_bytes)

    # Every task outcome/decision survives the projection -- never hidden.
    assert {t["task_id"] for t in result["tasks"]} == {t["task_id"] for t in full_dump["tasks"]}
    assert all(t["outcome"] == "merged" for t in result["tasks"])
    # The heavy per-turn telemetry is what was dropped, never the decision itself.
    for task in result["tasks"]:
        for attempt in task["attempts"]:
            assert "turn_series" not in attempt
            assert "usage" not in attempt
            assert "budget_report" not in attempt

    # Cross-execution access to the SAME artifact_id is always confined -- never found.
    full_ref = result["evidence_ref"]
    with pytest.raises(FileNotFoundError):
        await store.read_artifact(FOREIGN_EXECUTION_ID, full_ref["artifact_id"])
