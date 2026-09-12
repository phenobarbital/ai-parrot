"""Turn sdd-coder telemetry into a recommended token_budget (FEAT-554).

Reads the append-only JSONL dataset written by
`parrot.flows.dev_loop.sdd_coder.telemetry`, joins attempt rows to their
outcome events, and reports consumption percentiles plus estimation error per
(seat, task-size bucket).

Usage:
    python scripts/analyze_sdd_coder_usage.py --root artifacts/logs/sdd-coder-usage
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Tuple

import pandas as pd

MIN_SAMPLES: int = 12
"""Merged attempts required before a segment gets a recommended ceiling.

Below this the percentiles are printed and marked unreliable, but no ceiling is
suggested: a p95 over five samples is noise wearing the costume of a number.
"""

SIZE_BUCKETS: Tuple[Tuple[str, int, int], ...] = (("1-2", 1, 2), ("3-4", 3, 4), ("5+", 5, 10**6))
RESERVE_MULTIPLIER: int = 2
"""Recommended absolute final_answer_reserve = RESERVE_MULTIPLIER * max_tokens (spec §7)."""


def load_rows(root: Path) -> pd.DataFrame:
    """Glob `<root>/*.jsonl`, parse, and join attempt rows to outcome events.

    Three hazards, all silent if unhandled:

    * the join key is `attempt_uid` — `(feature_id, task_id, attempt)` recurs
      across jobs because attempt numbering restarts at 1 (spec §10 R3);
    * several outcome rows per attempt are EXPECTED (conflict then re-merge,
      engine.py:407) — the highest `event_seq` is effective (§10 R4);
    * an outcome with no attempt row is an incomplete pair: report and exclude,
      never count as zero tokens.

    A duplicate `attempt_uid` among ATTEMPT rows is a bug, not a retry: raise.
    """
    root = Path(root)

    # Read all JSONL files from root
    attempt_rows = []
    outcome_rows = []

    for jsonl_file in root.glob("*.jsonl"):
        with open(jsonl_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                    if row.get("kind") == "attempt":
                        attempt_rows.append(row)
                    elif row.get("kind") == "outcome":
                        outcome_rows.append(row)
                except (json.JSONDecodeError, ValueError):
                    # Skip malformed lines
                    continue

    if not attempt_rows:
        # Return empty dataframe with expected columns
        return pd.DataFrame()

    # Convert to DataFrames
    df_attempts = pd.DataFrame(attempt_rows)
    df_outcomes = pd.DataFrame(outcome_rows) if outcome_rows else pd.DataFrame()

    # Check for duplicate attempt_uids in attempts
    if not df_attempts.empty:
        duplicates = df_attempts[df_attempts.duplicated(subset=["attempt_uid"], keep=False)]
        if not duplicates.empty:
            dup_uid = duplicates["attempt_uid"].iloc[0]
            raise ValueError(f"Duplicate attempt_uid in attempt rows: {dup_uid}")

    # Deduplicate outcomes: keep the one with the highest event_seq per attempt_uid
    if not df_outcomes.empty:
        df_outcomes = df_outcomes.sort_values("event_seq").drop_duplicates(subset=["attempt_uid"], keep="last")

    # Left join outcomes onto attempts
    merged = df_attempts.copy()
    if not df_outcomes.empty:
        merged = df_attempts.merge(df_outcomes[["attempt_uid", "outcome"]], on="attempt_uid", how="left")
    else:
        merged["outcome"] = None

    # Report orphaned outcomes (outcomes with no matching attempt)
    if not df_outcomes.empty:
        outcome_uids = set(df_outcomes["attempt_uid"])
        attempt_uids = set(df_attempts["attempt_uid"])
        orphaned = outcome_uids - attempt_uids
        if orphaned:
            print(f"WARNING: {len(orphaned)} outcome row(s) with no matching attempt excluded")

    # Filter to only keep rows that have an outcome (complete pairs)
    # Actually, per spec §10 R5, we should keep consumption samples even if no outcome
    # But per the task, we exclude orphaned outcomes. So we keep all attempts
    # (whether or not they have an outcome), but we filter outcomes to only those
    # that have a matching attempt.

    return merged


def bucket_of(declared_files: Any, known: Any) -> str:
    """Return the task-size bucket label, or "unknown" when the count is absent."""
    if not known or declared_files is None:
        return "unknown"

    declared_files = int(declared_files)

    for label, min_val, max_val in SIZE_BUCKETS:
        if min_val <= declared_files <= max_val:
            return label

    # Fallback if somehow out of range
    return "unknown"


def recommend(df: pd.DataFrame, *, max_tokens: int) -> pd.DataFrame:
    """Per (seat_label, bucket): sample counts, percentiles, error, ceiling.

    Reports TWO sample counts on purpose: `n_consumption` (all merged rows) and
    `n_calibration` (rows with `calibration_eligible`). An attempt whose
    provider skipped a round's usage is a valid consumption sample and an
    invalid calibration sample (spec §10 R5), and merging the two would bias the
    margin the ceiling is built from.

    Estimation error uses `ledger_settled_estimate_input_tokens -
    ledger_input_tokens` — both sides describe the SAME settled requests.
    Released estimates are excluded by construction upstream.

    A segment with fewer than MIN_SAMPLES merged attempts gets percentiles
    marked unreliable and NO suggested ceiling. Each ceiling is printed with the
    absolute final_answer_reserve that should accompany it.
    """
    if df.empty:
        return pd.DataFrame()

    # Add bucket column
    df["bucket"] = df.apply(lambda row: bucket_of(row.get("declared_files"), row.get("declared_files_known")), axis=1)

    # Compute total tokens
    def total_tokens(row):
        # Use ledger if available, else provider. `row.get(...)` on a pandas
        # Series returns `NaN` (a float), not `None`, for a missing value in
        # a mixed-null column — `NaN is not None` is True in Python, so an
        # `is not None` check here would treat a missing ledger field as
        # present and return `NaN + NaN = NaN`, which then gets silently
        # dropped by `.notna()` below instead of falling through to the
        # provider-total fallback. This is exactly how the `gemini` seat
        # (provider-totals-only by design, AC-15) would vanish from every
        # percentile instead of contributing its baseline data.
        ledger_in = row.get("ledger_input_tokens")
        ledger_out = row.get("ledger_output_tokens")

        if pd.notna(ledger_in) and pd.notna(ledger_out):
            return ledger_in + ledger_out

        provider_in = row.get("provider_input_tokens")
        provider_out = row.get("provider_output_tokens")

        if pd.notna(provider_in) and pd.notna(provider_out):
            return provider_in + provider_out

        return None

    df["total_tokens"] = df.apply(total_tokens, axis=1)

    # Compute estimation error for calibration-eligible rows
    def estimation_error(row):
        if not row.get("calibration_eligible"):
            return None

        settled = row.get("ledger_settled_estimate_input_tokens")
        actual = row.get("ledger_input_tokens")

        if pd.notna(settled) and pd.notna(actual) and actual != 0:
            return (settled - actual) / actual

        return None

    df["estimation_error"] = df.apply(estimation_error, axis=1)

    # Group by (seat_label, bucket)
    grouped = df.groupby(["seat_label", "bucket"])

    results = []

    for (seat, bucket), group in grouped:
        # AC-13 gates the recommendation on MERGED attempts specifically
        # ("withholds a recommendation below 12 merged attempts") — a
        # failed/fidelity_violation/merge_conflict row still burned tokens
        # (it stays a valid consumption sample above, per calibration
        # eligibility separately), but it must not count toward the
        # merged-sample threshold that makes a ceiling trustworthy.
        group = group[group["outcome"] == "merged"]
        if group.empty:
            continue

        # Sample counts
        n_consumption = len(group)
        n_calibration = len(group[group["calibration_eligible"]])

        # Filter out rows with None total_tokens for percentiles
        tokens_valid = group[group["total_tokens"].notna()]["total_tokens"].dropna()

        if len(tokens_valid) == 0:
            continue

        # Percentiles
        p50 = tokens_valid.quantile(0.50)
        p95 = tokens_valid.quantile(0.95)
        p99 = tokens_valid.quantile(0.99)

        # Estimation error (median over calibration-eligible)
        errors = group[group["calibration_eligible"]]["estimation_error"].dropna()
        median_error = errors.median() if len(errors) > 0 else 0.0

        # Ceiling recommendation
        if bucket == "unknown":
            # Unknown buckets never get a ceiling recommendation
            ceiling_str = "N/A"
            reserve_str = "N/A"
            reliable = "unknown bucket (no recommendation)"
        elif n_consumption >= MIN_SAMPLES:
            ceiling = p95 * (1 + median_error)
            reserve = RESERVE_MULTIPLIER * max_tokens
            ceiling_str = f"{ceiling:.0f}"
            reserve_str = f"{reserve:.0f}"
            reliable = "OK"
        else:
            ceiling = None
            reserve = None
            ceiling_str = "N/A"
            reserve_str = "N/A"
            reliable = f"unreliable ({n_consumption} samples)"

        results.append(
            {
                "seat": seat,
                "bucket": bucket,
                "n_consumption": n_consumption,
                "n_calibration": n_calibration,
                "p50": f"{p50:.0f}",
                "p95": f"{p95:.0f}",
                "p99": f"{p99:.0f}",
                "median_error": f"{median_error * 100:+.1f}%",
                "ceiling": ceiling_str,
                "final_answer_reserve": reserve_str,
                "status": reliable,
            }
        )

    return pd.DataFrame(results)


def main() -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True, help="telemetry root directory")
    parser.add_argument(
        "--max-tokens", type=int, default=8192, help="profile max_tokens, for the reserve recommendation"
    )
    args = parser.parse_args()

    frame = load_rows(args.root)
    result = recommend(frame, max_tokens=args.max_tokens)
    print(result.to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
