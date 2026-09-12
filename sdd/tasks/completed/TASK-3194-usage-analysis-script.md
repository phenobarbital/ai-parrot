# TASK-3194: Analysis script — percentiles, estimation error and the ceiling recommendation

**Feature**: FEAT-554 — Empirical Token-Budget Sizing for sdd-coder Bedrock Seats
**Spec**: `sdd/specs/sdd-coder-bedrock-token-telemetry.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3191
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 5. The dataset is only worth collecting if something turns it
into the number this feature exists to produce: a `token_budget` per seat and
task size, with an honest refusal when the sample is too thin.

Three rules from the reviews shape the join, and all three are easy to get
wrong: rows key on `attempt_uid` (not the recurring attempt number), an attempt
may carry several outcome rows (conflict then re-merge), and an attempt can be a
valid *consumption* sample while being an invalid *calibration* sample.

---

## Scope

- Create `scripts/analyze_sdd_coder_usage.py`: load, join, bucket, report,
  recommend.
- Write unit tests over synthetic JSONL fixtures.

**NOT in scope**: writing rows (TASK-3191/3193), an HTML report, plotting,
cross-machine aggregation — all out of scope per spec §1.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `scripts/analyze_sdd_coder_usage.py` | CREATE | Analysis + recommendation |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_usage_analysis.py` | CREATE | Unit tests over synthetic rows |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.flows.dev_loop.sdd_coder.telemetry import AttemptUsageRow, OutcomeRow  # TASK-3191
import pandas as pd   # already a project dependency
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/telemetry.py (TASK-3191)
class AttemptUsageRow(BaseModel):
    kind: Literal["attempt"]; attempt_uid: str; job_id: str; feature_id: str
    task_id: str; attempt: int; seat_label: str; backend: str
    configured_model: str; resolved_model: str; duration_s: float; turns: int
    terminal: str; error_class: str
    declared_files: Optional[int]; declared_files_known: bool
    provider_input_tokens / provider_output_tokens: Optional[int]
    ledger_input_tokens / ledger_output_tokens: Optional[int]
    ledger_settled_estimate_input_tokens: Optional[int]
    ledger_released_estimate_tokens / ledger_uncertain_tokens / ledger_overrun_tokens: Optional[int]
    ledger_counting_methods: List[str]; ledger_accounting_complete: Optional[bool]
    enforcement: str; turns_with_unknown_usage: int; calibration_eligible: bool
    turn_series: List[Tuple[int, Optional[int], Optional[int]]]

class OutcomeRow(BaseModel):
    kind: Literal["outcome"]; attempt_uid: str; event_seq: int; outcome: str
    conflict_file_count: int; unexpected_file_count: int
