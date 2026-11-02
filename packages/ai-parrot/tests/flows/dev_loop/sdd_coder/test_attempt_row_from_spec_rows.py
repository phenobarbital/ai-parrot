"""FEAT-783 M6 — attempt row derived from spec rows."""

from parrot.flows.dev_loop.sdd_coder.models import AttemptRecord
from parrot.flows.dev_loop.sdd_coder.telemetry import AttemptUsageRow, build_attempt_row
from parrot.observability.recorders.models import UsageRecord


def _attempt_record() -> AttemptRecord:
    """Build a minimal attempt with legacy provider counters."""
    return AttemptRecord(
        attempt=1,
        attempt_uid="attempt-uid-1",
        seat_label="development.w1",
        backend="codex",
        model="gpt-5",
        started_at="2026-10-31T00:00:00+00:00",
        usage={"input_tokens": 999, "output_tokens": 888},
    )


def _build_row(record: AttemptRecord, *, spec_rows: list[UsageRecord] | None = None) -> AttemptUsageRow:
    """Project an attempt with the stable identifiers used by these tests."""
    return build_attempt_row(
        record,
        feature_id="FEAT-783",
        job_id="job-1",
        task_id="TASK-4991",
        declared_files=4,
        spec_rows=spec_rows,
    )


def test_spec_rows_override_record_usage() -> None:
    record = _attempt_record()
    spec_rows = [
        UsageRecord(provider="openai", attempt_uid=record.attempt_uid, input_tokens=100, output_tokens=20),
        UsageRecord(provider="openai", attempt_uid=record.attempt_uid, input_tokens=50, output_tokens=10),
        UsageRecord(
            provider="openai",
            attempt_uid=record.attempt_uid,
            input_tokens=700,
            output_tokens=600,
            usage_reported=False,
        ),
        UsageRecord(provider="openai", attempt_uid="other-attempt", input_tokens=500, output_tokens=400),
    ]

    row = _build_row(record, spec_rows=spec_rows)

    assert row.provider_input_tokens == 150
    assert row.provider_output_tokens == 30


def test_no_spec_rows_keeps_legacy_path() -> None:
    row = _build_row(_attempt_record())

    assert row.provider_input_tokens == 999
    assert row.provider_output_tokens == 888
