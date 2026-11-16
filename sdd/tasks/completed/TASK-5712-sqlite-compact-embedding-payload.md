# TASK-5712: Store SQLite embeddings once and hydrate every read

**Feature**: FEAT-892 — Agent Memory — Unified Integration, User Knowledge and Dynamics
**Spec**: `sdd/specs/agent-memory-mixin.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-5711
**Assigned-to**: unassigned
**Discovered-from**: `issue:36aa7d2b027b`

## Context

SQLite stores each embedding twice: full Python floats in payload JSON and a little-endian float32 BLOB. At 1536
dimensions this creates roughly 32 KB of avoidable JSON per episode and expensive reads. The owner approved float32
round trips on new writes and appending this task to the review-status parent on 2026-11-16.

## Scope

Write payload JSON without embedding and reconstruct it from the existing blob when missing from JSON. Preserve
legacy JSON values, None embeddings, all metadata and scope/order/limit behavior. `store` uses INSERT OR IGNORE;
retrying an existing ID must not rewrite it or compact its payload.
Cover vector search, FTS and LIKE search, recent/ID/matching/failure reads and metadata updates.
Document incremental compatibility; no bulk migration, VACUUM, schema bump or shared model API change.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/memory/episodic/backends/sqlite.py` | MODIFY | Compact writes and common blob hydration across reads |
| `packages/ai-parrot/tests/memory/dynamics/test_sqlite_backend.py` | MODIFY | Compact/legacy/read-path tests and current-layout latency fixture |
| `wiki/memory/memory-dynamics.md` | MODIFY | Float32 and legacy-storage migration note |

## Codebase Contract

Verified in feature worktree at `983470d620b8ffa27527d11169abbbc4be31f95b`; recheck after TASK-5711.

### Verified Imports

- `json`, `struct`, `math`, `datetime`, `pathlib.Path`, `typing.Any` are stdlib; backend already imports the first three.
- `from parrot.memory.episodic.backends.sqlite import SQLiteEpisodeBackend`.
- `from parrot.memory.episodic.models import EpisodicMemory, EpisodeSearchResult, EpisodeOutcome`.
- `pytest` and `numpy` already occur in test_sqlite_backend.py and are installed project dependencies.

### Existing Signatures to Use

- `EpisodicMemory.embedding` has `exclude=True`; `model_dump(mode="json")` excludes it. `to_dict()` restores it for other backends.
- `_pack_embedding` writes float32 and dimension; database columns are `payload TEXT`, `embedding BLOB`, `embedding_dim INTEGER`.
- `SQLiteEpisodeBackend.store(self, episode: EpisodicMemory) -> str` writes JSON at sqlite.py:299 with INSERT OR IGNORE.
- `_payloads_by_id(self, episode_ids: Sequence[str]) -> dict[str, str]` at :1099 is private and used only by vector search.
- Every public read orders/filters in SQL and constructs EpisodicMemory or EpisodeSearchResult from payload data.

### Does NOT Exist

- No separate vector table, payload version marker, or model option to exclude embedding from `to_dict`.
- No database migration is needed: presence of the JSON embedding key distinguishes legacy storage.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/memory/episodic/backends/sqlite.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/memory/dynamics/test_sqlite_backend.py", "action": "MODIFY"},
    {"path": "wiki/memory/memory-dynamics.md", "action": "MODIFY"}
  ],
  "contract_symbols": ["sym:packages/ai-parrot/src/parrot/memory/episodic/backends/sqlite.py#SQLiteEpisodeBackend.store", "sym:packages/ai-parrot/src/parrot/memory/episodic/models.py#EpisodicMemory.to_dict"]
}
```

## Implementation Blueprint

### Steps (in order)

1. Serialize `episode.model_dump(mode="json")` in store, preserving the separate existing blob write.
2. Add one private decoder accepting payload/blob/dimension. Only hydrate when the embedding key is absent; validate
   blob shape/finiteness before building the returned model. Preserve a legacy embedding key including explicit null.
3. Select the blob/dimension alongside payload in every episode read, including FTS and LIKE; use the decoder consistently.
4. Extend the targeted winner fetch to return decoded episode data. Keep metadata updates compact and transactional.
5. Test real stored rows and reopen compatibility; update the ceiling fixture and document precision/incremental migration.

### Backend (MODIFY)

```python
# REPLACE `        payload = json.dumps(episode.to_dict())`; occurrences: 1, sqlite.py:299.
payload = json.dumps(episode.model_dump(mode="json"))