```

### Does NOT Exist
- ~~A single `outcome` per `attempt_uid`~~ — conflict-then-re-merge legitimately
  produces several (`engine.py:407`). Take the highest `event_seq`; do not assume one.
- ~~`(feature_id, task_id, attempt)` as a key~~ — it collides across jobs (spec §10 R3).
- ~~A `total_tokens` column~~ — sum `ledger_input_tokens + ledger_output_tokens`, or the
  provider pair when no ledger was bound. Decide once, in one helper.
- ~~`scripts/telemetry/`~~ — `scripts/` holds flat modules plus `scripts/sdd/`,
  `scripts/bench/`, `scripts/matrix/`.
- ~~A `cost` or price column~~ — pricing is explicitly out of scope.

---

## Implementation Notes

### Key Constraints
- **Two sample counts, always reported separately.** Consumption percentiles may
  use every merged row; estimation error uses only `calibration_eligible` rows.
  Collapsing them would silently drop attempts whose provider skipped a round's
  usage, biasing the very error the margin is derived from.
- `MIN_SAMPLES = 12` gates the *recommendation*, not the percentiles: below it
  print the numbers marked unreliable and withhold the ceiling.
- An `outcome` row with no matching `attempt` row is an incomplete pair:
  report the count and EXCLUDE it. Never treat missing tokens as zero.
- A duplicate `attempt_uid` among attempt rows is a bug, not a retry: report it
  loudly rather than averaging.
- Print the recommended absolute `final_answer_reserve` (`2 × max_tokens`)
  beside each ceiling so the operator configures both together (spec §7).

### References in Codebase
- `scripts/release.py` — the repo's plain-module script style (argparse `main()`,
  no framework).

---

## Implementation Blueprint

### Steps (in order)
1. Write `load_rows` first and test the three join hazards — *why*: every later number is wrong if the join is wrong, and all three hazards are silent.
2. Add bucketing and percentiles — *why*: a single global ceiling would mix one-file tasks with six-file ones.
3. Add `recommend` last, with the sample gate — *why*: it is the only output an operator acts on.

### `scripts/analyze_sdd_coder_usage.py` (CREATE)
```python
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
from typing import Any, Dict, List, Tuple

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
    # FILL IN: read every line, split by `kind`, dedupe outcomes by
    # (attempt_uid, max event_seq), left-join onto attempts, count and report
    # orphans, raise on duplicate attempt uids. Bounded by AC-12.
    raise NotImplementedError


def bucket_of(declared_files: Any, known: Any) -> str:
    """Return the task-size bucket label, or "unknown" when the count is absent."""
    # FILL IN: map declared_files onto SIZE_BUCKETS; anything with
    # declared_files_known == False is "unknown" and is excluded from
    # recommendations. Bounded by AC-8.
    raise NotImplementedError


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
    # FILL IN: group, compute p50/p95/p99 of total tokens over merged rows,
    # median estimation error over calibration-eligible rows, then
    # ceiling = p95 * (1 + median_relative_error), withheld below MIN_SAMPLES.
    # Bounded by AC-13 and AC-21.
    raise NotImplementedError


