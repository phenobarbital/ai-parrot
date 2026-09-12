"""Unit tests for sdd-coder usage analysis (FEAT-554)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.analyze_sdd_coder_usage import load_rows, bucket_of, recommend


def _write(tmp_path: Path, rows: list[dict]) -> Path:
    """Write rows to a JSONL file in tmp_path and return the directory."""
    path = tmp_path / "FEAT-554.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    return tmp_path


def _outcome_for(attempt_row: dict, *, outcome: str = "merged", event_seq: int = 1) -> dict:
    """Build the `outcome` JSONL line pairing with one `attempt` row.

    `recommend()`'s sample-count gate is scoped to MERGED attempts (AC-13:
    "withholds a recommendation below 12 merged attempts") — an attempt row
    with no paired outcome row joins to `outcome=None` and is excluded from
    that gate entirely, so every `TestRecommendation` fixture below needs a
    real outcome row per attempt, not just the attempt row on its own.
    """
    return {
        "kind": "outcome",
        "attempt_uid": attempt_row["attempt_uid"],
        "job_id": attempt_row["job_id"],
        "feature_id": attempt_row["feature_id"],
        "task_id": attempt_row["task_id"],
        "attempt": attempt_row["attempt"],
        "event_seq": event_seq,
        "outcome": outcome,
    }


class TestJoin:
    """Test join hazards: latest outcome wins, orphan exclusion, duplicate detection."""

    def test_latest_outcome_wins(self, tmp_path: Path):
        """One attempt + two outcomes (seq 1, 2); assert joined row with seq 2 outcome."""
        rows = [
            {
                "kind": "attempt",
                "attempt_uid": "uid-001",
                "job_id": "job-1",
                "feature_id": "feat-1",
                "task_id": "task-1",
                "attempt": 1,
                "seat_label": "seat-a",
                "backend": "bedrock",
                "configured_model": "claude-3-haiku",
                "resolved_model": "claude-3-haiku",
                "duration_s": 10.0,
                "turns": 5,
                "terminal": "completed",
                "error_class": "",
                "declared_files": 2,
                "declared_files_known": True,
                "ledger_input_tokens": 100,
                "ledger_output_tokens": 50,
                "calibration_eligible": True,
            },
            {
                "kind": "outcome",
                "attempt_uid": "uid-001",
                "job_id": "job-1",
                "feature_id": "feat-1",
                "task_id": "task-1",
                "attempt": 1,
                "event_seq": 1,
                "outcome": "merge_conflict",
                "conflict_file_count": 1,
                "unexpected_file_count": 0,
            },
            {
                "kind": "outcome",
                "attempt_uid": "uid-001",
                "job_id": "job-1",
                "feature_id": "feat-1",
                "task_id": "task-1",
                "attempt": 1,
                "event_seq": 2,
                "outcome": "merged",
                "conflict_file_count": 0,
                "unexpected_file_count": 0,
            },
        ]

        root = _write(tmp_path, rows)
        df = load_rows(root)

        assert len(df) == 1
        assert df.iloc[0]["outcome"] == "merged"

    def test_orphan_outcome_excluded(self, tmp_path: Path):
        """An outcome whose attempt_uid has no attempt row is excluded."""
        rows = [
            {
                "kind": "attempt",
                "attempt_uid": "uid-001",
                "job_id": "job-1",
                "feature_id": "feat-1",
                "task_id": "task-1",
                "attempt": 1,
                "seat_label": "seat-a",
                "backend": "bedrock",
                "configured_model": "claude-3-haiku",
                "resolved_model": "claude-3-haiku",
                "duration_s": 10.0,
                "turns": 5,
                "terminal": "completed",
                "error_class": "",
                "declared_files": 2,
                "declared_files_known": True,
                "ledger_input_tokens": 100,
                "ledger_output_tokens": 50,
                "calibration_eligible": True,
            },
            {
                "kind": "outcome",
                "attempt_uid": "uid-orphan",
                "job_id": "job-1",
                "feature_id": "feat-1",
                "task_id": "task-1",
                "attempt": 1,
                "event_seq": 1,
                "outcome": "merged",
                "conflict_file_count": 0,
                "unexpected_file_count": 0,
            },
        ]

        root = _write(tmp_path, rows)
        df = load_rows(root)

        # Should only have the one valid attempt, orphan outcome excluded
        assert len(df) == 1
        assert df.iloc[0]["attempt_uid"] == "uid-001"

    def test_duplicate_attempt_uid_raises(self, tmp_path: Path):
        """Two attempt rows with the same attempt_uid raises ValueError."""
        rows = [
            {
                "kind": "attempt",
                "attempt_uid": "uid-dup",
                "job_id": "job-1",
                "feature_id": "feat-1",
                "task_id": "task-1",
                "attempt": 1,
                "seat_label": "seat-a",
                "backend": "bedrock",
                "configured_model": "claude-3-haiku",
                "resolved_model": "claude-3-haiku",
                "duration_s": 10.0,
                "turns": 5,
                "terminal": "completed",
                "error_class": "",
                "declared_files": 2,
                "declared_files_known": True,
                "ledger_input_tokens": 100,
                "ledger_output_tokens": 50,
                "calibration_eligible": True,
            },
            {
                "kind": "attempt",
                "attempt_uid": "uid-dup",
                "job_id": "job-1",
                "feature_id": "feat-1",
                "task_id": "task-1",
                "attempt": 2,
                "seat_label": "seat-a",
                "backend": "bedrock",
                "configured_model": "claude-3-haiku",
                "resolved_model": "claude-3-haiku",
                "duration_s": 10.0,
                "turns": 5,
                "terminal": "completed",
                "error_class": "",
                "declared_files": 2,
                "declared_files_known": True,
                "ledger_input_tokens": 100,
                "ledger_output_tokens": 50,
                "calibration_eligible": True,
            },
        ]

        root = _write(tmp_path, rows)

        with pytest.raises(ValueError) as exc_info:
            load_rows(root)

        assert "Duplicate attempt_uid" in str(exc_info.value)
        assert "uid-dup" in str(exc_info.value)


class TestBucketOf:
    """Test task-size bucket mapping."""

    def test_bucket_1_2(self):
        """Files 1-2 map to bucket '1-2'."""
        assert bucket_of(1, True) == "1-2"
        assert bucket_of(2, True) == "1-2"

    def test_bucket_3_4(self):
        """Files 3-4 map to bucket '3-4'."""
        assert bucket_of(3, True) == "3-4"
        assert bucket_of(4, True) == "3-4"

    def test_bucket_5_plus(self):
        """Files 5+ map to bucket '5+'."""
        assert bucket_of(5, True) == "5+"
        assert bucket_of(10, True) == "5+"
        assert bucket_of(100, True) == "5+"

    def test_unknown_when_not_known(self):
        """known=False maps to 'unknown'."""
        assert bucket_of(2, False) == "unknown"
        assert bucket_of(5, False) == "unknown"

    def test_unknown_when_none(self):
        """None declared_files maps to 'unknown'."""
        assert bucket_of(None, True) == "unknown"


class TestRecommendation:
    """Test recommendation output with sample counts, percentiles, error, ceiling."""

    def test_thin_segment_withholds_ceiling(self, tmp_path: Path):
        """11 merged attempts in one segment: percentiles marked unreliable, NO ceiling."""
        rows = []

        # Create 11 attempt rows with varying token counts
        for i in range(11):
            rows.append(
                {
                    "kind": "attempt",
                    "attempt_uid": f"uid-{i:03d}",
                    "job_id": "job-1",
                    "feature_id": "feat-1",
                    "task_id": "task-1",
                    "attempt": 1,
                    "seat_label": "seat-a",
                    "backend": "bedrock",
                    "configured_model": "claude-3-haiku",
                    "resolved_model": "claude-3-haiku",
                    "duration_s": 10.0,
                    "turns": 5,
                    "terminal": "completed",
                    "error_class": "",
                    "declared_files": 2,
                    "declared_files_known": True,
                    "ledger_input_tokens": 100 + i * 10,
                    "ledger_output_tokens": 50,
                    "calibration_eligible": True,
                }
            )

        rows = rows + [_outcome_for(r) for r in rows]
        root = _write(tmp_path, rows)
        df = load_rows(root)
        result = recommend(df, max_tokens=8192)

        assert len(result) == 1
        row = result.iloc[0]
        assert row["n_consumption"] == 11
        assert row["ceiling"] == "N/A"
        assert "unreliable" in row["status"]

    def test_ceiling_at_min_samples(self, tmp_path: Path):
        """12 merged attempts: ceiling is recommended."""
        rows = []

        for i in range(12):
            rows.append(
                {
                    "kind": "attempt",
                    "attempt_uid": f"uid-{i:03d}",
                    "job_id": "job-1",
                    "feature_id": "feat-1",
                    "task_id": "task-1",
                    "attempt": 1,
                    "seat_label": "seat-a",
                    "backend": "bedrock",
                    "configured_model": "claude-3-haiku",
                    "resolved_model": "claude-3-haiku",
                    "duration_s": 10.0,
                    "turns": 5,
                    "terminal": "completed",
                    "error_class": "",
                    "declared_files": 2,
                    "declared_files_known": True,
                    "ledger_input_tokens": 100 + i * 10,
                    "ledger_output_tokens": 50,
                    "calibration_eligible": True,
                }
            )

        rows = rows + [_outcome_for(r) for r in rows]
        root = _write(tmp_path, rows)
        df = load_rows(root)
        result = recommend(df, max_tokens=8192)

        assert len(result) == 1
        row = result.iloc[0]
        assert row["n_consumption"] == 12
        assert row["ceiling"] != "N/A"
        assert row["status"] == "OK"

    def test_sample_counts_reported_separately(self, tmp_path: Path):
        """n_consumption > n_calibration when some rows have calibration_eligible=False."""
        rows = []

        # First 12 rows: calibration_eligible=True
        for i in range(12):
            rows.append(
                {
                    "kind": "attempt",
                    "attempt_uid": f"uid-{i:03d}",
                    "job_id": "job-1",
                    "feature_id": "feat-1",
                    "task_id": "task-1",
                    "attempt": 1,
                    "seat_label": "seat-a",
                    "backend": "bedrock",
                    "configured_model": "claude-3-haiku",
                    "resolved_model": "claude-3-haiku",
                    "duration_s": 10.0,
                    "turns": 5,
                    "terminal": "completed",
                    "error_class": "",
                    "declared_files": 2,
                    "declared_files_known": True,
                    "ledger_input_tokens": 100,
                    "ledger_output_tokens": 50,
                    "calibration_eligible": True,
                }
            )

        # Add 3 rows with calibration_eligible=False
        for i in range(12, 15):
            rows.append(
                {
                    "kind": "attempt",
                    "attempt_uid": f"uid-{i:03d}",
                    "job_id": "job-1",
                    "feature_id": "feat-1",
                    "task_id": "task-1",
                    "attempt": 1,
                    "seat_label": "seat-a",
                    "backend": "bedrock",
                    "configured_model": "claude-3-haiku",
                    "resolved_model": "claude-3-haiku",
                    "duration_s": 10.0,
                    "turns": 5,
                    "terminal": "completed",
                    "error_class": "",
                    "declared_files": 2,
                    "declared_files_known": True,
                    "ledger_input_tokens": 100,
                    "ledger_output_tokens": 50,
                    "calibration_eligible": False,
                }
            )

        rows = rows + [_outcome_for(r) for r in rows]
        root = _write(tmp_path, rows)
        df = load_rows(root)
        result = recommend(df, max_tokens=8192)

        assert len(result) == 1
        row = result.iloc[0]
        assert row["n_consumption"] == 15
        assert row["n_calibration"] == 12
        assert row["n_consumption"] > row["n_calibration"]

    def test_unknown_bucket_no_recommendation(self, tmp_path: Path):
        """Rows with declared_files_known=False land in 'unknown' bucket with no ceiling."""
        rows = []

        for i in range(12):
            rows.append(
                {
                    "kind": "attempt",
                    "attempt_uid": f"uid-{i:03d}",
                    "job_id": "job-1",
                    "feature_id": "feat-1",
                    "task_id": "task-1",
                    "attempt": 1,
                    "seat_label": "seat-a",
                    "backend": "bedrock",
                    "configured_model": "claude-3-haiku",
                    "resolved_model": "claude-3-haiku",
                    "duration_s": 10.0,
                    "turns": 5,
                    "terminal": "completed",
                    "error_class": "",
                    "declared_files": 2,
                    "declared_files_known": False,  # Not known!
                    "ledger_input_tokens": 100,
                    "ledger_output_tokens": 50,
                    "calibration_eligible": True,
                }
            )

        rows = rows + [_outcome_for(r) for r in rows]
        root = _write(tmp_path, rows)
        df = load_rows(root)
        result = recommend(df, max_tokens=8192)

        assert len(result) == 1
        row = result.iloc[0]
        assert row["bucket"] == "unknown"
        assert row["ceiling"] == "N/A"

    def test_reserve_printed_with_ceiling(self, tmp_path: Path):
        """The absolute final_answer_reserve is printed next to each ceiling."""
        rows = []

        for i in range(12):
            rows.append(
                {
                    "kind": "attempt",
                    "attempt_uid": f"uid-{i:03d}",
                    "job_id": "job-1",
                    "feature_id": "feat-1",
                    "task_id": "task-1",
                    "attempt": 1,
                    "seat_label": "seat-a",
                    "backend": "bedrock",
                    "configured_model": "claude-3-haiku",
                    "resolved_model": "claude-3-haiku",
                    "duration_s": 10.0,
                    "turns": 5,
                    "terminal": "completed",
                    "error_class": "",
                    "declared_files": 2,
                    "declared_files_known": True,
                    "ledger_input_tokens": 100,
                    "ledger_output_tokens": 50,
                    "calibration_eligible": True,
                }
            )

        rows = rows + [_outcome_for(r) for r in rows]
        root = _write(tmp_path, rows)
        df = load_rows(root)
        result = recommend(df, max_tokens=8192)

        assert len(result) == 1
        row = result.iloc[0]
        # final_answer_reserve should be 2 * max_tokens = 16384
        assert row["final_answer_reserve"] == "16384"

    def test_provider_only_rows_contribute_to_percentiles(self, tmp_path: Path):
        """The `gemini` seat (provider-totals-only, no `ledger_*` fields, AC-15)
        must fall through to `provider_input_tokens`/`provider_output_tokens`
        for `total_tokens`, not silently vanish from every percentile.

        Regression coverage: a pandas DataFrame stores a missing value in a
        mixed-null numeric column as `NaN`, and `NaN is not None` is `True`
        in Python — an `is not None` check on a `ledger_*` column that is
        legitimately absent for this seat would wrongly treat it as present,
        compute `NaN + NaN = NaN`, and get dropped by `.notna()` instead of
        using the provider-total fallback.
        """
        # One companion row from a DIFFERENT seat with REAL ledger_* values —
        # this is what forces pandas to create numeric `ledger_input_tokens`/
        # `ledger_output_tokens` columns at all. Without it, no row in the
        # whole DataFrame ever sets those keys, so the columns never exist
        # and `row.get(...)` returns a genuine Python `None` (not `NaN`) even
        # under the buggy `is not None` check — which would make this test
        # pass regardless of the fix. `NaN` only appears when the SAME
        # column holds real values on other rows and is missing on this one.
        rows = [
            {
                "kind": "attempt",
                "attempt_uid": "uid-ledger-companion",
                "job_id": "job-1",
                "feature_id": "feat-1",
                "task_id": "task-1",
                "attempt": 1,
                "seat_label": "seat-a",
                "backend": "bedrock",
                "configured_model": "claude-3-haiku",
                "resolved_model": "claude-3-haiku",
                "duration_s": 10.0,
                "turns": 5,
                "terminal": "completed",
                "error_class": "",
                "declared_files": 2,
                "declared_files_known": True,
                "ledger_input_tokens": 500,
                "ledger_output_tokens": 100,
                "calibration_eligible": True,
            }
        ]
        for i in range(12):
            rows.append(
                {
                    "kind": "attempt",
                    "attempt_uid": f"uid-{i:03d}",
                    "job_id": "job-1",
                    "feature_id": "feat-1",
                    "task_id": "task-1",
                    "attempt": 1,
                    "seat_label": "gemini",
                    "backend": "google-compat",
                    "configured_model": "gemini-3.5-flash",
                    "resolved_model": "gemini-3.5-flash",
                    "duration_s": 10.0,
                    "turns": 5,
                    "terminal": "completed",
                    "error_class": "",
                    "declared_files": 2,
                    "declared_files_known": True,
                    # Explicitly None (not omitted) — `AttemptUsageRow`
                    # always emits these keys; this seat just has no
                    # budget adapter, so the ledger never settles anything.
                    "ledger_input_tokens": None,
                    "ledger_output_tokens": None,
                    "provider_input_tokens": 1000 + i * 10,
                    "provider_output_tokens": 200,
                    "calibration_eligible": False,
                }
            )
        rows = rows + [_outcome_for(r) for r in rows]

        root = _write(tmp_path, rows)
        df = load_rows(root)
        result = recommend(df, max_tokens=8192)

        assert len(result) == 2
        by_seat = {r["seat"]: r for _, r in result.iterrows()}
        gemini_row = by_seat["gemini"]
        assert gemini_row["n_consumption"] == 12
        assert gemini_row["ceiling"] != "N/A", "provider-total rows must still produce percentiles/a ceiling"

    def test_only_merged_attempts_count_toward_the_gate(self, tmp_path: Path):
        """A segment with 12 total attempts but only 5 `merged` ones must stay
        below MIN_SAMPLES — AC-13 gates on MERGED attempts specifically, not
        on every attempt regardless of outcome (a `failed`/`merge_conflict`
        row still burned tokens but must not inflate the merged-sample count
        that makes a ceiling trustworthy).
        """
        rows = []
        for i in range(12):
            rows.append(
                {
                    "kind": "attempt",
                    "attempt_uid": f"uid-{i:03d}",
                    "job_id": "job-1",
                    "feature_id": "feat-1",
                    "task_id": "task-1",
                    "attempt": 1,
                    "seat_label": "seat-a",
                    "backend": "bedrock",
                    "configured_model": "claude-3-haiku",
                    "resolved_model": "claude-3-haiku",
                    "duration_s": 10.0,
                    "turns": 5,
                    "terminal": "completed" if i < 5 else "failed",
                    "error_class": "" if i < 5 else "RuntimeError",
                    "declared_files": 2,
                    "declared_files_known": True,
                    "ledger_input_tokens": 100 + i * 10,
                    "ledger_output_tokens": 50,
                    "calibration_eligible": True,
                }
            )
        outcomes = [_outcome_for(r, outcome="merged" if idx < 5 else "failed") for idx, r in enumerate(rows)]
        rows = rows + outcomes

        root = _write(tmp_path, rows)
        df = load_rows(root)
        result = recommend(df, max_tokens=8192)

        assert len(result) == 1
        row = result.iloc[0]
        assert row["n_consumption"] == 5
        assert row["ceiling"] == "N/A"
        assert "unreliable" in row["status"]
