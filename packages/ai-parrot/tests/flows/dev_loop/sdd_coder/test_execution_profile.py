"""Regression scenarios for FEAT-584; use isolated fixtures, never live providers.

Every scenario builds synthetic ``--events``/``--transcript`` JSONL fixtures
inline (out-of-order writes, overlapping categories, an immediate tool
result, absent receipts, cross-process clocks) and drives
``scripts.sdd.profile_execution.main`` -- the public CLI boundary -- never a
private helper directly. Nothing here is copied from a private transcript.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from scripts.sdd.profile_execution import main

_T0 = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)


def _ts(offset_s: float) -> str:
    return (_T0 + timedelta(seconds=offset_s)).isoformat()


def _write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.write_text("\n".join(json.dumps(record) for record in records) + "\n", encoding="utf-8")


def _event(kind: str, ts_offset: float, **kwargs: Any) -> dict[str, Any]:
    record: dict[str, Any] = {"kind": kind, "timestamp": _ts(ts_offset)}
    record.update(kwargs)
    return record


def _run_profiler(
    tmp_path: Path, events: list[dict[str, Any]], transcript: list[dict[str, Any]] | None
) -> dict[str, Any]:
    events_path = tmp_path / "events.jsonl"
    output_path = tmp_path / "report.json"
    _write_jsonl(events_path, events)

    argv = ["--events", str(events_path), "--output", str(output_path)]
    if transcript is not None:
        transcript_path = tmp_path / "transcript.jsonl"
        _write_jsonl(transcript_path, transcript)
        argv += ["--transcript", str(transcript_path)]

    exit_code = main(argv)
    assert exit_code == 0
    return json.loads(output_path.read_text(encoding="utf-8"))


def test_global_union_and_request_dedup(tmp_path: Path) -> None:
    """Overlapping categories are unioned once globally and streamed messages share one request."""
    events = [
        # Out-of-order on purpose: the review pair is written before the attempt pair closes.
        _event("review.started", 50.0, execution_id="exec-1"),
        _event("attempt.dispatched", 0.0, execution_id="exec-1", task_id="TASK-1", attempt_uid="a1"),
        _event("review.finished", 120.0, execution_id="exec-1"),
        _event("attempt.finished", 100.0, execution_id="exec-1", task_id="TASK-1", attempt_uid="a1"),
    ]
    # Three streamed deltas of ONE assistant turn, sharing a single request_id.
    transcript = [
        {"role": "assistant", "request_id": "req-1", "timestamp": _ts(10.0)},
        {"role": "assistant", "request_id": "req-1", "timestamp": _ts(11.0)},
        {"role": "assistant", "request_id": "req-1", "timestamp": _ts(12.0)},
    ]

    report = _run_profiler(tmp_path, events, transcript)

    # attempt: [0, 100]; review: [50, 120] -- global union is [0, 120] = 120s,
    # NOT 100 + 70 = 170s (the historical double-subtraction bug this fixes).
    assert report["active"]["union_s"] == 120.0
    buckets = report["active"]["category_buckets_s"]
    assert buckets["attempt"] == 100.0
    assert buckets["review"] == 70.0
    # Category buckets are independent and MAY overlap: their sum legitimately
    # exceeds the global union and must never be read as the total.
    assert sum(buckets.values()) > report["active"]["union_s"]

    # Three assistant rows, but only ONE request (spec AC14: requests != messages).
    assert report["requests"]["assistant_rows_total"] == 3
    assert report["requests"]["count"] == 1


def test_background_and_merge_identity(tmp_path: Path) -> None:
    """Immediate tool results and unrelated later merges cannot shorten or misattribute attempts."""
    events = [
        _event("background.launched", 0.0, execution_id="exec-2", job_id="job-1"),
        # The real receipt arrives 300s later -- NOT the ~1s an immediate
        # transcript tool_result would suggest.
        _event("background.finished", 300.0, execution_id="exec-2", job_id="job-1"),
        # Only the moment the result was OBSERVED is known -- no real dispatch
        # window -- so this must stay unresolved (span real = null), never
        # fabricated from its own single timestamp.
        _event("delivery.observed", 2.0, execution_id="exec-2", task_id="TASK-9", attempt_uid="a9"),
        # Two interleaved attempts of the SAME task: a1 starts first but
        # finishes LAST; a2 starts second, finishes first and is the only one
        # merged. A "next event" heuristic would misattribute a2's merge.
        _event("attempt.dispatched", 0.0, execution_id="exec-2", task_id="TASK-5", attempt_uid="a1"),
        _event("attempt.dispatched", 5.0, execution_id="exec-2", task_id="TASK-5", attempt_uid="a2"),
        _event("attempt.finished", 8.0, execution_id="exec-2", task_id="TASK-5", attempt_uid="a2"),
        _event("merge.finished", 9.0, execution_id="exec-2", task_id="TASK-5", attempt_uid="a2"),
        _event("attempt.finished", 10.0, execution_id="exec-2", task_id="TASK-5", attempt_uid="a1"),
    ]
    # An immediate tool_result acknowledging admission of the background job,
    # 1s after launch -- must have NO effect on the background span.
    transcript = [
        {
            "role": "tool",
            "request_id": "req-bg-ack",
            "timestamp": _ts(1.0),
            "tool_name": "Bash",
            "is_tool_result": True,
        }
    ]

    report = _run_profiler(tmp_path, events, transcript)

    background_spans = [span for span in report["active"]["spans"] if span["category"] == "background"]
    assert len(background_spans) == 1
    # The background span (300s) is long enough to also surface in the
    # explicit long_spans highlight list -- never silently excluded.
    assert any(span["category"] == "background" for span in report["active"]["long_spans"])
    assert background_spans[0]["duration_s"] == 300.0
    assert background_spans[0]["identity"]["job_id"] == "job-1"

    unresolved_kinds = [(u["kind"], u["identity"]["task_id"]) for u in report["active"]["unresolved_spans"]]
    assert ("delivery.observed", "TASK-9") in unresolved_kinds

    attempts_by_uid = {a["attempt_uid"]: a for a in report["attempts"]}
    assert attempts_by_uid["a1"]["merged_at"] is None
    assert attempts_by_uid["a1"]["finished_at"] == _ts(10.0)  # never shortened by a2's interleaved merge
    assert attempts_by_uid["a2"]["merged_at"] == _ts(9.0)


def test_unknown_tokens_long_requests_and_clock(tmp_path: Path) -> None:
    """Unknown values, long requests and cross-process clocks remain explicit."""
    events = [
        # Cross-process pairing: start and end disagree on process_id, so the
        # monotonic clock reading is not usable and must not be silently
        # treated as directly comparable.
        _event(
            "attempt.dispatched",
            0.0,
            execution_id="exec-3",
            task_id="TASK-7",
            attempt_uid="aX",
            payload={"process_id": "p1", "monotonic_s": 10.0},
        ),
        _event(
            "attempt.finished",
            50.0,
            execution_id="exec-3",
            task_id="TASK-7",
            attempt_uid="aX",
            payload={"process_id": "p2", "monotonic_s": 999.0},
        ),
        # Same-process pairing: the monotonic reading is trustworthy and
        # tracked separately from (and here, deliberately skewed against) the
        # UTC wall-clock duration.
        _event(
            "attempt.dispatched",
            0.0,
            execution_id="exec-3",
            task_id="TASK-8",
            attempt_uid="aY",
            payload={"process_id": "pA", "monotonic_s": 5.0},
        ),
        _event(
            "attempt.finished",
            40.0,
            execution_id="exec-3",
            task_id="TASK-8",
            attempt_uid="aY",
            payload={"process_id": "pA", "monotonic_s": 44.0},
        ),
    ]
    transcript = [
        # A 130s-long request -- must NOT be silently excluded (the historical
        # profiler dropped spans >= 120s).
        {"role": "assistant", "request_id": "req-A", "timestamp": _ts(0.0)},
        {
            "role": "assistant",
            "request_id": "req-A",
            "timestamp": _ts(130.0),
            "usage": {"input_tokens": 100, "output_tokens": 50},  # cache_* fields unknown
        },
        # A short request with every token field known.
        {
            "role": "assistant",
            "request_id": "req-B",
            "timestamp": _ts(200.0),
            "usage": {
                "input_tokens": 10,
                "cache_read_tokens": 5,
                "cache_creation_tokens": 2,
                "output_tokens": 3,
            },
        },
    ]

    report = _run_profiler(tmp_path, events, transcript)

    long_request_ids = {r["request_id"] for r in report["requests"]["long_requests"]}
    assert "req-A" in long_request_ids
    assert report["requests"]["long_requests"][0]["duration_s"] >= 120.0

    tokens = report["requests"]["tokens"]
    assert tokens["input_tokens_sum"] == 110  # 100 (req-A) + 10 (req-B)
    assert tokens["output_tokens_sum"] == 53  # 50 (req-A) + 3 (req-B)
    assert tokens["cache_read_tokens_sum"] == 5  # only req-B reports it
    assert tokens["cache_creation_tokens_sum"] == 2
    assert tokens["context_tokens_known_requests"] == 1  # req-B: all three known
    assert tokens["context_tokens_unknown_requests"] == 1  # req-A: cache_* missing

    spans_by_task = {span["identity"]["task_id"]: span for span in report["active"]["spans"]}
    cross_process_span = spans_by_task["TASK-7"]
    assert cross_process_span["clock_basis"] == "identity_paired"
    assert cross_process_span["duration_s"] == 50.0
    assert "duration_precise_s" not in cross_process_span  # never fabricated across processes

    same_process_span = spans_by_task["TASK-8"]
    assert same_process_span["clock_basis"] == "identity_paired+monotonic_same_process"
    assert same_process_span["duration_s"] == 40.0  # wall clock, still reported
    assert same_process_span["duration_precise_s"] == pytest.approx(39.0)  # monotonic, tracked separately
