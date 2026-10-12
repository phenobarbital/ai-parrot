# TASK-4242: Regression gate — BaselineStore backends and per-tag pass^k check_regression

**Feature**: FEAT-652 — Answer-Accuracy Metrics for the Evaluation Harness
**Spec**: `sdd/specs/eval-answer-accuracy-metrics.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 6. `PostgresEvalSink._SCHEMA_DDL` already creates `eval_baselines`
(`dataset_name`, `tag`, `run_id`, `pass_k`, `captured_at`) but nothing reads or writes it.
This task adds a `BaselineStore` contract with in-memory and Postgres backends and a pure
`check_regression()` that compares an `EvalReport` with the stored baselines **per tag,
independently** — the same rule `knowledge/retrieval/eval/metrics.py::check_regression`
applies to retrieval classes (an improvement elsewhere never offsets a regression). Recording
is explicit; the gate never writes.

---

## Scope

- Create `eval/regression.py`: `BaselineStore` (ABC), `InMemoryBaselineStore`, `PostgresBaselineStore`,
  `RegressionVerdict`, `check_regression`.
- Unit tests; Postgres test gated on `EVAL_DB_DSN`.

**NOT in scope**: CLI / CI wiring; `EvalRunner` integration; exports (TASK-4243); reusing the retrieval
harness function (typed on `QueryClass`).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/eval/regression.py` | CREATE | store ABC, backends, verdict, gate |
| `packages/ai-parrot/tests/eval/test_regression.py` | CREATE | per-tag rule, no-baseline, record, Postgres (gated) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.eval.runner import EvalReport, EvalRunConfig        # verified: eval/runner.py:69,43
from parrot.eval.sink import PostgresEvalSink, _SCHEMA_DDL      # verified: eval/sink.py:100,60
from pydantic import BaseModel, Field                           # pydantic v2
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/eval/runner.py
class EvalRunConfig(BaseModel):   # line 43: k=1, max_concurrency=8, sandbox_pool_size=4, fail_fast=False, seed=None
class EvalReport(BaseModel):      # line 69
    run_id: str = Field(default_factory=lambda: str(uuid.uuid4()))   # line 93
    dataset_name: str                                                # line 94
    config: EvalRunConfig                                            # line 95
    pass_k: float | None = None                                      # line 96
    per_tag: dict[str, float] = Field(default_factory=dict)          # line 99  (pass^k per tag)

# packages/ai-parrot/src/parrot/eval/sink.py
CREATE TABLE IF NOT EXISTS eval_baselines (id BIGSERIAL PRIMARY KEY, dataset_name TEXT NOT NULL, tag TEXT NOT NULL DEFAULT '',
    run_id TEXT NOT NULL, pass_k FLOAT, captured_at TIMESTAMPTZ NOT NULL DEFAULT NOW());          # lines 80-87
class PostgresEvalSink: @staticmethod _resolve_dsn() -> str | None   # line 122; connection pattern :177-185 (lazy asyncpg, connect, execute(_SCHEMA_DDL), close)

# Rule to mirror (do NOT import — typed on QueryClass): packages/ai-parrot/src/parrot/knowledge/retrieval/eval/metrics.py:199-225
#   regressed iff baseline_value - candidate_value > tolerance, per key, independently.
```

### Does NOT Exist
- ~~`parrot.eval.regression`~~ — created here.
- ~~`EvalReport.baseline`~~, ~~`EvalRunner.check_regression`~~ — the gate is standalone.
- ~~`eval_baselines.tolerance`~~ column — tolerance is a call argument, never stored.
- ~~`BaselineStore.latest()`~~ — the contract is `get_baseline(dataset_name, tag="")` + `record(report)`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/eval/regression.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/eval/test_regression.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/eval/runner.py#EvalReport",
    "sym:packages/ai-parrot/src/parrot/eval/runner.py#EvalRunConfig",
    "sym:packages/ai-parrot/src/parrot/eval/sink.py#PostgresEvalSink",
    "sym:packages/ai-parrot/src/parrot/eval/sink.py#_SCHEMA_DDL"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Tag `""` is the overall `pass_k`; `record()` writes `""` plus every `per_tag` key; a report with
  `pass_k is None` records nothing for `""`.
- `get_baseline` returns the **latest** row (`ORDER BY captured_at DESC LIMIT 1`); in-memory keeps the last written value.
- `check_regression` checks `""` and every tag present in the report; tags with no baseline never regress;
  `passed = not regressed_tags`. It never calls `record()`.
- Postgres backend mirrors the sink: lazy `import asyncpg`, one connection per call, `await conn.execute(_SCHEMA_DDL)`, `$N` params, close in `finally`; `RuntimeError` on use without DSN.

### References in Codebase
- `packages/ai-parrot/src/parrot/knowledge/retrieval/eval/metrics.py:199-225` — the per-class rule in prose and code.
- `packages/ai-parrot/src/parrot/eval/sink.py:142-215` — asyncpg pattern.

---

## Implementation Blueprint

### Steps (in order)
1. Write `RegressionVerdict` and `BaselineStore` — *why*: `check_regression`'s types are fixed by the spec skeleton.
2. Write `InMemoryBaselineStore` — *why*: TASK-4243's e2e test uses it.
3. Write `check_regression` — *why*: pure function, testable without any backend.
4. Write `PostgresBaselineStore`, then the tests.

### `packages/ai-parrot/src/parrot/eval/regression.py` (CREATE)
```python
"""pass^k regression gate over eval_baselines (FEAT-652, Module 6)."""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod

