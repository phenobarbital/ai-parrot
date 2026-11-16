# TASK-5706: SQLite vector scoring off the event loop and targeted scoped reads

**Feature**: FEAT-892 — Agent Memory — Unified Integration, User Knowledge and Dynamics
**Spec**: `sdd/specs/agent-memory-mixin.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-5661, TASK-5665, TASK-5679, TASK-5702
**Assigned-to**: claude (sdd-fix)
**Discovered-from**: `issue:2bb5faf7fe99`

## Context

Feature review of FEAT-892 (`issue:2bb5faf7fe99`, severity major). Two read paths of the SQLite episodic backend do
work that grows with the whole scope and run it on the event loop:

- `SQLiteEpisodeBackend.search_similar` selects `payload` for every candidate (the payload JSON carries the embedding,
  about 32 KB per row at 1536 dimensions), unpacks each blob with `struct` and scores it with the pure-Python `_cosine`.
  Measured on this branch at the D6 ceiling (5,000 rows, 1536 dimensions): p50 2,517 ms per search, against the AC13
  contract of p95 ≤ 150 ms, and the whole time is spent inside the event loop.
- `EpisodicMemoryStore._resolve_episodes`, `get_failure_warnings`, `get_user_preferences`, `get_room_context` and
  `_fallback_lexical_search` call `count()` and then `get_recent(limit=count)`, deserializing the whole scope
  (2,391 ms for the same 5,000 rows) to resolve at most 64 ids or one category.

No test measures latency, so AC13 has no automated evidence.

## Scope

- Score candidates with `numpy` in a worker thread (`asyncio.to_thread`); read ids and embedding blobs first and load
  the payload only for the winning rows.
- Two optional read capabilities on `SQLiteEpisodeBackend`: `get_by_ids` and `get_recent_matching` (category, failure
  and keyset-page predicates evaluated in SQL).
- `EpisodicMemoryStore` uses those capabilities when the backend has them and keeps today's full-scope read otherwise.
- Tests: scoring parity with the removed helpers, the two capabilities, the store routes, and a latency test at the
  5,000-row ceiling.

**NOT in scope:** the ceiling warning of D7 and the other minor findings (`issue:5fb1a338c719`, TASK-5707); the same
capabilities for the pgvector, Redis or FAISS backends (they keep the full-scope read); `AbstractEpisodeBackend`
(`backends/abstract.py`), which another task is editing; an index or a vector extension (D6 forbids one);
`dynamics/feedback.py`, which has the same read pattern and is owned by TASK-5704; unrelated refactoring.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/memory/episodic/backends/sqlite.py` | MODIFY | `_rank_candidates`, two-phase `search_similar`, `get_by_ids`, `get_recent_matching` |
| `packages/ai-parrot/src/parrot/memory/episodic/store.py` | MODIFY | Targeted reads on the five routes, with the full-scope fallback |
| `packages/ai-parrot/tests/memory/dynamics/test_sqlite_backend.py` | MODIFY | Scoring parity, capabilities, off-loop dispatch, latency at the ceiling |
| `packages/ai-parrot/tests/memory/dynamics/test_store_reviews.py` | MODIFY | Store routes use targeted reads and match the fallback |

## Codebase Contract (Anti-Hallucination)

### Verified Imports

- `import numpy as np` — `numpy` reaches core through `pandas>=2.0.0` and `faiss-cpu>=1.9.0`
  (`packages/ai-parrot/pyproject.toml`, core `dependencies`); `backends/faiss.py:15` already imports it at module level.
- `from parrot.memory.episodic.backends.sqlite import SQLiteEpisodeBackend`
- `from parrot.memory.episodic.store import EpisodicMemoryStore`
- `from parrot.memory.episodic.models import EpisodeCategory, EpisodeSearchResult, EpisodicMemory, MemoryNamespace`

### Existing Signatures to Use

- `episodes(episode_id TEXT PRIMARY KEY, tenant_id, agent_id, user_id, session_id, room_id, crew_id, model_id,
  created_at TEXT, expires_at, is_failure INTEGER, payload TEXT, embedding BLOB, embedding_dim INTEGER)`; the blob is
  little-endian float32 (`_pack_embedding`, `backends/sqlite.py:93`).
- `store()` writes `created_at = episode.created_at.isoformat()` and `payload = json.dumps(episode.to_dict())`;
  `EpisodicMemory.to_dict()` adds `embedding` and writes `category` as its enum value (`episodic/models.py:150`).
- `SQLiteEpisodeBackend._build_where(namespace_filter, include_failures_only=False) -> tuple[str, list[Any]]`; a `None`
  value becomes `IS NULL` (`backends/sqlite.py:916`).
- `_cosine` and `_unpack_embedding` are used only by `search_similar` (verified:
  `grep -rn "_cosine\|_unpack_embedding" packages/ai-parrot`), so both are removed with it.
