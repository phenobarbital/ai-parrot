"""Per-seat roll-up of sdd-coder job journals (``sdd_coder/summary.py``)."""

from __future__ import annotations

import json
from pathlib import Path

from parrot.flows.dev_loop.sdd_coder.models import AttemptRecord, CoderJob, TaskResult
from parrot.flows.dev_loop.sdd_coder.summary import JOURNAL_DIR, load_jobs, summarize_job_seats


def _attempt(seat: str, attempt: int = 1, *, backend="nova", model="qwen", terminal="completed", usage=None, dur=10.0):
    return AttemptRecord(
        attempt=attempt,
        seat_label=seat,
        backend=backend,
        model=model,
        started_at="2026-09-12T00:00:00Z",
        duration_s=dur,
        usage=usage or {},
        terminal=terminal,
    )


def _job(job_id: str, tasks: list[TaskResult]) -> CoderJob:
    return CoderJob(
        job_id=job_id,
        feature_id="FEAT-1",
        chunk_task_ids=[t.task_id for t in tasks],
        state="done",
        started_at="2026-09-12T00:00:00Z",
        tasks=tasks,
    )


def _two_seat_job() -> CoderJob:
    return _job(
        "j1",
        [
            TaskResult(
                task_id="TASK-1",
                outcome="merged",
                attempts=[_attempt("qwen", usage={"input_tokens": 1000, "output_tokens": 200}, dur=30.0)],
            ),
            TaskResult(
                task_id="TASK-2",
                outcome="merged",
                attempts=[
                    _attempt("qwen", 1, terminal="failed", usage={"input_tokens": 500, "output_tokens": 50}, dur=12.0),
                    _attempt("qwen", 2, usage={"input_tokens": 700, "output_tokens": 90}, dur=20.0),
                ],
            ),
            TaskResult(
                task_id="TASK-3",
                outcome="failed",
                attempts=[_attempt("codex-spark", backend="codex", model="", terminal="failed", dur=61.0)],
            ),
        ],
    )


def test_groups_attempts_by_seat_with_retries_failures_and_tokens():
    seats = {s.seat: s for s in summarize_job_seats([_two_seat_job()])}

    qwen = seats["qwen"]
    assert qwen.backend == "nova" and qwen.model == "qwen"
    assert qwen.tasks_handled == ["TASK-1", "TASK-2"]
    assert qwen.tasks_merged == 2
    assert qwen.attempts == 3 and qwen.retries == 1 and qwen.failures == 1
    assert qwen.duration_s == 62.0
    assert qwen.input_tokens == 2200 and qwen.output_tokens == 340
    assert qwen.usage_known is True

    codex = seats["codex-spark"]
    assert codex.tasks_handled == ["TASK-3"] and codex.tasks_merged == 0
    assert codex.failures == 1 and codex.attempts == 1
    assert codex.input_tokens is None and codex.output_tokens is None
    assert codex.usage_known is False  # codex CLI never reports usage — n/a, never 0


def test_rows_are_ordered_by_seat_label():
    assert [s.seat for s in summarize_job_seats([_two_seat_job()])] == ["codex-spark", "qwen"]


def test_latest_job_outcome_wins_across_jobs():
    first = _job("j1", [TaskResult(task_id="TASK-9", outcome="failed", attempts=[_attempt("qwen", terminal="failed")])])
    second = _job("j2", [TaskResult(task_id="TASK-9", outcome="merged", attempts=[_attempt("qwen", 1)])])
    (qwen,) = summarize_job_seats([first, second])
    assert qwen.tasks_handled == ["TASK-9"]
    assert qwen.tasks_merged == 1
    assert qwen.attempts == 2 and qwen.failures == 1


def test_resolved_model_outranks_configured_model():
    record = _attempt("qwen")
    record = record.model_copy(update={"resolved_model": "qwen.qwen3-coder-480b"})
    (row,) = summarize_job_seats([_job("j", [TaskResult(task_id="T", outcome="merged", attempts=[record])])])
    assert row.model == "qwen.qwen3-coder-480b"


def test_empty_input_yields_no_rows():
    assert summarize_job_seats([]) == []


def test_load_jobs_reads_journals_and_skips_garbage(tmp_path: Path):
    journal_dir = tmp_path / JOURNAL_DIR
    journal_dir.mkdir(parents=True)
    (journal_dir / "job-0001.json").write_text(_two_seat_job().model_dump_json())
    (journal_dir / "job-0002.json").write_text("{not json")

    jobs = load_jobs(str(tmp_path))

    assert [j.job_id for j in jobs] == ["j1"]
    assert summarize_job_seats(jobs)[1].seat == "qwen"


def test_load_jobs_without_journal_dir_is_empty(tmp_path: Path):
    assert load_jobs(str(tmp_path)) == []
    assert not (tmp_path / JOURNAL_DIR).exists()


def test_journal_roundtrip_matches_engine_shape(tmp_path: Path):
    """The journal is `CoderJob.model_dump_json(indent=2)` — exactly what load_jobs parses."""
    journal_dir = tmp_path / JOURNAL_DIR
    journal_dir.mkdir(parents=True)
    job = _two_seat_job()
    (journal_dir / f"{job.job_id}.json").write_text(json.dumps(json.loads(job.model_dump_json()), indent=2))
    assert load_jobs(str(tmp_path))[0] == job