from pydantic import BaseModel, Field

from parrot.eval.runner import EvalReport
from parrot.eval.sink import PostgresEvalSink, _SCHEMA_DDL

logger = logging.getLogger(__name__)
OVERALL_TAG = ""


class RegressionVerdict(BaseModel):
    """Outcome of comparing one report against stored baselines, per tag."""

    dataset_name: str
    tolerance: float
    overall_baseline: float | None = None
    overall_candidate: float | None = None
    regressed_tags: list[str] = Field(default_factory=list)
    passed: bool


class BaselineStore(ABC):
    """Latest pass^k per (dataset, tag); ``""`` is the overall figure."""

    @abstractmethod
    async def get_baseline(self, dataset_name: str, tag: str = OVERALL_TAG) -> float | None: ...

    @abstractmethod
    async def record(self, report: EvalReport) -> None:
        """Record ``report.pass_k`` under ``""`` and every ``per_tag`` entry under its tag."""


class InMemoryBaselineStore(BaselineStore):
    def __init__(self) -> None:
        self._rows: dict[tuple[str, str], float] = {}

    async def get_baseline(self, dataset_name: str, tag: str = OVERALL_TAG) -> float | None:
        return self._rows.get((dataset_name, tag))

    async def record(self, report: EvalReport) -> None:
        if report.pass_k is not None:
            self._rows[(report.dataset_name, OVERALL_TAG)] = report.pass_k
        for tag, value in report.per_tag.items():
            self._rows[(report.dataset_name, tag)] = value


async def check_regression(report: EvalReport, store: BaselineStore, *, tolerance: float = 0.05) -> RegressionVerdict:
    """A tag regresses iff ``baseline - candidate > tolerance``; independent per tag; never records."""
    candidates: dict[str, float | None] = {OVERALL_TAG: report.pass_k, **report.per_tag}
    regressed: list[str] = []
    # FILL IN: for each (tag, candidate) with candidate not None: baseline = await store.get_baseline(report.dataset_name, tag);
    #          skip when baseline is None; append tag when baseline - candidate > tolerance — bounded by AC-1/AC-2
    overall_baseline = await store.get_baseline(report.dataset_name, OVERALL_TAG)
    return RegressionVerdict(dataset_name=report.dataset_name, tolerance=tolerance, overall_baseline=overall_baseline,
                             overall_candidate=report.pass_k, regressed_tags=regressed, passed=not regressed)