- Every read orders `created_at DESC, episode_id DESC`.
- `EpisodicMemoryStore._episode_matches_namespace(episode, namespace)` is the exact-scope authority and stays.
- The store detects optional backend capabilities with `getattr` + `callable` (`_resolve_dynamics_states`,
  `store.py:646`).

### Does NOT Exist

- `get_by_ids` / `get_recent_matching` on `AbstractEpisodeBackend`, pgvector, Redis or FAISS: they are optional
  capabilities, never required by the protocol.
- A `category` column: the category lives in the payload and is filtered with `json_extract(payload, '$.category')`.
- An offset or cursor argument on `get_recent`.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/memory/episodic/backends/sqlite.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/memory/episodic/store.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/memory/dynamics/test_sqlite_backend.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/memory/dynamics/test_store_reviews.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/memory/episodic/backends/sqlite.py#SQLiteEpisodeBackend.search_similar",
    "sym:packages/ai-parrot/src/parrot/memory/episodic/store.py#EpisodicMemoryStore._resolve_episodes"
  ]
}
```

## Implementation Notes

### Key Constraints

- Results must not change: same validation errors (`stored embedding has an invalid shape`,
  `stored embedding values must be finite`), a dimension mismatch and a zero norm score 0.0, ties keep the newest row
  first, scores are computed in float64.
- A winning row deleted between the two reads is skipped, never an error.
- The store keeps its Python exact-scope check and its `_exclude_retracted` / ranking steps; only the read changes.
- `get_room_context` without categories keeps the cache-aware full-scope read: there is no predicate to push down.

## Implementation Blueprint

### Steps (in order)

1. `sqlite.py`: add `import numpy as np` and the constants; replace `_unpack_embedding` and `_cosine` with
   `_rank_candidates` — because scoring must be one vectorized call that a worker thread can run.
2. `sqlite.py`: rewrite `search_similar` as ids + blobs → `asyncio.to_thread(_rank_candidates, …)` → payloads of the
   winners — because the payload of a losing row is never needed.
3. `sqlite.py`: add `get_by_ids` and `get_recent_matching` after `get_recent`.
4. `store.py`: use the capabilities in the five routes behind `getattr`, keeping the existing read as the fallback.
5. Tests, then the Validation Commands.

### `packages/ai-parrot/src/parrot/memory/episodic/backends/sqlite.py` (MODIFY)

```python
# AFTER — insert below `import aiosqlite` (verified: sqlite.py:15)
# occurrences: 1 (verified: grep -c 'import aiosqlite' sqlite.py)
import numpy as np

# AFTER — insert below `_STATE_READ_BATCH = 500` (verified: sqlite.py:33)
# occurrences: 1
_ID_READ_BATCH = 500
_SCORE_BLOCK_ROWS = 1_024

# REPLACES `_unpack_embedding` and `_cosine` (verified: sqlite.py:114, sqlite.py:135; one occurrence each)
def _rank_candidates(
    embedding: list[float],
    candidates: list[tuple[bytes, int]],
    score_threshold: float,
    top_k: int,
) -> list[tuple[int, float]]:
    """Return ``(candidate index, cosine score)`` for the best candidates, best first."""
    # FILL IN: validate every blob, score matching dimensions in float64 blocks of _SCORE_BLOCK_ROWS,
    # stable descending order — bounded by Key Constraints.

# REPLACES the body of `    async def search_similar(` (verified: sqlite.py:712, occurrences: 1)
#   SELECT episode_id, embedding, embedding_dim ... LIMIT vector_ceiling
#   ranked = await asyncio.to_thread(_rank_candidates, embedding, candidates, score_threshold, top_k)
#   payloads = await self._payloads_by_id([...])

# AFTER — insert below the body of `    async def get_recent(` (verified: sqlite.py:819, occurrences: 1)
async def get_by_ids(self, episode_ids: Sequence[str], namespace_filter: dict[str, Any]) -> list[EpisodicMemory]: ...

async def get_recent_matching(
    self,
    namespace_filter: dict[str, Any],
    *,
    limit: int | None = None,
    categories: Sequence[str] | None = None,
    failures_only: bool = False,
    before_id: str | None = None,
) -> list[EpisodicMemory]: ...
```

**Why**: the blob read is 30 MB at the ceiling and the payload read was 160 MB; scoring in `numpy` releases the GIL, so
a thread keeps the loop responsive without a process pool.

### `packages/ai-parrot/src/parrot/memory/episodic/store.py` (MODIFY)

```python
# REPLACES the read in `    async def _resolve_episodes(` (verified: store.py:670, occurrences: 1)
get_by_ids = getattr(self._backend, "get_by_ids", None)

# REPLACES the read in `    async def _fallback_lexical_search(` (verified: store.py:355, occurrences: 1)
#   page through get_recent_matching(limit=_LEXICAL_PAGE_SIZE, failures_only=..., before_id=<last id of the previous page>) until top_k matches

