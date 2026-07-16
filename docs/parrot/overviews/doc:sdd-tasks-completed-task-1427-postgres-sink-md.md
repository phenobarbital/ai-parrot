---
type: Wiki Overview
title: 'TASK-1427: `PostgresEvalSink` + schema DDL (`parrot/eval/sink.py`)'
id: doc:sdd-tasks-completed-task-1427-postgres-sink-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Persists eval runs/results to Postgres JSONB using the existing async (asyncpg)
  pattern. Implements
relates_to:
- concept: mod:parrot.eval
  rel: mentions
- concept: mod:parrot.eval.runner
  rel: mentions
---

# TASK-1427: `PostgresEvalSink` + schema DDL (`parrot/eval/sink.py`)

**Feature**: FEAT-217 — Generic Agent Evaluation Harness
**Spec**: `sdd/specs/generic-evaluation-harness.spec.md`
**Spec section**: §3 Module 10 (brainstorm §8)
**Status**: pending
**Priority**: medium
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1415, TASK-1425
**Assigned-to**: unassigned

---

## Context

Persists eval runs/results to Postgres JSONB using the existing async (asyncpg) pattern. Implements
spec §3 Module 10. Operational telemetry — kept separate from any future audit store (there is NO
`AuditLedger`, spec §6).

---

## Scope

- Create `parrot/eval/sink.py` with:
  - `EvalReportSink(ABC)` — `async persist(report) -> str` (returns `run_id`).
  - `PostgresEvalSink(EvalReportSink)` — async asyncpg writes; stores `config`, `summary`, `scores`,
    and raw `trajectory` as JSONB.
  - Table DDL (idempotent `CREATE TABLE IF NOT EXISTS`) for `eval_runs`, `eval_results`,
    `eval_baselines`, `judge_cache` per spec §8 / brainstorm §8. (`judge_cache`/`eval_baselines`
    tables created now for the shared schema; population is a follow-up.)
- DSN/config via `navconfig` (`from navconfig import config`).
- Export from `parrot/eval/__init__.py`.

**NOT in scope**: the judge cache logic, baseline regression gate (CI), shadow-mode population.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/eval/sink.py` | CREATE | Sink ABC + Postgres sink + DDL |
| `packages/ai-parrot/src/parrot/eval/__init__.py` | MODIFY | Export sink names |
| `packages/ai-parrot/tests/eval/test_postgres_sink.py` | CREATE | Integration test (skip w/o DB) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from abc import ABC, abstractmethod
import json
import asyncpg                                  # existing dependency
from navconfig import config                    # standard config accessor
from parrot.eval.runner import EvalReport       # TASK-1425
```

### Existing Signatures to Use
```python
# Mirror the asyncpg + JSONB pattern (positional $N params, ::jsonb casts) from:
# parrot/bots/database/toolkits/postgres.py  (_execute_crud, $N binding, JSONB cast handling)
```

### Does NOT Exist
- ~~`AuditLedger`~~ — does not exist; the eval store is independent operational telemetry.
- ~~An ORM layer in `parrot` for eval~~ — use raw asyncpg, JSONB columns.

---

## Implementation Notes

### Key Constraints
- Async asyncpg only — no blocking I/O. Use a short-lived connection or pool from config DSN.
- JSONB serialize via `json.dumps(...)` with `::jsonb` casts ($N positional params).
- Idempotent DDL so the sink can self-provision on first run.
- Integration test must `pytest.skip` cleanly when no DB DSN is configured (CI-safe).

### Schema (per spec §8)
```
eval_runs       (run_id, dataset_name, config JSONB, started_at, finished_at, summary JSONB)
eval_results    (run_id, task_id, attempt, passed, scores JSONB, trajectory JSONB)
eval_baselines  (dataset_name, tag, run_id, pass_k, captured_at)
judge_cache     (cache_key, judge_model_version, rubric_version, verdict JSONB, created_at)
```

---

## Acceptance Criteria

- [ ] `from parrot.eval import EvalReportSink, PostgresEvalSink` resolves.
- [ ] `persist(report)` returns a `run_id` and writes one `eval_runs` row + N `eval_results` rows
      (integration test, gated on DB availability).
- [ ] DDL is idempotent (running twice does not error).
- [ ] Test skips gracefully without a configured DSN.
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/eval/sink.py`

---

## Test Specification

```python
import pytest
from parrot.eval import PostgresEvalSink

@pytest.mark.asyncio
async def test_persist_run(maybe_db_dsn):
    if not maybe_db_dsn:
        pytest.skip("no eval DB DSN configured")
    # build a small EvalReport, persist, assert row counts + returned run_id
```

---

## Agent Instructions

Standard SDD flow: read the postgres toolkit asyncpg pattern first, verify the contract, set index
`in-progress`, implement, run tests + ruff, move to `completed/`, set index `done`, fill the note.

---

## Completion Note

*(Agent fills this in when done)*
