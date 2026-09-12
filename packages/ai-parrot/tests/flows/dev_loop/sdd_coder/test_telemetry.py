import asyncio
import json
import os
import pytest
from pathlib import Path
from unittest.mock import MagicMock

from parrot.flows.dev_loop.sdd_coder.models import AttemptRecord
from parrot.flows.dev_loop.sdd_coder.telemetry import (
    MAX_LINE_BYTES,
    AttemptUsageRow,
    OutcomeRow,
    CoderTelemetrySink,
    build_attempt_row,
    feature_file_name,
    resolve_durable_root,
)


def _row(**over) -> AttemptUsageRow:
    base = dict(
        ts="2026-09-12T00:00:00+00:00",
        attempt_uid="a" * 32,
        feature_id="FEAT-554",
        task_id="TASK-1",
        attempt=1,
    )
    base.update(over)
    return AttemptUsageRow(**base)


class TestRowShape:
    def test_unknown_usage_round_trips(self):
        row = _row(turn_series=[(7, None, None)])
        assert json.loads(row.model_dump_json())["turn_series"] == [[7, None, None]]

    def test_worst_case_fits_the_budget(self):
        # Every string field at max_length + 101 turns
        turn_series = [(i, 1000, 1000) for i in range(101)]
        row = _row(
            attempt_uid="a" * 64,
            job_id="j" * 64,
            feature_id="f" * 64,
            task_id="t" * 64,
            seat_label="s" * 32,
            backend="b" * 32,
            configured_model="m" * 200,
            resolved_model="r" * 200,
            terminal="t" * 16,
            error_class="e" * 120,
            enforcement="e" * 16,
            turn_series=turn_series,
        )
        serialized = row.model_dump_json().encode("utf-8")
        assert len(serialized) <= MAX_LINE_BYTES
        print(f"Worst-case row size: {len(serialized)} bytes")


class TestFeatureFileName:
    @pytest.mark.parametrize("bad", ["../etc", "a/b", "", "x" * 65])
    def test_rejects_unsafe(self, bad):
        with pytest.raises(ValueError):
            feature_file_name(bad)

    def test_accepts_safe(self):
        assert feature_file_name("FEAT-554") == "FEAT-554.jsonl"


class TestDurableRoot:
    def test_refuses_path_under_worktree_base(self, tmp_path):
        wt_base = tmp_path / "wt"
        wt_base.mkdir()
        inside = wt_base / "inside"

        # Configured path inside worktree base
        with pytest.raises(ValueError, match="cannot be inside or equal to worktree base path"):
            resolve_durable_root(str(inside), worktree_base_path=str(wt_base))

        # Configured path equal to worktree base
        with pytest.raises(ValueError, match="cannot be inside or equal to worktree base path"):
            resolve_durable_root(str(wt_base), worktree_base_path=str(wt_base))

        # Relative configured path
        with pytest.raises(ValueError, match="must be absolute"):
            resolve_durable_root("relative/path", worktree_base_path=str(wt_base))

    def test_derives_main_checkout(self, tmp_path):
        # We can run resolve_durable_root with configured=None and verify it resolves
        # to a path outside the worktree base path.
        wt_base = tmp_path / "wt"
        wt_base.mkdir()

        resolved = resolve_durable_root(None, worktree_base_path=str(wt_base))
        assert resolved.is_absolute()
        assert "artifacts/logs/sdd-coder-usage" in str(resolved)
        assert resolved != wt_base
        assert wt_base not in resolved.parents