# `count = await self._backend.count(namespace.build_filter())`
# occurrences: 3 (verified: store.py:988, 1040, 1062)
# FILL IN: disambiguate by enclosing method — get_failure_warnings (failures_only=True),
# get_user_preferences (categories=[USER_PREFERENCE]), get_room_context (categories given, else unchanged).
```

**Why**: each route needs a subset the backend can select; the fallback keeps other backends working unchanged.

### FILL IN checklist

- [ ] `_rank_candidates` body — bounded by Key Constraints.
- [ ] `_payloads_by_id` helper — batches of `_ID_READ_BATCH`.
- [ ] The three `count` sites — bounded by the comment above.

## Acceptance Criteria

- [ ] `search_similar` returns the same episodes, order and scores as before for matching, mismatched-dimension and
      zero vectors, and raises the same errors for a malformed or non-finite stored vector.
- [ ] Scoring is dispatched through `asyncio.to_thread`; the payload is read only for returned rows.
- [ ] At 5,000 rows of 1536 dimensions, `search_similar` p95 ≤ 150 ms (D6, AC13).
- [ ] `get_by_ids` and `get_recent_matching` never return a row outside the namespace filter.
- [ ] With the SQLite backend, the five store routes issue no `count()` + full-scope `get_recent`, and return the same
      result as a backend without the capabilities.

## Validation Commands

- `pytest packages/ai-parrot/tests/memory/dynamics/test_sqlite_backend.py packages/ai-parrot/tests/memory/dynamics/test_store_reviews.py packages/ai-parrot/tests/memory/dynamics/test_recall.py -q`

## Test Specification

- `test_vector_scoring_matches_reference_semantics`: mismatched dimension, zero vector, ties, threshold and `top_k`.
- `test_vector_scoring_rejects_malformed_and_non_finite_vectors`: both stored-vector errors survive.
- `test_vector_search_scores_off_the_event_loop_and_reads_winning_payloads_only`: dispatch and payload reads.
- `test_vector_search_meets_latency_contract_at_ceiling`: AC13 at 5,000 × 1536.
- `test_get_by_ids_and_recent_matching_filter_in_sql`: scope, category, failure, limit and keyset page.
- `test_store_routes_use_targeted_reads_and_match_full_scope_fallback`: the five routes.

## Agent Instructions

1. Verify the Codebase Contract against the source before editing.
2. Touch only the files listed above.
3. Run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`.
4. Commit code with `feat(agent-memory-mixin): TASK-5706 — SQLite vector scoring off the event loop and targeted scoped reads`,
   then close the task with `scripts/sdd/close_task.sh`.

## Completion Note

- Task: TASK-5706
- Feature: agent-memory-mixin
- Implementation SHA: 1f03f469a4
- Closed at (UTC): 2026-11-16T10:01:24+00:00
- Resolves: `issue:2bb5faf7fe99`
- Validation: `test_sqlite_backend.py`, `test_store_reviews.py` and `test_recall.py` pass (31 tests), and so do the 404
  tests under `packages/ai-parrot/tests/memory` plus `tests/test_episodic_memory.py`, in a clean tree of the commit.
- Measured on this branch at the D6 ceiling (5,000 rows, 1536 dimensions, payloads as `store()` writes them, 40 runs):
  `search_similar` p50 2,517 ms before, p50 78 ms and p95 81 ms after, against the AC13 contract of p95 ≤ 150 ms.
  Resolving 64 ids went from 2,416 ms (`get_recent(limit=count)`) to 35 ms (`get_by_ids`).
- Deviation from the blueprint as filed: the page cursor is `before_id: str` and not `before: tuple[datetime, str]`. The
  backend compares against the stored `(created_at, episode_id)` of that row, so the page does not depend on a datetime
  surviving the payload round trip. The blueprint above is corrected.
- Scores accumulate in float64 directly from the float32 blobs (`einsum(..., dtype=float64)`), which is exact to the old
  implementation within 1e-15 and avoids a widened copy of the candidates.
- The latency test measures up to three rounds of 20 searches and passes when one round meets the budget, so a concurrent
  load on the machine does not fail it. It writes a 190 MB database under `tmp_path` and deletes it when it ends.
- Not done here, by scope: `get_room_context` without categories still reads the whole scope (there is no predicate to
  select by); pgvector, Redis and FAISS keep the full-scope read; `dynamics/feedback.py` has the same
  `count()` + `get_recent(limit=count)` pattern and belongs to TASK-5704.
- Found while measuring, not fixed: the payload JSON duplicates the embedding as text (about 32 KB per row at 1536
  dimensions, next to a 6 KB blob). It is about half of the remaining search time, because SQLite walks the payload's
  overflow pages to reach the blob, and it is why a full-scope read costs 2.4 s. Filed as a separate ledger issue.
- `started_at` was written together with this note; no separate start commit was made, to keep index conflicts with the
  two other sessions working on FEAT-892 to a minimum.
- Implemented by Claude through `/sdd-fix`, by hand (no coder seat).
