# TASK-5249: G1 spike checks G1-01 … G1-13

**Feature**: FEAT-824 — Ontology backend: PostgreSQL OntologyStore + SurrealDB programme
**Spec**: `sdd/specs/ontology-backend.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-5248
**Assigned-to**: unassigned

---

## Context

TASK-5248 built the harness (models, verdict, report, runner). This task writes the thirteen
checks of spec §2 "Phase 1 — Spike G1" as `Check` coroutines and exposes them as `ALL_CHECKS`.
The checks are written and statically verified here; they are **run** against a live server in
TASK-5250 (host step). Spec Module 1.

---

## Scope

- Create the `checks/` package under `scripts/spikes/surrealdb_g1/` with one coroutine per check,
  each carrying `check_id`, `title` and `blocking` attributes (set by a small decorator in
  `_common.py`) and returning a `CheckResult` with concrete evidence (the query run and what came
  back) and measurements where the spec asks for latency.
- Create `scripts/spikes/surrealdb_g1/schema.surql` — the draft §5.2 schema
  (`sdd/proposals/SPEC_ontology_backend_postgres_surrealdb.md` §5.2) adapted to 3.3.x syntax.
- Create `tests/spikes/test_surrealdb_g1_checks.py` — static test that `ALL_CHECKS` is complete.

Check → file map (all ids from spec §2):

| File | Checks |
|---|---|
| `connection.py` | G1-01 connect, authenticate, reconnect over WebSocket |
| `schema.py` | G1-02 `schema.surql` applies (SCHEMAFULL, FLEXIBLE, relation tables) |
| `search.py` | G1-03 BM25 + Spanish snowball; G1-04 HNSW 1024 cosine KNN; G1-05 BM25 and KNN each with `CONTAINSANY` over up to 200 IRIs, latency recorded; G1-06 `search::rrf` availability (informational) |
| `live.py` | G1-07 `LIVE SELECT` delivers changes; consumer recovers after disconnect |
| `transactions.py` | G1-08 multi-statement transaction commits data + outbox row + stream counter atomically; G1-10 the four injected failures, replay converges |
| `concurrency.py` | G1-09 eight writer processes, unique `(origin, ns, db, seq)` and `request_id`, no lost or duplicated mutation; G1-13 SDK licence, image digest, several processes on one server (informational) |
| `graph.py` | G1-11 `RELATE`, bounded multi-hop traversal, reachability, bind parameters, a dynamic query that cannot mutate; G1-12 runtime tables, upsert by key, soft delete, equality filters, namespace/database per tenant with no cross-tenant read |

**NOT in scope**: running the checks against a server, the report file (TASK-5250); any change to
`harness.py` beyond what TASK-5248 delivered; any `pyproject.toml` change.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `scripts/spikes/surrealdb_g1/checks/__init__.py` | CREATE | `ALL_CHECKS` in G1 order |
| `scripts/spikes/surrealdb_g1/checks/_common.py` | CREATE | `g1_check` decorator, `connect()` helper, timing |
| `scripts/spikes/surrealdb_g1/checks/connection.py` | CREATE | G1-01 |
| `scripts/spikes/surrealdb_g1/checks/schema.py` | CREATE | G1-02 |
| `scripts/spikes/surrealdb_g1/checks/search.py` | CREATE | G1-03 … G1-06 |
| `scripts/spikes/surrealdb_g1/checks/live.py` | CREATE | G1-07 |
| `scripts/spikes/surrealdb_g1/checks/transactions.py` | CREATE | G1-08, G1-10 |
| `scripts/spikes/surrealdb_g1/checks/concurrency.py` | CREATE | G1-09, G1-13 |
| `scripts/spikes/surrealdb_g1/checks/graph.py` | CREATE | G1-11, G1-12 |
| `scripts/spikes/surrealdb_g1/schema.surql` | CREATE | KnowledgeStore schema under test |
| `tests/spikes/test_surrealdb_g1_checks.py` | CREATE | completeness test |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# From TASK-5248 (scripts/spikes/surrealdb_g1/harness.py), imported as a sibling module:
from harness import Check, CheckResult, SpikeContext
```

### Existing Signatures to Use
```python
# scripts/spikes/surrealdb_g1/harness.py (TASK-5248)
class CheckResult(BaseModel):
    check_id: str; title: str; blocking: bool
    status: Literal["pass", "fail", "skipped"]; evidence: str
    measurements: dict[str, float] = {}; fallback: str | None = None
class SpikeContext(BaseModel):
    url: str; username: str; password: str; server_image: str; sdk_version: str
Check = Callable[[SpikeContext], Awaitable[CheckResult]]
async def run(ctx, checks) -> list[CheckResult]   # reads check.check_id / .title / .blocking when a check raises
```

