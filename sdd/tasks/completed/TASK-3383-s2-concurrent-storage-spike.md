# TASK-3383: G2/S2 gate — concurrent local episodic backend and durable review application

**Feature**: FEAT-571 — Agent Memory Dynamics
**Spec**: `sdd/specs/memory-dynamics.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: XL (> 8h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 row **G2** (Lane 0a gate, brainstorm spike S2). G2 is *explicitly* a dependency of
review implementation on **every** backend, not only the SDD adapter (spec §3 "G2 is
explicitly a dependency of review implementation, including existing backends").

Today no backend offers an atomic review transition: the protocol has store/search/
recent/failures/delete-expired/count/`update_metadata` only (C5). PostgreSQL's
`update_metadata` is a shallow JSONB `||` merge — two concurrent `fsrs` replacements
clobber each other; Redis does `hget` → merge → `hset`; FAISS rewrites whole snapshot
files; `LedgerLog.append` is a single fsync'd `O_APPEND` write whose returned offset is
best-effort under contention. Shared SDD worktrees (eight+ processes) need a local
backend that survives all of this (AC06, AC14).

S2 must **freeze**: the local backend choice (SQLite/WAL candidate vs FAISS snapshots),
the atomic review protocol (durable idempotency + apply-revision), identity/migration
contract (including `model_id` encoding — spec §2 "Encode backend/model without ambiguous
slash concatenation"), local retrieval without an embedding service (lexical fallback),
oversampling, and the review-log ↔ backend-state recovery order under crash/retry.

---

## Scope

- Prototype `SQLiteEpisodeBackend` **inside the spike dir** (`sqlite_prototype.py`,
  aiosqlite, WAL, `busy_timeout`, `BEGIN IMMEDIATE`), implementing the current
  `AbstractEpisodeBackend` protocol *plus* two experimental operations the gate is
  measuring: `apply_review(record) -> receipt` (durable dedupe on outcome id/revision +
  state apply-revision check in **one transaction**) and lexical `search_text()`
  (FTS5 or LIKE — report which) for recall without embeddings.
- Multi-process harness (`harness.py`, `multiprocessing` **processes**, not coroutines):
  8 writer/reader processes; 5k baseline and 10k scale episodes; workloads: plain
  writes, duplicate `apply_review` calls, concurrent reviews of the *same* memory,
  injected crash points (before log write / after log write before state / after state
  before ack), restart + replay, namespace + `model_id` filtering, and a feedback-import
  shaped batch (deterministic ids, original timestamps).
- Run the **same** workloads against `FAISSBackend` with `persistence_path` snapshots
  (single-writer contract) and record lost writes / corruption.
- Measure p95 `recall_similar` (embedding latency reported **separately** from end-to-
  end; use a fixed-vector stub embedder so the DB cost is isolated) and p95
  `search_text` at 5k; disclose hardware (CPU model, disk type, kernel).
- Prove convergence: after every crash/replay scenario, materialized state equals one
  application of each accepted outcome revision (spec §2 "Required invariant").
- Commit `REPORT.md`, `metrics.json`, `amendment.md` freezing backend, atomic protocol,
  identity/migration (incl. `model_id` encoding, TTL interaction for imported
  feedback — spec §2 "prevent generic TTL defaults from silently replacing its new
  retention policy"), lexical fallback, oversampling, JSONL/PG review-log cursor
  format and recovery order. Logs → `artifacts/logs/`.

> **Amendment (sdd-worker, 2026-09-18): all spike artifacts (REPORT.md, metrics.json,
> amendment.md) are relocated from `sdd/state/FEAT-571/spikes/s2-concurrent-storage/` to
> `packages/ai-parrot/tests/memory/dynamics/spikes/s2_storage/` throughout this file. The
> FEAT-549 sdd-coder engine's fidelity gate (`check_fidelity()`) unconditionally rejects any
> coder-committed path starting with `sdd/`, regardless of what a task's own contract lists —
> so these gate deliverables must live in a directory the coder already owns. The orchestrator
> (sdd-worker) is responsible for mirroring the final REPORT.md/metrics.json/amendment.md into
> `sdd/state/FEAT-571/spikes/s2-concurrent-storage/` as a post-merge step for owner review.

**NOT in scope**: creating `parrot/memory/episodic/backends/sqlite.py` (M2, and only if
G2 selects it); adding `store.review`/`cite` (M2); `parrot/memory/dynamics/*` (M1);
real PostgreSQL/Redis integration runs (M2's `test_backend_review_contracts` — S2 only
*documents* their current non-atomicity from source); editing the spec (owner applies
`amendment.md`); U4 log-retention policy (owner decision, record as open in the report).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/memory/dynamics/spikes/s2_storage/__init__.py` | CREATE | package marker |
| `packages/ai-parrot/tests/memory/dynamics/spikes/s2_storage/sqlite_prototype.py` | CREATE | throwaway `SQLiteEpisodeBackend` candidate + `apply_review`/`search_text` |
| `packages/ai-parrot/tests/memory/dynamics/spikes/s2_storage/harness.py` | CREATE | multi-process workloads, crash injection, metrics, report writer |
| `packages/ai-parrot/tests/memory/dynamics/spikes/s2_storage/test_s2_harness.py` | CREATE | fast single-process contract tests + env-gated full load run |
| `packages/ai-parrot/tests/memory/dynamics/spikes/s2_storage/REPORT.md` | CREATE | reproducible gate report (hardware, workload, metrics, pass/fail) |
| `packages/ai-parrot/tests/memory/dynamics/spikes/s2_storage/metrics.json` | CREATE | raw summary metrics |
| `packages/ai-parrot/tests/memory/dynamics/spikes/s2_storage/amendment.md` | CREATE | proposed storage/identity/protocol amendment |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` @ `fc1a5728a55648566e264cb95c5df36190438204` on 2026-09-18.
> `core/` = `packages/ai-parrot/src/parrot/`.

### Verified Imports
```python
from parrot.memory.episodic.backends.abstract import AbstractEpisodeBackend   # core/memory/episodic/backends/abstract.py:11 (Protocol)
from parrot.memory.episodic.backends.faiss import FAISSBackend                 # core/memory/episodic/backends/faiss.py:54
from parrot.memory.episodic.models import EpisodicMemory, EpisodeSearchResult, EpisodeOutcome, EpisodeCategory, MemoryNamespace  # models.py:55,203,20,29,214
from parrot.memory.episodic.store import EpisodicMemoryStore                  # core/memory/episodic/store.py:57
from parrot.knowledge.wiki.ledger.log import LedgerLog                        # core/knowledge/wiki/ledger/log.py:10
import aiosqlite                                                              # packages/ai-parrot/pyproject.toml:192 ("aiosqlite>=0.17", core dep — nothing to add)
```

### Existing Signatures to Use
```python
# core/memory/episodic/backends/abstract.py  (Protocol — implement ALL of these in the prototype)
class AbstractEpisodeBackend(Protocol):                                                         # :11
    async def store(self, episode: EpisodicMemory) -> str: ...                                  # :18
    async def search_similar(self, embedding: list[float], namespace_filter: dict[str, Any],
                             top_k: int = 5, score_threshold: float = 0.3,
                             include_failures_only: bool = False) -> list[EpisodeSearchResult]: ...  # :29
    async def get_recent(self, namespace_filter: dict[str, Any], limit: int = 10,
                         since: datetime | None = None) -> list[EpisodicMemory]: ...            # :50
    async def get_failures(self, agent_id: str, tenant_id: str = "default", limit: int = 5) -> list[EpisodicMemory]: ...  # :67  (incomplete scope — spec C5)
    async def delete_expired(self) -> int: ...                                                  # :84
    async def count(self, namespace_filter: dict[str, Any]) -> int: ...                         # :92
    async def update_metadata(self, episode_ids: list[str], patch: dict[str, Any]) -> int: ...  # :106 (shallow merge — NOT a review transaction)

# core/memory/episodic/backends/faiss.py
class FAISSBackend:                                                                             # :54
    def __init__(self, dimension: int = 384, persistence_path: str | None = None,
                 max_episodes: int = 10000, auto_save_interval: int = 100) -> None: ...         # :70
    async def configure(self) -> None: ...   # :89 (loads snapshot)     async def store(...)     # :111
    async def update_metadata(...)           # :257 (in-memory patch + save())   async def save() # :292   async def load() # :317
def _matches_filter(...)                                                                        # :44 (module-level post-filter)

# core/memory/episodic/backends/pgvector.py — DOCUMENT ONLY (no live run in S2)
class PgVectorBackend:                       # :66 ; CREATE TABLE :119 ; episode_id UUID PRIMARY KEY :120 ; metadata JSONB :151
#   store(): ON CONFLICT (episode_id) DO NOTHING :299 ; update_metadata(): SET metadata = COALESCE(metadata,'{}') || $1::jsonb :515
# core/memory/episodic/backends/redis_vector.py — DOCUMENT ONLY
class RedisVectorBackend:                    # :145 ; update_metadata :544 → hget(key,"metadata") :575 … hset(key,"metadata",…) :587 (read-modify-write, no WATCH/MULTI)

# core/memory/episodic/store.py
class EpisodicMemoryStore:                                                                      # :57
    def __init__(self, backend: AbstractEpisodeBackend, embedding_provider=None, reflection_engine=None,
                 redis_cache=None, default_ttl_days: int = 90, importance_scorer=None, recall_strategy=None) -> None  # :86  (TTL 90 default — the generic TTL S2 must keep away from imported feedback)
    async def record_episode(self, namespace, situation, action_taken, outcome, ..., ttl_days: int | None = None) -> EpisodicMemory  # :106 (ttl_days=0 → no expiry :157)
    async def recall_similar(self, query, namespace, top_k=5, score_threshold=0.3, category=None, include_failures_only=False) -> list[EpisodeSearchResult]  # :377 (returns [] with no embedding provider)
    @classmethod async def create_faiss(cls, persistence_path=None, dimension=384, max_episodes=10000, ...) -> EpisodicMemoryStore  # :812

# core/memory/episodic/models.py
class EpisodeSearchResult(EpisodicMemory): score: float  # :203, ge=0.0 le=1.01 :206 — similarity only, cannot hold ranking_score
class MemoryNamespace(BaseModel):                          # :214 ; def build_filter(self) -> dict[str, Any] :245 (tenant_id, agent_id always; others when not None)

# core/knowledge/wiki/ledger/log.py
class LedgerLog:                                           # :10 ; __init__(self, path: str) :13
    def append(self, event: LedgerEvent) -> tuple[str, int]: ...   # :21 — single O_APPEND os.write ≤ 4 KiB + fsync; returned offset best-effort (docstring :23-35)
    def iter_events(self, from_offset: int = 0) -> Iterator[tuple[LedgerEvent, int]]: ...  # :83
# shared root: LedgerService.from_root(root) (core/knowledge/wiki/ledger/service.py:114) resolves <root>/.parrot/ledger (project.py:508-515)
```

### Does NOT Exist
- ~~`parrot.memory.episodic.backends.sqlite`~~ / ~~`SQLiteEpisodeBackend`~~ — the prototype lives **only** in the spike dir; M2 creates the real module *if* this gate selects it.
- ~~`EpisodicMemoryStore.review()` / `.cite()`~~, ~~`ReviewRecord`/`ReviewReceipt` models~~ — M1/M2. The spike defines *local* dataclasses for the experiment.
- ~~`MemoryNamespace.model_id`~~ — absent (spec C2). The prototype adds a `model_id` **column** and filter key in its own schema to test isolation; do not edit `models.py`.
- ~~an atomic review guarantee from `update_metadata`~~ on any backend (spec §6). Do not "prove" safety of `hget`/`hset` or JSONB `||`.
- ~~a `search_text`/lexical route on any existing backend~~ — `RecallStrategy.search` requires a query embedding (spec C14); the lexical route is the experiment.
- ~~`JsonlReviewLog` / `PostgresReviewLog`~~ — proposed M2 sinks; the spike may emulate the JSONL sink with `LedgerLog`-style `O_APPEND` writes to test recovery order, but must not create `parrot/memory/dynamics/*`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/tests/memory/dynamics/spikes/s2_storage/__init__.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/memory/dynamics/spikes/s2_storage/sqlite_prototype.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/memory/dynamics/spikes/s2_storage/harness.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/memory/dynamics/spikes/s2_storage/test_s2_harness.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/memory/dynamics/spikes/s2_storage/REPORT.md", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/memory/dynamics/spikes/s2_storage/metrics.json", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/memory/dynamics/spikes/s2_storage/amendment.md", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/memory/episodic/backends/abstract.py#AbstractEpisodeBackend",
    "sym:packages/ai-parrot/src/parrot/memory/episodic/backends/abstract.py#AbstractEpisodeBackend.update_metadata",
    "sym:packages/ai-parrot/src/parrot/memory/episodic/backends/faiss.py#FAISSBackend",
    "sym:packages/ai-parrot/src/parrot/memory/episodic/backends/pgvector.py#PgVectorBackend",
    "sym:packages/ai-parrot/src/parrot/memory/episodic/backends/redis_vector.py#RedisVectorBackend",
    "sym:packages/ai-parrot/src/parrot/memory/episodic/store.py#EpisodicMemoryStore",
    "sym:packages/ai-parrot/src/parrot/memory/episodic/store.py#EpisodicMemoryStore.recall_similar",
    "sym:packages/ai-parrot/src/parrot/memory/episodic/models.py#EpisodicMemory",
    "sym:packages/ai-parrot/src/parrot/memory/episodic/models.py#EpisodeSearchResult",
    "sym:packages/ai-parrot/src/parrot/memory/episodic/models.py#MemoryNamespace",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/log.py#LedgerLog",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/log.py#LedgerLog.append"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- **Real processes**: `multiprocessing.get_context("spawn")`, each worker opens its own `aiosqlite` connection to the *same* file under a `tmp_path`; coroutine-only concurrency is explicitly insufficient (spec §4 `test_eight_process_local_store`).
- **One transaction per review**: `BEGIN IMMEDIATE` → check `reviews(outcome_id, outcome_revision)` unique → check `state.apply_revision == expected` → write review row + new state + ack in the same commit. Return `applied | duplicate | stale_revision | pending` (spec §7 Failure Contract categories `stale_revision`, `outcome_conflict`, `storage_unavailable`).
- **Crash injection is deterministic**: an env var `S2_CRASH_AT ∈ {before_log, after_log, after_state}` read by the worker; the worker `os._exit(137)` at that point; the parent restarts and calls `replay()`; then asserts convergence.
- **Identity**: episode ids are UUID strings (PostgreSQL PK is `UUID` — imported feedback must map deterministically, e.g. `uuid5(NAMESPACE, legacy_feedback_id)`); `model_id` stored as its own column, never `backend/model` concatenated (spec §2).
- **TTL**: imported rows carry `expires_at = NULL`; prove `delete_expired()` never touches them while the store's default `ttl_days=90` still applies to ordinary episodes.
- **Numbers to disclose**: hardware, Python version, SQLite version (`sqlite3.sqlite_version`), aiosqlite version, workload sizes, p50/p95/p99, lost-write count, per-scenario convergence — in `metrics.json` and REPORT.md tables.
- Formatting: `black` 120 cols; `ruff check` clean on the spike package. No new dependencies.

### References in Codebase
- `core/knowledge/wiki/store.py:243` `SQLitePragmaPolicy` / `:264` `WikiStoreBusy` — the repo's existing SQLite/WAL hardening pattern (busy handling) to mirror in the prototype.
- `core/knowledge/wiki/ledger/log.py:21-81` — durable append semantics and why the offset is not a cursor.
- `core/memory/episodic/backends/faiss.py:292-360` — snapshot save/load the comparison arm exercises.

---

## Implementation Blueprint

### Steps (in order)
1. Write `sqlite_prototype.py`: schema (episodes + model_id column, reviews unique(outcome_id, outcome_revision), state with apply_revision, optional FTS5 table), the protocol methods, `apply_review`, `search_text`, `replay` — *why*: the gate compares a concrete candidate, not a design sketch.
2. Write `harness.py`: workload definitions, spawn-based worker entry, crash injection, timing collection, FAISS comparison arm, `write_report()` — *why*: identical workloads on both arms is what makes the comparison valid.
3. Write `test_s2_harness.py`: fast single-process tests (dedupe, stale revision, model_id filter, TTL exemption, lexical search) that always run; one `PARROT_SPIKE_FULL=1`-gated test for the 8-process 5k/10k runs and crash matrix — *why*: FEAT-563 validation is a pytest file; the heavy run stays opt-in.
4. Run the full matrix, `tee` to `artifacts/logs/feat-571-s2-<ts>.log`, fill REPORT.md / metrics.json / amendment.md — *why*: AC14 requires disclosed workload/hardware with the numbers.

### `packages/ai-parrot/tests/memory/dynamics/spikes/s2_storage/sqlite_prototype.py` (CREATE)
```python
"""S2 spike: SQLite/WAL episodic backend prototype (throwaway — M2 decides the real module)."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiosqlite  # pyproject.toml:192 — core dependency

from parrot.memory.episodic.models import EpisodeSearchResult, EpisodicMemory  # models.py:203,55

logger = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS episodes (
    episode_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, agent_id TEXT NOT NULL,
    user_id TEXT, session_id TEXT, room_id TEXT, crew_id TEXT, model_id TEXT,
    created_at TEXT NOT NULL, expires_at TEXT, is_failure INTEGER NOT NULL DEFAULT 0,
    payload TEXT NOT NULL, embedding TEXT
);
CREATE TABLE IF NOT EXISTS reviews (
    outcome_id TEXT NOT NULL, outcome_revision INTEGER NOT NULL, episode_id TEXT NOT NULL,
    grade INTEGER, recorded_at TEXT NOT NULL, PRIMARY KEY (outcome_id, outcome_revision, episode_id)
);
CREATE TABLE IF NOT EXISTS memory_state (
    episode_id TEXT PRIMARY KEY, apply_revision INTEGER NOT NULL, state TEXT NOT NULL
);
"""
# FILL IN: optional `CREATE VIRTUAL TABLE episodes_fts USING fts5(...)` — report whether FTS5 is available in this SQLite build.


@dataclass(frozen=True)
class ReviewCommand:
    """Experimental review input: idempotency key is (outcome_id, outcome_revision), never episode provenance."""

    outcome_id: str
    outcome_revision: int
    episode_id: str
    grade: int
    expected_apply_revision: int
    new_state: dict[str, Any]


@dataclass(frozen=True)
class ReviewReceipt:
    """Result category per spec §7 Failure Contract."""

    episode_id: str
    result: str  # applied | duplicate | stale_revision | pending
    apply_revision: int
    reason: str = ""


class SQLiteEpisodeBackend:
    """Implements AbstractEpisodeBackend (abstract.py:11) plus apply_review/search_text/replay for the gate."""

    def __init__(self, path: Path, *, busy_timeout_ms: int = 5000) -> None:
        self._path = Path(path)
        self._busy_timeout_ms = busy_timeout_ms
        self._db: aiosqlite.Connection | None = None

    async def configure(self) -> None:
        """Open the connection, enable WAL + busy_timeout, create schema."""
        self._db = await aiosqlite.connect(str(self._path))
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute(f"PRAGMA busy_timeout={self._busy_timeout_ms}")
        await self._db.executescript(SCHEMA)
        logger.info("S2 sqlite backend ready at %s", self._path)

    async def close(self) -> None:
        if self._db is not None:
            await self._db.close()

    async def store(self, episode: EpisodicMemory) -> str:
        # FILL IN: INSERT OR IGNORE (duplicate ids are no-ops like FAISS/PG); model_id from episode.metadata.get("model_id").
        raise NotImplementedError

    async def search_similar(self, embedding, namespace_filter, top_k=5, score_threshold=0.3, include_failures_only=False) -> list[EpisodeSearchResult]:
        # FILL IN: SQL filter (incl. model_id) BEFORE top-k, cosine in Python over the filtered candidate set; score ≤ 1.0.
        raise NotImplementedError

    async def search_text(self, query: str, namespace_filter: dict[str, Any], top_k: int = 5) -> list[EpisodeSearchResult]:
        # FILL IN: FTS5 bm25 (normalize to [0,1]) or LIKE fallback — the "recall without embeddings" route (spec §2).
        raise NotImplementedError

    async def apply_review(self, command: ReviewCommand) -> ReviewReceipt:
        # FILL IN: BEGIN IMMEDIATE; if (outcome_id, revision, episode_id) exists → duplicate; if state.apply_revision !=
        # expected → stale_revision; else INSERT review, UPSERT state with apply_revision+1; COMMIT; honour S2_CRASH_AT.
        raise NotImplementedError

    async def replay(self, log_rows: list[ReviewCommand]) -> int:
        # FILL IN: re-apply commands idempotently; return number newly applied. Convergence invariant: spec §2 Durable Storage.
        raise NotImplementedError

    # FILL IN: get_recent / get_failures / delete_expired / count / update_metadata per abstract.py:50-125 (delete_expired must
    # skip rows with expires_at IS NULL — imported feedback exemption).
```
**Why this shape**: the three tables make the spec's invariant checkable in SQL — reviews are the durable dedupe set, `memory_state.apply_revision` is the stale-write guard, and both change in one `BEGIN IMMEDIATE` transaction. `ReviewCommand` keys on outcome identity, matching spec §2 "Optional episode provenance is not its idempotency key".

### `packages/ai-parrot/tests/memory/dynamics/spikes/s2_storage/harness.py` (CREATE)
```python
"""S2 spike harness: spawn-based multi-process workloads, crash injection, FAISS comparison, report writer."""
from __future__ import annotations

import asyncio
import json
import logging
import multiprocessing as mp
import os
import platform
import sqlite3
import statistics
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)
SPIKE_DIR = Path(__file__).resolve().parent  # coder-owned spike package dir — sdd-coder fidelity gate forbids commits under sdd/
CRASH_POINTS = ("before_log", "after_log", "after_state")


@dataclass
class Workload:
    """One named scenario: sizes, process count and which arm(s) run it."""

    name: str
    episodes: int
    processes: int = 8
    crash_at: str | None = None
    arms: tuple[str, ...] = ("sqlite", "faiss")
    extra: dict[str, Any] = field(default_factory=dict)


def environment() -> dict[str, str]:
    """Hardware/software disclosure for REPORT.md (AC14)."""
    return {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "cpu": platform.processor() or "unknown",
        "sqlite": sqlite3.sqlite_version,
        # FILL IN: aiosqlite.__version__, faiss.__version__, disk type (lsblk -d -o name,rota), cpu model (/proc/cpuinfo).
    }


def _worker_main(arm: str, db_path: str, worker_id: int, plan: dict[str, Any], out_q: mp.Queue) -> None:
    """Process entry: run the plan against `arm`, push timings/results; os._exit at plan['crash_at'] if set."""
    # FILL IN: asyncio.run(...) around the arm's async body; catch nothing — a crash must be a real process death.
    raise NotImplementedError


def run_workload(workload: Workload, tmp_dir: Path) -> dict[str, Any]:
    """Spawn `workload.processes` workers per arm, join, aggregate p50/p95/p99, lost writes, convergence."""
    ctx = mp.get_context("spawn")
    # FILL IN: for each arm → fresh db/snapshot dir under tmp_dir; start workers; collect from out_q; if crash_at → restart
    # one worker with replay=True; verify count()==expected writes and state==one-application-per-revision.
    raise NotImplementedError


def default_matrix() -> list[Workload]:
    """5k baseline + 10k scale, dupes, same-memory reviews, 3 crash points, namespace/model_id filter, import batch."""
    # FILL IN: build the list from spec §3 row G2; keep names stable — REPORT.md tables key on them.
    raise NotImplementedError


def write_report(results: list[dict[str, Any]], *, commands: list[str]) -> Path:
    """Persist metrics.json + REPORT.md under SPIKE_DIR."""
    SPIKE_DIR.mkdir(parents=True, exist_ok=True)
    (SPIKE_DIR / "metrics.json").write_text(json.dumps({"environment": environment(), "results": results}, indent=2, default=str) + "\n")
    # FILL IN: REPORT.md — Commands · Environment · Workload table · p50/p95/p99 per arm (embedding latency separate) ·
    # lost writes · crash/replay convergence matrix · PG/Redis/FAISS non-atomicity evidence (source line refs) · Pass/Fail
    # (zero lost writes; p95 recall_similar < 50 ms @5k) · Limitations · pointer to amendment.md.
    raise NotImplementedError
```
**Why**: `spawn` processes + a shared file are the only faithful model of "eight worktrees"; `Workload` names are the join key between `metrics.json` and the report tables so the amendment can cite exact rows.

### `packages/ai-parrot/tests/memory/dynamics/spikes/s2_storage/test_s2_harness.py` (CREATE)
```python
"""S2 gate tests: fast single-process contract checks (always) + full multi-process matrix (PARROT_SPIKE_FULL=1)."""
from __future__ import annotations

import os

import pytest

from . import harness
from .sqlite_prototype import ReviewCommand, SQLiteEpisodeBackend

FULL = os.environ.get("PARROT_SPIKE_FULL") == "1"


@pytest.fixture
async def backend(tmp_path):
    be = SQLiteEpisodeBackend(tmp_path / "episodes.sqlite")
    await be.configure()
    yield be
    await be.close()


async def test_duplicate_review_is_duplicate(backend) -> None:
    # FILL IN: store one episode; apply_review twice with same (outcome_id, revision) → applied then duplicate; apply_revision unchanged.
    raise NotImplementedError


async def test_stale_revision_rejected(backend) -> None:
    # FILL IN: two commands with the same expected_apply_revision → second returns stale_revision; state reflects the first only.
    raise NotImplementedError


async def test_model_id_filter_before_top_k(backend) -> None:
    # FILL IN: same pattern under two model_ids; filter returns only the requested model's rows even with top_k=1.
    raise NotImplementedError


async def test_imported_rows_survive_delete_expired(backend) -> None:
    # FILL IN: expires_at NULL row + expired row → delete_expired() == 1 and the imported row remains.
    raise NotImplementedError


async def test_lexical_search_without_embeddings(backend) -> None:
    # FILL IN: search_text finds a lesson by a distinctive token with no embedding stored; scores within [0, 1].
    raise NotImplementedError


@pytest.mark.skipif(not FULL, reason="set PARROT_SPIKE_FULL=1 to run the 8-process matrix and write REPORT.md")
def test_full_matrix_writes_report(tmp_path) -> None:
    # FILL IN: results = [harness.run_workload(w, tmp_path) for w in harness.default_matrix()]; harness.write_report(...);
    # assert every sqlite arm has lost_writes == 0 and all crash scenarios converged. Bounded by AC06/AC14.
    raise NotImplementedError
```
**Why**: the fast tests pin the *semantics* the amendment will freeze (dedupe, stale revision, scoped filters, TTL exemption, lexical route); the gated test produces the AC14 numbers.

### `packages/ai-parrot/tests/memory/dynamics/spikes/s2_storage/amendment.md` (CREATE)
```markdown
# Proposed spec amendment — S2 (TASK-3383) · status: PROPOSED (owner + architecture review required)

## Freeze
- Local dynamics backend: FILL IN (SQLite/WAL prototype → M2 `backends/sqlite.py` | FAISS snapshots single-writer only) — evidence: REPORT rows FILL IN
- Atomic review protocol: one transaction = dedupe(outcome_id, outcome_revision) + apply_revision check + review row + state + ack; categories applied|duplicate|stale_revision|pending|storage_unavailable
- Review-log cursor/record schema (JsonlReviewLog / PostgresReviewLog): FILL IN ; recovery order after crash: FILL IN (log → state → ack; ack is an appended record, never a rewrite)
- Identity/migration: episode ids UUID (uuid5 of legacy `coder-feedback:` id — FILL IN namespace constant); `model_id` as its own dimension/column, never `backend/model` concatenation; imported rows `expires_at = NULL`
- Local retrieval without embeddings: FILL IN (FTS5 | LIKE) ; oversampling factor: FILL IN (candidate 4) ; lexical fallback order: FILL IN
- PostgreSQL / Redis: M2 must implement transactional identity/state (`||` merge and hget/hset documented as unsafe — REPORT §Evidence); FAISS stays single-writer

## Pass/Fail
- Zero lost writes, 8 processes, 5k and 10k: PASS|FAIL
- p95 recall_similar < 50 ms at 5k (hardware: FILL IN; embedding stub latency reported separately): PASS|FAIL
- Crash/replay convergence at before_log / after_log / after_state: PASS|FAIL each
- Feedback-import batch idempotent (twice → no new rows, timestamps preserved): PASS|FAIL

## Open (not decided by this gate)
- U4 review-log retention (owner) · optional G4 coordination on page-state atomicity

## Sections to edit on acceptance
§2 "Durable Storage and Lineage", §2 Data Models (MemoryRef/ReviewRecord/ReviewReceipt storage fields), §3 M2 eligibility row and conditional `backends/sqlite.py` path, §6 C5.
```
**Why**: this is the artifact the owner reviews to unblock M2/M5; the spike code itself never becomes production code.

### FILL IN checklist
- [ ] `sqlite_prototype.py::apply_review/replay` — one-transaction dedupe + apply_revision; bounded by spec §2 "Required invariant" and §7 categories
- [ ] `sqlite_prototype.py::search_similar/search_text` — filters (incl. `model_id`) before top-k, bounded scores ≤ 1.0; bounded by spec §2 "apply every namespace filter before inclusion"
- [ ] `sqlite_prototype.py::delete_expired` — exempt `expires_at IS NULL`; bounded by spec §2 TTL paragraph
- [ ] `harness.py::run_workload/_worker_main/default_matrix` — spawn processes, crash matrix, FAISS arm; bounded by spec §3 row G2 and §4 `test_eight_process_local_store`
- [ ] `harness.py::environment/write_report` — hardware + embedding-latency disclosure; bounded by AC14
- [ ] `REPORT.md`, `metrics.json`, `amendment.md` — from the logged full run

---

## Acceptance Criteria

- [ ] Fast tests pass (duplicate, stale revision, model_id filter, TTL exemption, lexical search)
- [ ] Full matrix run once with `PARROT_SPIKE_FULL=1`; log under `artifacts/logs/`; REPORT.md quotes the exact command
- [ ] REPORT.md discloses hardware, versions, workload sizes, p50/p95/p99 per arm with embedding latency separate, lost-write counts, and per-crash-point convergence (AC06, AC14)
- [ ] REPORT.md documents PostgreSQL `||` merge, Redis read-modify-write and FAISS snapshot rewrite as non-atomic with source line references (no live PG/Redis run claimed)
- [ ] `amendment.md` freezes backend, atomic protocol, cursor/recovery order, identity/migration (`model_id` encoding, TTL exemption), lexical fallback and oversampling, with PASS/FAIL per check; U4 recorded as open
- [ ] `black --check` and `ruff check` clean on `packages/ai-parrot/tests/memory/dynamics/spikes/s2_storage/`
- [ ] No files under `parrot/memory/dynamics/` or `parrot/memory/episodic/backends/sqlite.py`; no spec edits; no dependency changes

---

## Validation Commands

- `pytest packages/ai-parrot/tests/memory/dynamics/spikes/s2_storage/test_s2_harness.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/memory/dynamics/spikes/s2_storage/test_s2_harness.py — see blueprint
async def test_duplicate_review_is_duplicate(backend): ...
async def test_stale_revision_rejected(backend): ...
async def test_model_id_filter_before_top_k(backend): ...
async def test_imported_rows_survive_delete_expired(backend): ...
async def test_lexical_search_without_embeddings(backend): ...
def test_full_matrix_writes_report(tmp_path): ...   # PARROT_SPIKE_FULL=1 only — 8 spawn processes, 5k/10k, crash matrix
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** — §2 "Durable Storage and Lineage", §2 "Feedback Migration", §3 rows G2/M2/M5, §4 integration tests, §6 C5, §7 Failure Contract
2. **Check dependencies** — none (may run concurrently with S1/S3/S4/M0; touches only its own files and `tmp_path`)
3. **Verify the Codebase Contract** — every anchor above with `grep`/`sed -n`
4. **Update status** in `sdd/tasks/index/memory-dynamics.json` → `"in-progress"`
5. **Implement** from the blueprint; complete every `FILL IN`; keep the prototype in the spike dir
6. **Run the full matrix once**, save the log, fill REPORT.md / metrics.json / amendment.md
7. **Verify** acceptance criteria; the gate passes only on owner/architecture review of `amendment.md`
8. **Move this file** to `sdd/tasks/completed/TASK-3383-s2-concurrent-storage-spike.md`, update the index → `"done"`, fill the Completion Note with the PASS/FAIL summary

---

## Completion Note

**Completed by**: sdd-worker (orchestrated native `sonnet` delivery)
**Date**: 2026-09-18
**Notes**: Full spike delivered and gate report produced. SQLite/WAL backend prototype
(`SQLiteEpisodeBackend`) implements the full `AbstractEpisodeBackend` protocol plus
`apply_review`/`search_text`/`replay`; 8-process spawn-based harness ran the full matrix
(plain writes 5k/10k, duplicate/concurrent review, 3 crash-injection points + replay,
namespace/model_id filter, feedback-import batch) against both the sqlite prototype and
`FAISSBackend`. PASS: zero lost writes at 5k/10k (sqlite), all 3 crash/replay scenarios
converged, feedback-import idempotent. FAIL: p95 `recall_similar` (DB-only) ≈126-257ms vs
the <50ms@5k bar — a disclosed prototype-scaling gap (brute-force cosine over the shared
table, no ANN index), not a correctness bug; flagged as an open M2 decision in
`amendment.md`. FAISS arm lost the majority-to-all of its writes and repeatedly corrupted
its own snapshot under 8-process contention — real, reproducible evidence backing the
"reject FAISS for the review-transaction role" freeze. Fast tests (5 passed, 1 env-gated
skip) verified green post-merge in the feature worktree.
Full REPORT.md/metrics.json/amendment.md: `packages/ai-parrot/tests/memory/dynamics/spikes/s2_storage/`
(mirrored by the orchestrator to `sdd/state/FEAT-571/spikes/s2-concurrent-storage/` for
owner/architecture review — the gate itself is NOT passed until that review happens).

**Deviations from spec**: Task's own "Files to Create / Modify" list originally placed
REPORT.md/metrics.json/amendment.md under `sdd/state/FEAT-571/spikes/s2-concurrent-storage/`;
amended by sdd-worker (2026-09-18, Option A, user-approved) to
`packages/ai-parrot/tests/memory/dynamics/spikes/s2_storage/` because the FEAT-549
sdd-coder engine's fidelity gate unconditionally rejects any coder-committed path under
`sdd/` — confirmed via a real `fidelity_violation` on the coder's first delivery attempt.
No other deviation from the blueprint.

Seat: sonnet (native) · Backend: native · Model: sonnet · Attempts: 1 · Duration: ~2583s ·
Tokens: n/a (native — usage not tracked by the engine)
