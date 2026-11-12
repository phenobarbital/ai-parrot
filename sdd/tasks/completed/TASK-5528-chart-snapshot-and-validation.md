# TASK-5528: Chart snapshot builders and model validation

**Feature**: FEAT-713 — Accounting Metrics Layer
**Spec**: `sdd/specs/accounting-metrics-layer.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-5525, TASK-5527
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 4 (snapshot + validation half) and AC4. Completeness of the chart of accounts is the core
invariant of this feature: per effective-dated interval, every account in the snapshot must belong to exactly one
valid set or be explicitly excluded. This task writes the snapshot builders and `validation.py`, which returns
**all** problems. TASK-5529 writes the loader that resolves selectors and calls `validate`.

Design-bearing module (spec delegation table: "no") — the interval partition and completeness semantics need care.

---

## Scope

- `snapshot.py`: `snapshot_from_rows`, `snapshot_from_arrow`, `snapshot_from_manifest` (YAML or CSV).
- `validation.py`: `partition_intervals`, `validate`, `metric_order`, with every check of spec §3 M4:
  per interval — unassigned accounts, overlaps outside mutual `allow_overlap`, empty sets, `interval_gap`;
  globally — dangling refs, cycles, selectors matching nothing, nature missing/ambiguous (and conflicts between
  `nature.accounts` and snapshot natures), `float_amount`, `numeric_type` (precision/scale beyond DECIMAL(38,6)),
  `column_missing`.
- `tests/accounting/test_snapshot_validation.py`: `test_partition_intervals`, `test_completeness_per_interval`,
  `test_overlap_and_allow_overlap`, `test_cycle_and_dangling`, `test_float_amount_and_numeric_type`,
  `test_snapshot_builders`.

**NOT in scope**: reading YAML models, selector resolution into `ResolvedSet`, hashing (TASK-5529);
`test_all_problems_reported` end to end (TASK-5529 via `load_model`).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-semantic/src/parrot/semantic/accounting/snapshot.py` | CREATE | snapshot builders |
| `packages/ai-parrot-semantic/src/parrot/semantic/accounting/validation.py` | CREATE | partition + all checks |
| `packages/ai-parrot-semantic/tests/accounting/test_snapshot_validation.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.semantic.accounting.errors import Problem                        # TASK-5524
from parrot.semantic.accounting.grammar import parse_expr, parse_assertion, references   # TASK-5527
from parrot.semantic.accounting.models import (                              # TASK-5525
    AccountSet, AccountingModelSpec, ChartAccount, ChartSnapshot, ResolvedSet, Nature,
)
import yaml                                                                   # satellite dependency pyyaml>=6
import csv
```

### Existing Signatures to Use
```python
# errors.py (TASK-5524)
class Problem(BaseModel, frozen=True):
    code: ProblemCode   # unassigned_account | empty_set | overlap | dangling_ref | cycle | nature_missing |
                        # nature_ambiguous | float_amount | numeric_type | column_missing | interval_gap | selector_no_match
    message: str; interval: tuple[date | None, date | None] | None = None; accounts: tuple[str, ...] = ()
```
- Fixtures (`tests/accounting/conftest.py`, TASK-5525): `chart_snapshot` (40 accounts), `troc_pnl_yaml`.

### Does NOT Exist
- ~~`import pyarrow` at module top in `snapshot.py`~~ — import it inside `snapshot_from_arrow` only.
- ~~database access in `snapshot.py`~~ — it never opens a connection (spec §3 M4); TASK-5533's
  `DatabaseRuntime.fetch_chart_rows` supplies rows.