### Does NOT Exist
- ~~`surrealdb` in any `pyproject.toml`~~ — import it **inside** each check function only.
- ~~`search::rrf` guaranteed in 3.3.x~~ — G1-06 discovers it; it is informational.
- ~~an asyncdb SurrealDB driver~~ — use the `surrealdb` SDK (`AsyncSurreal`) directly.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "scripts/spikes/surrealdb_g1/checks/__init__.py", "action": "CREATE"},
    {"path": "scripts/spikes/surrealdb_g1/checks/_common.py", "action": "CREATE"},
    {"path": "scripts/spikes/surrealdb_g1/checks/connection.py", "action": "CREATE"},
    {"path": "scripts/spikes/surrealdb_g1/checks/schema.py", "action": "CREATE"},
    {"path": "scripts/spikes/surrealdb_g1/checks/search.py", "action": "CREATE"},
    {"path": "scripts/spikes/surrealdb_g1/checks/live.py", "action": "CREATE"},
    {"path": "scripts/spikes/surrealdb_g1/checks/transactions.py", "action": "CREATE"},
    {"path": "scripts/spikes/surrealdb_g1/checks/concurrency.py", "action": "CREATE"},
    {"path": "scripts/spikes/surrealdb_g1/checks/graph.py", "action": "CREATE"},
    {"path": "scripts/spikes/surrealdb_g1/schema.surql", "action": "CREATE"},
    {"path": "tests/spikes/test_surrealdb_g1_checks.py", "action": "CREATE"}
  ],
  "contract_symbols": ["sym:scripts/spikes/surrealdb_g1/harness.py#CheckResult", "sym:scripts/spikes/surrealdb_g1/harness.py#SpikeContext"]
}
```

---

## Implementation Notes

### Key Constraints
- Every check uses a fresh `NAMESPACE`/`DATABASE` named after its id (e.g. `g1_05`) so checks are
  independent and re-runnable; clean up at the end.
- G1-09 and G1-13 spawn processes with `multiprocessing` (spawn start method), each opening its
  own connection; collect results through a `Queue` — CPU-bound/process work is multiprocessing,
  never threads (repo conventions).
- G1-10: simulate each of the four failure points named in the spec by raising between steps and
  re-running the replay; pass only if the final state equals the no-failure run.
- G1-11 "dynamic query that cannot mutate": find and record the mechanism (a read-only user/role,
  or a statement allow-list); a check that only shows mutation is possible is `fail`.
- When the SDK fails a check, try the fallbacks the spec names (SDK 2.0.0 stable via a second
  `uv run --with`, or HTTP `POST /sql` with aiohttp) **in TASK-5250**; here, structure each check so
  its client calls go through `_common.connect()` so a fallback client can be swapped in, and set
  `fallback` on the result when used.
- Every query string is SurrealQL for 3.3.x — verify syntax against the official 3.3 docs when
  writing; the draft §5.2/§5.4 syntax is "illustrative".

---

## Implementation Blueprint

### Steps (in order)
1. Write `_common.py` (decorator + connect + timer) — *why*: every check shares them, and the
   runner reads the decorator's attributes when a check raises.
2. Write `schema.surql` from draft §5.2 — *why*: G1-02 and G1-03…05 need the tables and indexes.
3. Write one module per row of the Scope table — *why*: one concern per file keeps blocks < 80 lines.
4. Write `checks/__init__.py` listing the thirteen checks in id order.
5. Write the completeness test; run ruff and the test.

### `scripts/spikes/surrealdb_g1/checks/_common.py` (CREATE)
```python
"""Shared helpers for G1 checks: metadata decorator, connection, timing."""
from __future__ import annotations

import time
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Callable

from harness import Check, SpikeContext


def g1_check(check_id: str, title: str, *, blocking: bool) -> Callable[[Check], Check]:
    """Attach check_id/title/blocking to a check coroutine (read by harness.run on failure)."""
    def decorate(fn: Check) -> Check:
        fn.check_id = check_id  # type: ignore[attr-defined]
        fn.title = title  # type: ignore[attr-defined]
        fn.blocking = blocking  # type: ignore[attr-defined]
        return fn
    return decorate


@asynccontextmanager
async def connect(ctx: SpikeContext, namespace: str, database: str) -> AsyncIterator[Any]:
    """Open an authenticated AsyncSurreal connection scoped to namespace/database."""
    from surrealdb import AsyncSurreal  # imported lazily: not a project dependency

    # FILL IN: open, signin(username/password), use(namespace, database), yield, close —
    #          exact SDK 3.x calls verified against the pinned SDK's docs.
    raise NotImplementedError
    yield


class Timer:
    """`with Timer() as t: ...; t.ms` — wall-clock milliseconds."""

    def __enter__(self) -> "Timer":
        self._start = time.perf_counter()
        return self

    def __exit__(self, *exc: object) -> None:
        self.ms = (time.perf_counter() - self._start) * 1000.0