class TestProjection:
    def test_never_persists_exception_text(self):
        # Create an AttemptRecord with sensitive error text
        record = AttemptRecord(
            attempt=1,
            seat_label="seat-1",
            backend="bedrock",
            model="anthropic.claude-3",
            started_at="2026-09-12T00:00:00+00:00",
            ended_at="2026-09-12T00:01:00+00:00",
            duration_s=60.0,
            usage={"input_tokens": 100, "output_tokens": 50},
            error="SECRET-TOKEN-XYZ: database connection failed",
        )
        # Set extra attributes that build_attempt_row expects
        # (task_id is NOT a record field — it is a required build_attempt_row
        # parameter, supplied by the caller at the engine layer).
        record.attempt_uid = "a" * 32
        record.resolved_model = "anthropic.claude-3-resolved"
        record.turns = 3
        record.terminal = "failed"
        record.error_class = "DatabaseError"
        record.declared_files_known = True
        record.turns_with_unknown_usage = 0
        # `budget_report` is `BudgetReport.model_dump()` — its field names are
        # UNPREFIXED (verified: parrot/models/token_budget.py:122-158). Only
        # this row's OWN fields carry the `ledger_` prefix.
        record.budget_report = {
            "input_tokens": 120,
            "output_tokens": 60,
            "settled_estimate_input_tokens": 10,
            "released_estimate_tokens": 5,
            "uncertain_tokens": 0,
            "overrun_tokens": 0,
            "counting_methods": ["exact"],
            "accounting_complete": True,
            "policy": {"enforcement": "observe"},
        }
        record.turn_series = [(1, 50, 25)]

        row = build_attempt_row(
            record, feature_id="FEAT-554", job_id="job-123", task_id="TASK-1", declared_files=5
        )
        serialized = row.model_dump_json()

        assert "SECRET-TOKEN-XYZ" not in serialized
        assert "database connection failed" not in serialized
        assert row.error_class == "DatabaseError"
        assert row.calibration_eligible is True
        assert row.task_id == "TASK-1"
        # The whole point of this projection: both accountings side by side.
        # Assert the REAL unprefixed->prefixed mapping actually landed —
        # a prior version of this test used the wrong ("ledger_"-prefixed)
        # source keys and would have passed even if every ledger_* field on
        # the row stayed None.
        assert row.ledger_input_tokens == 120
        assert row.ledger_output_tokens == 60
        assert row.ledger_settled_estimate_input_tokens == 10
        assert row.ledger_released_estimate_tokens == 5
        assert row.ledger_accounting_complete is True
        assert row.ledger_counting_methods == ["exact"]
        assert row.enforcement == "observe"

    def test_calibration_eligible_conditions(self):
        record = AttemptRecord(
            attempt=1,
            seat_label="seat-1",
            started_at="2026-09-12T00:00:00+00:00",
        )
        record.attempt_uid = "a" * 32

        # Case 1: accounting incomplete
        record.turns_with_unknown_usage = 0
        record.budget_report = {"accounting_complete": False}
        row = build_attempt_row(record, feature_id="FEAT-554", job_id="job-123", task_id="TASK-1", declared_files=None)
        assert row.calibration_eligible is False

        # Case 2: turns with unknown usage > 0
        record.turns_with_unknown_usage = 1
        record.budget_report = {"accounting_complete": True}
        row = build_attempt_row(record, feature_id="FEAT-554", job_id="job-123", task_id="TASK-1", declared_files=None)
        assert row.calibration_eligible is False

        # Case 3: complete and 0 unknown
        record.turns_with_unknown_usage = 0
        record.budget_report = {"accounting_complete": True}
        row = build_attempt_row(record, feature_id="FEAT-554", job_id="job-123", task_id="TASK-1", declared_files=None)
        assert row.calibration_eligible is True


class TestSink:
    @pytest.mark.asyncio
    async def test_unwritable_root_suppresses_warnings(self, tmp_path, caplog):
        # Create a path that is a file, so mkdir will fail
        unwritable = tmp_path / "file_blocking_dir"
        unwritable.touch()

        sink = CoderTelemetrySink(unwritable)
        row = _row()

        import logging

        with caplog.at_level(logging.WARNING):
            for _ in range(10):
                await sink.write_attempt(row)

        # Should only log once
        warnings = [r for r in caplog.records if r.levelname == "WARNING"]
        assert len(warnings) == 1
        assert "Telemetry write failed" in warnings[0].message

    @pytest.mark.asyncio
    async def test_oversized_row_dropped(self, tmp_path, caplog):
        sink = CoderTelemetrySink(tmp_path)
        # Create a row that exceeds MAX_LINE_BYTES
        row = _row(turn_series=[(i, 1000, 1000) for i in range(500)])

        import logging

        with caplog.at_level(logging.WARNING):
            await sink.write_attempt(row)

        warnings = [r for r in caplog.records if r.levelname == "WARNING"]
        assert len(warnings) == 1
        assert "Oversized telemetry row dropped" in warnings[0].message

        # Verify file is empty or doesn't exist
        file_path = tmp_path / "FEAT-554.jsonl"
        assert not file_path.exists()

    @pytest.mark.asyncio
    async def test_concurrent_appends(self, tmp_path):
        sink = CoderTelemetrySink(tmp_path)
        rows = [_row(attempt_uid=f"concurrent-uid-{i:02d}") for i in range(20)]

        # Run 20 concurrent writes
        await asyncio.gather(*(sink.write_attempt(r) for r in rows))

        file_path = tmp_path / "FEAT-554.jsonl"
        assert file_path.exists()

        lines = file_path.read_text("utf-8").splitlines()
        assert len(lines) == 20

        uids = set()
        for line in lines:
            data = json.loads(line)
            assert data["kind"] == "attempt"
            uids.add(data["attempt_uid"])

        assert len(uids) == 20
        assert uids == {f"concurrent-uid-{i:02d}" for i in range(20)}
