# TASK-2766: Graph commit protocol on real transactions

**Feature**: FEAT-520 — GraphIndex Postgres Backend
**Spec**: `sdd/specs/graphindex-postgres-backend.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2765
**Assigned-to**: unassigned

---

## Context

Module 3 of FEAT-520. Both existing backends implement the graph commit
protocol (`apply_update`/`get_commit`/`list_commits`/`revert_commit`) —
`GraphPublisher` depends on it for durable, revertible agent memory. On
Postgres, pre-images + commit row + mutations become ONE transaction
(atomicity by the engine, not by asyncio.Lock/WAL). Behavioral parity bar:
`tests/knowledge/graphindex/test_persist_commit_protocol.py`.

---

## Scope

- Add to `PostgresPersistence` (same file as TASK-2765):
  - `apply_update(ctx, update: GraphUpdate) -> CommitReceipt` — inside one
    transaction: capture pre-images of every touched node/edge (including
    implicit incident edges of `removed_nodes`) into `commit_items`, insert
    the commit row (payload jsonb, `seq` from IDENTITY), then apply writes:
    node/edge upserts via the TASK-2765 close-and-insert helpers, removals =
    close validity (tombstone convention on this backend is "validity
    closed", replacing Arango soft-delete / SQLite DELETE).
  - `get_commit(ctx, commit_id) -> Optional[dict]` — commit fields + payload
    + items (same public shape as siblings: no storage internals).
  - `list_commits(ctx, run_id=None, agent_id=None, limit=50) -> list[dict]` —
    newest first by `seq`, payload omitted, `[]` on missing/unreachable.
  - `revert_commit(ctx, commit_id) -> dict` — restore pre-images; refuse when
    a later non-reverted commit (higher `seq`) touched any same item key;
    created-by-commit items (no pre-image) are removed so `load_graph` never
    sees them; stamp `reverted_at`. Same `{"status": "reverted"}` /
    `{"error": ...}` result shapes as the siblings.
- Port `test_persist_commit_protocol.py` scenarios to Postgres (live-gated).

**NOT in scope**: temporal query API (TASK-2767), toolkit exposure (TASK-2773).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/graphindex/persist_postgres.py` | MODIFY | commit protocol methods |
| `packages/ai-parrot/tests/knowledge/graphindex/test_commit_protocol_postgres.py` | CREATE | ported behavioral suite, live-gated |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.graphindex.schema import (
    GraphUpdate,     # schema.py:233 — fields incl. op, nodes, edges, removed_nodes,
                     #   removed_edges, agent_id, run_id, asserted_by (:263), reason
    CommitReceipt,   # schema.py:269 — commit_id, op, node_ids, edge_keys, committed_at, warnings
)
```

### Existing Signatures to MIRROR
```python
# packages/ai-parrot/src/parrot/knowledge/graphindex/persist.py (Arango impl — behavior reference)
async def apply_update(self, ctx, update: GraphUpdate) -> CommitReceipt
    # - pre-images recorded BEFORE mutations
    # - edge item_key = f"{source_id}|{target_id}|{kind}"  (_edge_key helper)
    # - endpoint kinds resolved for edges whose endpoints are not in the update
async def get_commit(self, ctx, commit_id) -> Optional[dict[str, Any]]
async def list_commits(self, ctx, run_id=None, agent_id=None, limit=50) -> list[dict]
async def revert_commit(self, ctx, commit_id) -> dict[str, Any]
    # refusal rule: later non-reverted commit with same item_key → {"error": ...}

# packages/ai-parrot/src/parrot/knowledge/graphindex/persist_sqlite.py
async def apply_update(...)   # :608 — SQLite equivalent, rowid ordering
async def get_commit(...)     # :785
async def list_commits(...)   # :817
async def revert_commit(...)  # :856
# graph_commits DDL :82 / graph_commit_items :96 — column names to keep parity with
```

### Does NOT Exist
- ~~a per-tenant `asyncio.Lock` requirement on Postgres~~ — the transaction IS
  the serialization for atomicity. Keep a lock ONLY if the ported tests
  require strict `seq` monotonicity under concurrency (check the test
  expectations first; if needed, `SELECT ... FOR UPDATE` on the version-stamp
  row is the Postgres-native equivalent — do not copy the asyncio.Lock
  blindly).
- ~~`gi_commits` / `gi_commit_items` table names here~~ — those are the
  ARANGO collection names (persist.py); this backend uses
  `graphindex.commits` / `graphindex.commit_items` (TASK-2764 DDL).
- ~~hard DELETE of removed nodes~~ — removal closes validity (tombstone by
  range), so temporal reads (TASK-2767) still see history.

---

## Implementation Notes

### Key Constraints
- Commit row + items + mutations in ONE `async with conn.transaction():` —
  a mid-apply crash rolls back everything (stronger than the Arango
  "visible in audit trail" compromise; document this deviation in the
  docstring).
- `seq` comes from the IDENTITY column — no manual max()+1.
- Result dict shapes byte-compatible with the siblings (GraphPublisher
  consumes them).

### References in Codebase
- `tests/knowledge/graphindex/test_persist_commit_protocol.py` — the parity
  bar; port its scenarios 1:1.
- `parrot/knowledge/graphindex/publish.py` — `GraphPublisher`, the consumer.

---

## Acceptance Criteria

- [ ] All ported commit-protocol scenarios green on Postgres (live-gated).
- [ ] Mid-apply failure rolls back commit + items + mutations (test with a
      forced constraint violation).
- [ ] Revert refusal on later-commit conflict matches sibling behavior (test).
- [ ] `GraphPublisher` smoke test over `PostgresPersistence` passes.
- [ ] `ruff check` clean; zero SQLAlchemy.

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/graphindex/test_commit_protocol_postgres.py
# Port tests/knowledge/graphindex/test_persist_commit_protocol.py scenarios, plus:
async def test_apply_update_atomic_rollback(pg_persistence, ctx): ...
async def test_removed_node_closes_validity_not_delete(pg_persistence, ctx): ...
```

---

## Agent Instructions

1. Read spec §3 Module 3 and the sibling implementations first.
2. Verify contract references; check the parity test's concurrency
   expectations before deciding on locking.
3. Update index status; move to completed + note when done.

---

## Completion Note

*(Agent fills this in when done)*