```

### `scripts/spikes/surrealdb_g1/checks/__init__.py` (CREATE)
```python
"""G1 check list in spec order (FEAT-824 §2)."""
from __future__ import annotations

from checks.concurrency import check_g1_09_writers, check_g1_13_info
from checks.connection import check_g1_01_connect
from checks.graph import check_g1_11_traversal, check_g1_12_document_store
from checks.live import check_g1_07_live
from checks.schema import check_g1_02_schema
from checks.search import check_g1_03_bm25, check_g1_04_hnsw, check_g1_05_containsany, check_g1_06_rrf
from checks.transactions import check_g1_08_transaction, check_g1_10_failure_injection

ALL_CHECKS = [
    check_g1_01_connect, check_g1_02_schema, check_g1_03_bm25, check_g1_04_hnsw,
    check_g1_05_containsany, check_g1_06_rrf, check_g1_07_live, check_g1_08_transaction,
    check_g1_09_writers, check_g1_10_failure_injection, check_g1_11_traversal,
    check_g1_12_document_store, check_g1_13_info,
]
```

### Each check module (CREATE) — shape of one check
```python
from checks._common import Timer, connect, g1_check
from harness import CheckResult, SpikeContext


@g1_check("G1-03", "BM25 full-text search with a Spanish snowball analyzer", blocking=True)
async def check_g1_03_bm25(ctx: SpikeContext) -> CheckResult:
    """Index Spanish chunks, query an inflected form, expect the stemmed match ranked first."""
    async with connect(ctx, "g1", "g1_03") as db:
        # FILL IN: apply analyzer + BM25 index, insert fixture chunks, run `@1@` query with
        #          search::score, assert ranking; evidence = query + returned ids/scores.
        ...
    return CheckResult(check_id="G1-03", title=check_g1_03_bm25.title, blocking=True,
                       status="pass", evidence="FILL IN")
```

### `tests/spikes/test_surrealdb_g1_checks.py` (CREATE)
```python
"""ALL_CHECKS is complete and correctly flagged (no server, no SDK)."""
from __future__ import annotations

import sys
from pathlib import Path

SPIKE = Path(__file__).resolve().parents[2] / "scripts" / "spikes" / "surrealdb_g1"
BLOCKING = {"G1-01", "G1-02", "G1-03", "G1-04", "G1-05", "G1-07", "G1-08", "G1-09", "G1-10", "G1-11", "G1-12"}


def test_all_checks_complete_and_flagged() -> None:
    sys.path.insert(0, str(SPIKE))
    from checks import ALL_CHECKS

    ids = [c.check_id for c in ALL_CHECKS]
    assert ids == [f"G1-{n:02d}" for n in range(1, 14)]
    assert {c.check_id for c in ALL_CHECKS if c.blocking} == BLOCKING
```

### FILL IN checklist
- [ ] `_common.connect` — SDK 3.x connect/signin/use/close.
- [ ] `schema.surql` — draft §5.2 tables, analyzer, BM25/HNSW indexes, relation tables, `synth`.
- [ ] each of the 13 checks — queries, assertions, evidence text, measurements (G1-05 latency per
      IRI-set size; G1-09 counts).
- [ ] G1-11 non-mutating dynamic query mechanism; G1-12 cross-tenant read attempt must fail.

---

## Acceptance Criteria

- [ ] `ALL_CHECKS` holds G1-01 … G1-13 in order with the spec's blocking flags.
- [ ] Importing `checks` does not import `surrealdb`.
- [ ] Every check returns evidence naming the query/command it ran.
- [ ] No `pyproject.toml` is modified; `ruff check scripts/spikes/surrealdb_g1 tests/spikes` passes.

---

## Validation Commands

- `pytest tests/spikes/test_surrealdb_g1_checks.py -q`

---

## Agent Instructions

1. Work in the feature worktree (`parrot sdd worktree ensure --slug ontology-backend --feature-id FEAT-824`).
2. Confirm TASK-5248 is `done` in `sdd/tasks/index/ontology-backend.json`.
3. Verify the Codebase Contract against the delivered `harness.py`; fix it here first if it drifted.
4. Mark `in-progress`, implement from the blueprint, complete every `FILL IN`.
5. Run the Validation Commands; commit only the files listed above.
6. Close with `parrot sdd task close TASK-5249 ontology-backend verified`; fill in the Completion Note.

---

## Completion Note

Seat: gpt-5.6-terra · Backend: codex · Attempts: 1 · Duration: 426s. Merge-tier validation green.

**Completed by**: sdd-worker (coder: gpt-5.6-terra)
**Date**: 2026-11-07
**Notes**:

**Deviations from spec**: none