```
```python
class PostgresBaselineStore(BaselineStore):
    """asyncpg over ``eval_baselines`` (DDL from ``PostgresEvalSink._SCHEMA_DDL``); latest row by ``captured_at``."""

    def __init__(self, dsn: str | None = None) -> None:
        self._dsn = dsn or PostgresEvalSink._resolve_dsn()
        self.logger = logging.getLogger(__name__)

    def _require_dsn(self) -> str:
        if not self._dsn:
            raise RuntimeError("PostgresBaselineStore: no DSN configured. Set EVAL_DB_DSN or pass dsn=.")
        return self._dsn

    async def get_baseline(self, dataset_name: str, tag: str = OVERALL_TAG) -> float | None:
        import asyncpg  # lazy, optional dependency
        conn = await asyncpg.connect(self._require_dsn())
        try:
            await conn.execute(_SCHEMA_DDL)
            row = await conn.fetchrow(
                "SELECT pass_k FROM eval_baselines WHERE dataset_name = $1 AND tag = $2 ORDER BY captured_at DESC LIMIT 1",
                dataset_name, tag)
        finally:
            await conn.close()
        return None if row is None or row["pass_k"] is None else float(row["pass_k"])

    async def record(self, report: EvalReport) -> None:
        # FILL IN: connect, ensure schema, INSERT one row per (OVERALL_TAG if pass_k is not None) + per_tag with report.run_id, close in finally — bounded by AC-3
        raise NotImplementedError
```
**Why this shape**: the pure gate and the in-memory store make the rule fully testable offline;
the Postgres backend adds persistence with the sink's own discipline and no new columns.

### `packages/ai-parrot/tests/eval/test_regression.py` (CREATE)
```python
"""Unit tests for the regression gate (TASK-4242)."""
import os
import pytest
from parrot.eval.regression import InMemoryBaselineStore, PostgresBaselineStore, RegressionVerdict, check_regression
from parrot.eval.runner import EvalReport, EvalRunConfig


def _report(pass_k, per_tag, name="qa"):
    return EvalReport(dataset_name=name, config=EvalRunConfig(), pass_k=pass_k, per_tag=per_tag)


async def test_per_tag_independent():
    store = InMemoryBaselineStore()
    await store.record(_report(0.9, {"A": 0.8, "B": 0.9}))
    verdict = await check_regression(_report(0.9, {"A": 0.95, "B": 0.7}), store, tolerance=0.05)
    # FILL IN: assert verdict.regressed_tags == ["B"] and not verdict.passed — bounded by AC-1

# FILL IN: test_no_baseline_passes (empty store → passed True, overall_baseline None); test_overall_regression_flags_empty_tag;
#          test_record_overall_and_tags; test_postgres_requires_dsn; skipif-gated test_postgres_roundtrip — bounded by AC-2..AC-4
```

### FILL IN checklist
- [ ] `regression.py::check_regression` loop; AC-1/AC-2
- [ ] `regression.py::PostgresBaselineStore.record`; AC-3
- [ ] `test_regression.py` — six tests; AC-1..AC-4

---

## Acceptance Criteria

- [ ] AC-1: a tag regresses iff `baseline - candidate > tolerance`, evaluated independently per tag (an improvement in A never hides a regression in B).
- [ ] AC-2: with no stored baseline the verdict passes and `overall_baseline is None`; `check_regression` never writes to the store.
- [ ] AC-3: `record()` stores the overall figure under `""` and each `per_tag` entry; Postgres backend returns the latest row (test gated on `EVAL_DB_DSN`).
- [ ] AC-4: `PostgresBaselineStore(dsn=None)` without `EVAL_DB_DSN` raises `RuntimeError` on use, not at construction.
- [ ] `ruff check packages/ai-parrot/src/parrot/eval/regression.py` clean.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/eval/test_regression.py -q`
- `pytest packages/ai-parrot/tests/eval/test_runner.py -q`

---

## Test Specification

See the blueprint block above.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug eval-answer-accuracy-metrics --feature-id FEAT-652`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — none
4. **Verify the Codebase Contract** — `grep`/`read` every reference before writing code
5. **Update status** in `sdd/tasks/index/eval-answer-accuracy-metrics.json` → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** from the blueprint, completing every `# FILL IN:`; never change a signature or path it fixes
7. **Verify** — run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`
8. **Commit the code** — stage only the two files listed
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4242 eval-answer-accuracy-metrics verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

- Implemented by seat sonnet (native), 1 attempt, 89s. Merged and lint-committed by the engine.
- Validation: eval suite `packages/ai-parrot/tests/eval` 144 passed, 3 skipped (merge-tier validation completed green, HEAD d5c1b893e).
- Postgres-backed paths are skipped without `EVAL_DB_DSN`; not exercised against a real DB.
- Closed manually via close_task.sh: finalize_task fidelity gate rejected it because a sibling task's review-fix commit sat in the same range.
- Deviations from spec: none.