def main() -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True, help="telemetry root directory")
    parser.add_argument("--max-tokens", type=int, default=8192, help="profile max_tokens, for the reserve recommendation")
    args = parser.parse_args()
    frame = load_rows(args.root)
    print(recommend(frame, max_tokens=args.max_tokens).to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```
**Why this shape**: `load_rows` returns a frame rather than printing, so the join rules are unit-testable without the CLI. `recommend` takes `max_tokens` as a parameter instead of importing the profile — the script must run against a dataset from a machine whose profile it cannot see.

### FILL IN checklist
- [ ] `load_rows` — the join, orphan reporting and duplicate-uid guard; bounded by AC-12
- [ ] `bucket_of` — bucket mapping plus the `unknown` case; bounded by AC-8
- [ ] `recommend` — the two sample counts, percentiles, error and the gated ceiling; bounded by AC-13, AC-21
- [ ] `test_usage_analysis.py` — the five test bodies below

---

## Acceptance Criteria

- [ ] A segment with 11 merged attempts prints percentiles marked unreliable and NO ceiling; 12 produces one.
- [ ] An `outcome` row with no matching `attempt` row is reported as an incomplete pair and excluded from every statistic.
- [ ] `merge_conflict` (seq 1) then `merged` (seq 2) for one `attempt_uid` resolves to `merged`, counted once.
- [ ] A duplicate `attempt_uid` among attempt rows raises with a message naming the uid.
- [ ] `n_consumption` and `n_calibration` are reported separately and can differ.
- [ ] Rows with `declared_files_known=False` land in the `unknown` bucket and get no recommendation.
- [ ] The output prints the absolute `final_answer_reserve` next to each ceiling.
- [ ] All tests pass: `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_usage_analysis.py -v`
- [ ] No linting errors: `ruff check scripts/analyze_sdd_coder_usage.py`

---

## Test Specification

```python
# packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_usage_analysis.py
import json

import pytest


def _write(tmp_path, rows):
    path = tmp_path / "FEAT-554.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    return tmp_path


class TestJoin:
    def test_latest_outcome_wins(self, tmp_path):
        # FILL IN: one attempt + two outcomes (seq 1 merge_conflict, seq 2
        # merged); assert one joined row with outcome == "merged"
        raise NotImplementedError

    def test_orphan_outcome_excluded(self, tmp_path):
        # FILL IN: an outcome whose attempt_uid has no attempt row — bounded by AC-12
        raise NotImplementedError

    def test_duplicate_attempt_uid_raises(self, tmp_path):
        # FILL IN: two attempt rows sharing a uid; assert the error names it
        raise NotImplementedError


class TestRecommendation:
    def test_thin_segment_withholds_ceiling(self, tmp_path):
        # FILL IN: 11 merged attempts in one segment — bounded by AC-13
        raise NotImplementedError

    def test_sample_counts_reported_separately(self, tmp_path):
        # FILL IN: merged rows where some have calibration_eligible False;
        # assert n_consumption > n_calibration — bounded by AC-21
        raise NotImplementedError
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** — §3 Module 5 and §10 R3/R4/R5.
2. **Check dependencies** — TASK-3191 must be in `sdd/tasks/completed/`; the row schema is fixed there.
3. **Verify the Codebase Contract** — import the row models and read their fields rather than retyping them.
4. **Update status** in `sdd/tasks/index/sdd-coder-bedrock-token-telemetry.json` → `"in-progress"`.
5. **Implement** from the blueprint; keep the two sample counts separate.
6. **Verify** all acceptance criteria.
7. **Move this file** to `sdd/tasks/completed/TASK-3194-usage-analysis-script.md`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

**Completed by**: sdd-coder (haiku, native seat) via parrot-sdd-coder orchestrator, merged by sdd-worker
**Date**: 2026-09-12
**Notes**: Implemented `scripts/analyze_sdd_coder_usage.py`: `load_rows()`
joins `attempt`/`outcome` JSONL lines on `attempt_uid`, taking the
highest-`event_seq` outcome as effective and reporting orphaned outcomes
and duplicate `attempt_uid`s (raises, naming the uid); `bucket_of()` maps
`declared_files` into the `1-2`/`3-4`/`5+`/`unknown` buckets;
`recommend()` groups by `(seat_label, bucket)`, reports `n_consumption`
and `n_calibration` separately, computes p50/p95/p99, gates the ceiling on
`MIN_SAMPLES=12`, derives the safety margin from calibration-eligible
rows' median estimation error, excludes `unknown` from any
recommendation, and prints `final_answer_reserve` next to each ceiling.
13 tests pass; `ruff check` clean.

**Deviations from spec**: none

**Post-merge adversarial review addendum**: a full-feature code review after
all 11 tasks landed found two defects in this script, both fixed with new
regression tests (each verified to fail against the pre-fix code):
1. `total_tokens()`/`estimation_error()` used `is not None` on values read
   from a pandas row; a missing value in a mixed-null numeric column is
   `NaN` (a float), and `NaN is not None` is `True` in Python — the
   `gemini` seat's absent `ledger_*` fields were silently treated as
   present, computed to `NaN`, and dropped from every percentile instead
   of falling through to the provider-total fallback (AC-15). Fixed with
   `pd.notna(...)`.
2. `recommend()`'s `MIN_SAMPLES` gate counted every row in a (seat,
   bucket) group regardless of `outcome`, contradicting both AC-13
   ("withholds a recommendation below 12 MERGED attempts") and the
   function's own docstring ("n_consumption: all merged rows"). Fixed to
   filter to `outcome == "merged"` before computing `n_consumption`/
   percentiles.
See FEAT-554's final commit for full detail.

Seat: haiku (native) · Backend: n/a · Model: haiku · Attempts: 1 · Duration: 324.4s · Tokens: n/a (subagent_tokens: 90241)