- ~~`ModelValidationError` raised here~~ — `validate` *returns* `list[Problem]`; the loader raises.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-semantic/src/parrot/semantic/accounting/snapshot.py", "action": "CREATE"},
    {"path": "packages/ai-parrot-semantic/src/parrot/semantic/accounting/validation.py", "action": "CREATE"},
    {"path": "packages/ai-parrot-semantic/tests/accounting/test_snapshot_validation.py", "action": "CREATE"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Key Constraints
- Intervals are half-open `[start, end)`; `None` start = −∞, `None` end = +∞. `partition_intervals` collects every
  `valid_from` and `valid_to` across sets, sorts the distinct dates and returns consecutive intervals covering
  (−∞, +∞) — so `[(None, d1), (d1, d2), …, (dn, None)]`, or `((None, None),)` when no set is dated.
- A set is *active* in an interval when its own `[valid_from, valid_to)` contains the whole interval.
- `validate` never stops early; problems are returned in a deterministic order (sort by code, interval, accounts).
- `columns` maps journal column → declared type string; `None` skips `column_missing`, `float_amount`
  and `numeric_type`. Float types: names containing `float`, `double`, `real`. Decimal types: parse
  `DECIMAL(p,s)` / `NUMERIC(p,s)`; reject `s > 6` or `p - s > 32` as `numeric_type` (spec numeric contract).
- `metric_order` returns a topological order; on a cycle it still returns (callers read the `cycle` problem from
  `validate`); keep the order deterministic (sorted names at each step).
- Standard library + pyyaml (+ pyarrow inside the arrow builder) only.

---

## Implementation Blueprint

### Steps (in order)
1. Write `snapshot.py` — *why*: validation tests need snapshots.
2. Write `partition_intervals` and its test first — *why*: every per-interval check depends on it.
3. Write `validate` check by check, each with its test — *why*: AC4 requires every problem be found.
4. Write `metric_order`.

### `packages/ai-parrot-semantic/src/parrot/semantic/accounting/snapshot.py` (CREATE)
```python
"""Chart-of-accounts snapshot builders (FEAT-713 M4). Never opens a connection."""

from __future__ import annotations

import csv
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Any, Mapping, Sequence

import yaml

from .models import ChartAccount, ChartSnapshot

if TYPE_CHECKING:
    import pyarrow as pa


def snapshot_from_rows(
    rows: Sequence[Mapping[str, Any]], *, account_key: str, nature_column: str | None,
    parent_column: str | None = None, tags_column: str | None = None, source: str, taken_at: date,
) -> ChartSnapshot:
    """Build the sorted, hashed snapshot from account-master rows (dict rows from the executor)."""
    # FILL IN: map each row to ChartAccount (nature lower-cased; None when nature_column is None or empty;
    #   tags from a list or a comma-separated string); sort by account_id; duplicate ids ⇒ ValueError.
    raise NotImplementedError


def snapshot_from_arrow(
    table: "pa.Table", *, account_key: str, nature_column: str | None,
    parent_column: str | None = None, tags_column: str | None = None, source: str, taken_at: date,
) -> ChartSnapshot:
    """Same as snapshot_from_rows over ``table.to_pylist()``."""
    return snapshot_from_rows(
        table.to_pylist(), account_key=account_key, nature_column=nature_column,
        parent_column=parent_column, tags_column=tags_column, source=source, taken_at=taken_at,
    )


def snapshot_from_manifest(path: Path) -> ChartSnapshot:
    """YAML (``taken_at`` + ``accounts`` list) or CSV (columns account_id, nature, parent_id, tags) manifest."""
    # FILL IN: dispatch on suffix (.yaml/.yml via yaml.safe_load, .csv via csv.DictReader); CSV taken_at =
    #   file mtime date; source=f"manifest:{path}".
    raise NotImplementedError
```

### `packages/ai-parrot-semantic/src/parrot/semantic/accounting/validation.py` (CREATE)
```python
"""Load-time model validation (FEAT-713 M4): returns EVERY problem."""

from __future__ import annotations

from datetime import date
from typing import Mapping

from .errors import GrammarError, Problem
from .grammar import parse_assertion, parse_expr, references
from .models import AccountingModelSpec, AccountSet, ChartSnapshot, ResolvedSet

Interval = tuple[date | None, date | None]


def partition_intervals(sets: Mapping[str, AccountSet]) -> tuple[Interval, ...]:
    """Half-open intervals between every valid_from / valid_to boundary, covering (-inf, +inf)."""
    # FILL IN: see Key Constraints.
    raise NotImplementedError


def validate(
    spec: AccountingModelSpec, resolved: Mapping[str, ResolvedSet], snapshot: ChartSnapshot,
    columns: Mapping[str, str] | None,
) -> list[Problem]:
    """Every invariant of spec §3 M4; never stops at the first problem."""
    problems: list[Problem] = []
    # FILL IN: per-interval checks (unassigned_account, overlap unless BOTH sets list each other in allow_overlap,
    #   empty_set, interval_gap for an account covered only in later intervals);
    #   formula checks (GrammarError ⇒ dangling_ref with the message; unknown set ⇒ dangling_ref;
    #   unknown metric ⇒ dangling_ref; cycles ⇒ cycle);
    #   selector_no_match for a set whose select matched nothing (compare resolved vs. spec);
    #   nature_missing / nature_ambiguous (natural_balance with a nature map, or map conflicting with snapshot);
    #   column_missing / float_amount / numeric_type when columns is not None.
    return sorted(problems, key=lambda p: (p.code, str(p.interval), p.accounts))


def metric_order(spec: AccountingModelSpec) -> tuple[str, ...]:
    """Deterministic topological order of metrics; members of a cycle are appended last in name order."""
    # FILL IN: Kahn's algorithm over metric→metric references from parse_expr; ignore unparsable expressions.
    raise NotImplementedError
```

### `packages/ai-parrot-semantic/tests/accounting/test_snapshot_validation.py` (CREATE)
```python
"""FEAT-713 M4 — snapshots and validation."""

from __future__ import annotations

from datetime import date


def test_partition_intervals() -> None:
    # FILL IN: no dates ⇒ ((None, None),); one valid_from ⇒ ((None, d), (d, None)); nested dates sorted/deduped.


def test_completeness_per_interval(chart_snapshot) -> None:
    # FILL IN: account covered only after valid_from ⇒ interval_gap for the earlier interval.


def test_overlap_and_allow_overlap(chart_snapshot) -> None:
    # FILL IN: shared account ⇒ overlap; mutual allow_overlap ⇒ no problem; one-sided ⇒ still overlap.


def test_cycle_and_dangling(chart_snapshot) -> None:
    # FILL IN: a = b + 1, b = a ⇒ cycle; sum(nope) ⇒ dangling_ref.


def test_float_amount_and_numeric_type(chart_snapshot) -> None:
    # FILL IN: DOUBLE amount ⇒ float_amount unless allow_float; DECIMAL(38,8) and DECIMAL(40,2) ⇒ numeric_type.


def test_snapshot_builders(tmp_path) -> None:
    # FILL IN: rows, arrow and manifest (yaml + csv) produce equal snapshot_hash for the same accounts.
```

### FILL IN checklist
- [ ] `snapshot_from_rows`, `snapshot_from_manifest`.
- [ ] `partition_intervals`, every `validate` check, `metric_order` — AC4.
- [ ] Six tests.

---

## Acceptance Criteria

- [ ] `validate` reports every problem listed in spec §3 M4, per interval where the spec says so (AC4).
- [ ] Snapshot builders are deterministic: same accounts ⇒ same `snapshot_hash`.
- [ ] Neither module opens a connection or imports anything outside the accounting package, stdlib, pyyaml
  (and pyarrow inside a function).
- [ ] `ruff check` passes on the three files.

## Validation Commands

- `pytest packages/ai-parrot-semantic/tests/accounting/test_snapshot_validation.py -q`

---

## Test Specification

See blueprint.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`parrot sdd worktree ensure --slug accounting-metrics-layer --feature-id FEAT-713`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in `sdd/tasks/index/accounting-metrics-layer.json`
4. **Verify the Codebase Contract** before writing any code; update it first if anything moved
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** from the Implementation Blueprint; complete every `# FILL IN:`; never change a fixed signature or path
7. **Verify** — run the Validation Commands with absolute `PYTHONPATH` for both `packages/ai-parrot-semantic/src` and `packages/ai-parrot/src`
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `parrot sdd task close TASK-5528 accounting-metrics-layer verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

**Completed by**: sdd-worker / native opus coder (attempt 2f89f94e6bb54d9592e89b6e69f64b2c), commit cae9565319
**Date**: 2026-11-12
**Notes**: snapshot.py (3 builders) and validation.py (partition_intervals, validate, metric_order); 7 tests green. Open-spec decisions the TASK-5529 loader author should know: (1) accounts covered in some intervals but not others -> `interval_gap`; only never-covered accounts -> `unassigned_account`; (2) `selector_no_match` when resolved accounts add nothing beyond the explicit list; (3) cycle problems list the cycle's metric names in Problem.accounts; (4) under natural_balance an explicit nature.accounts map gives `nature_ambiguous`; (5) unparameterised DECIMAL/NUMERIC and integer amount types accepted, non-numeric -> `numeric_type`, column names matched case-insensitively; (6) snapshot tags sorted/deduped; (7) YAML manifest without taken_at uses file mtime. Extra test test_nature_checks added.

**Deviations from spec**: none