# BEFORE `def _rank_candidates(`; occurrences: 1, sqlite.py:117 before TASK-5711.
def _decode_episode(payload: str, embedding: bytes | None, embedding_dim: int | None) -> dict[str, Any]:
    """Decode episode data, restoring compact embeddings without rewriting legacy values."""
    # FILL IN: legacy-key precedence, None and finite float32 decoding, bounded by AC1–AC4.

# REPLACE `    async def _payloads_by_id(self, episode_ids: Sequence[str]) -> dict[str, str]:`
# occurrences: 1, sqlite.py:1099 before TASK-5711; return decoded dicts and update its sole caller.
```

**Why:** using the existing model serializer avoids changing every backend; one decoder prevents inconsistent read contracts.

### Existing latency tests (MODIFY)

```python
# Within `async def test_vector_search_meets_latency_contract_at_ceiling(tmp_path) -> None:`
# occurrences: 1, test_sqlite_backend.py:581 before TASK-5711.
# FILL IN: build the template using model_dump(mode="json") and update the fixture docstring, bounded by AC5.
```

**Why:** the performance fixture must use the same compact layout as production writes.

### Payload tests (MODIFY, same test module)

```python
# INSERT test cases below `_SCOPE = {"tenant_id": "tenant-a", "agent_id": "agent-a"}`.
# occurrences: 1, test_sqlite_backend.py:447 before TASK-5711.
# Reuse existing _episode fixtures and imports; add pathlib.Path for typed tmp_path arguments if needed.
# FILL IN: typed fixtures and async cases covering AC1–AC5; use temporary databases and actual public read methods.
```

**Why:** public read tests verify persisted layout without coupling to private helpers and remain in the feature test contract.

### Documentation (MODIFY)

```markdown
<!-- INSERT after `### Storage and Durability`; occurrences: 1, memory-dynamics.md:292. -->
SQLite stores new episode embeddings only in its little-endian float32 blob. Reads restore that vector into the
episode model. Legacy JSON embeddings remain readable at their original precision; existing IDs are never rewritten
by store retries. Existing rows retain their storage overhead until a separate explicit migration is performed.
```

**Why:** precision changes and incremental disk savings must be explicit; existing rows are never silently rewritten.

### FILL IN checklist

- [ ] Decoder and every read route, including both text-search branches.
- [ ] New, legacy, None, idempotent-store and metadata-update regressions; inspect stored JSON size.
- [ ] Current-layout latency fixture and compatibility documentation.

## Acceptance Criteria

- [ ] AC1: new payload JSON excludes embedding; its blob retains float32 data/dimension; input episode is unchanged.
- [ ] AC2: all public episode read paths restore float32 embeddings and None values, including after reopen.
- [ ] AC3: legacy rows preserve their JSON vector or explicit null, with no migration or rewrite during configure/read.
- [ ] AC4: metadata update preserves layout; store retries preserve legacy rows without replacing values; scope/order/limits remain.
- [ ] AC5: regression and ceiling latency tests pass; documentation explains precision and gradual storage savings.

## Validation Commands

- `pytest packages/ai-parrot/tests/memory/dynamics/test_sqlite_backend.py -q`

## Test Specification

Compare exact float32 unpacked values, test all seven read routes (including FTS and LIKE), mixed legacy/new rows,
None vectors, metadata updates and reopen. Assert compact JSON size does not grow with vector dimension. Preserve
store/recall integration as additional regression checks. Tests must close resources on failure.

## Agent Instructions

Wait for TASK-5711, which modifies the same backend and test file. Reverify anchors, implement in the feature worktree,
run task validation with that checkout's source on PYTHONPATH, Black and Ruff. Keep logs in artifacts/logs. Commit
scoped files and finalize using structured evidence through `parrot sdd task finalize`.

## Completion Note

- Task: TASK-5712
- Feature: agent-memory-mixin
- Implementation SHA: b4ff591f3b4a2bc47780d6a6b8c52f2210356489
- Closed at (UTC): 2026-11-16T11:20:13+00:00
- Fix commits: none

| Metric | Value |
|---|---|
| validation_refs | 1 |
| fix_commits | 0 |
| seat_summary | Seat: gpt-5.6-terra · Backend: codex · Model: gpt-5.6-terra · Attempts: 1 · Duration: 464.9s · Tokens: n/a |
