# TASK-4384: `HelixPersistence` commit protocol — `apply_update` / `get_commit` / `list_commits` / `revert_commit`

**Feature**: FEAT-670 — HelixDB graph provider
**Spec**: `sdd/specs/helixdb-provider.spec.md` (§3 Module 7, second half; AC4, AC21; §4 `test_persistence_conformance[helix-memory]`, `test_commit_seq_and_edge_key_atomic`)
**Status**: pending
**Priority**: high
**Estimated effort**: L
**Depends-on**: TASK-4383
**Assigned-to**: unassigned

---

## Context

TASK-4383 created `graphindex/persist_helix.py` with the graph plane. This task adds the
**durable agent-memory commit protocol** that `GraphPublisher` drives, honouring FEAT-540's
`GraphPersistence` semantics (`graphindex/protocols.py:103-123`): atomic `apply_update`,
strictly monotonic per-tenant `seq` allocated inside the write, `edge_key` identity, pre-images
including the incident edges of a removed node, revert refused when a later commit touched the
same item key, errors propagate. Spec §3 M7 marks this module **not delegation-eligible**:
the revert ordering over one batch is the algorithmic piece.

After this task `HelixPersistence` satisfies `GraphPersistence` structurally and passes the
whole FEAT-540 conformance suite (`ALL_CASES`) on `helix-memory`.

---

## Scope

- Add to `HelixPersistence` (inside the class, right above `create_helix_persistence`):
  `apply_update`, `get_commit`, `list_commits`, `revert_commit` and the private helpers
  `_next_seq_entries` / `_capture_preimages` / `_node_prior` / `_edge_prior`.
- Allocate `seq` from the `Meta` node `gi_commit_seq` with a **compare-and-set** inside the same
  write batch as the graph change (bounded retry on a lost race).
- Store pre-images in the **canonical SQLite row shape** (see Implementation Notes) so commit
  history is portable across backends (TASK-4393 export/import, TASK-4394 migrate).
- Write `packages/ai-parrot/tests/knowledge/graphindex/test_commit_protocol_helix.py`:
  `ALL_CASES` on `helix-memory`, protocol `isinstance` checks, SQLite-shape parity of
  `get_commit` / `list_commits`, and the live `test_commit_seq_and_edge_key_atomic` (AC21).

**NOT in scope**: `export_commits` / `import_commits` (TASK-4393); the registry row with
`capabilities=("incremental", "history")` (TASK-4392); `GraphPublisher` / `backends.py` edits;
any change to the graph-plane methods TASK-4383 wrote except a shared helper it needs.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/graphindex/persist_helix.py` | MODIFY | commit protocol methods inside `HelixPersistence` |
| `packages/ai-parrot/tests/knowledge/graphindex/test_commit_protocol_helix.py` | CREATE | full conformance + shape parity + live seq/edge race |

---

## Codebase Contract (Anti-Hallucination)

Verified 2026-10-16 on `dev` @ `1c239a5ca`.

### Verified Imports
```python
from parrot.knowledge.graphindex.protocols import GraphPersistence, IncrementalPersistence, edge_key  # protocols.py:103, :156, :12
from parrot.knowledge.graphindex.schema import CommitReceipt, GraphUpdate          # schema.py:269, :233
from parrot.knowledge.graphindex.persist_sqlite import SQLitePersistence            # persist_sqlite.py:139 (parity oracle in tests)
from .persistence_conformance import ALL_CASES                                      # tests/knowledge/graphindex/persistence_conformance.py:136
# Created by TASK-4383 / TASK-4372..4374 — re-verify in the worktree:
from parrot.knowledge.graphindex.persist_helix import HelixPersistence, GRAPHINDEX_PLANE
from parrot.knowledge.helix import dsl          # lookup_by_key, upsert_node_entries, find_or_add_edge_entries
from parrot.knowledge.helix.errors import HelixWriteRejected
```

### Existing Signatures to Use
```python
# graphindex/protocols.py:103 GraphPersistence (runtime_checkable) — commit half
async def apply_update(self, ctx, update) -> Any                                        # :134
async def get_commit(self, ctx, commit_id: str) -> dict[str, Any] | None               # :135
async def list_commits(self, ctx, *, run_id: str | None = None, agent_id: str | None = None, limit: int = 50)  # :136-143
async def revert_commit(self, ctx, commit_id: str, *, agent_id: str, run_id: str | None = None) -> Any        # :144-151

# graphindex/schema.py
class GraphUpdate(BaseModel):   # :233 — nodes, edges, removed_edges: list[tuple[str,str,str]], removed_nodes: list[str],
                                #        agent_id: str, run_id, asserted_by: str, source, reason, op: str = "publish"
class CommitReceipt(BaseModel): # :269 — commit_id, op, node_ids, edge_keys: list[tuple[str,str,str]], committed_at, warnings

# graphindex/persist_sqlite.py — the reference semantics
async def apply_update(self, ctx, update) -> CommitReceipt      # :622-776 — commit_id = uuid4().hex[:16]; items:
    # ("node", node_id) per update.nodes, ("node_removed", node_id) per removed_nodes, then incident edges of removed
    # nodes are added to removed_edge_set; ("edge"|"edge_removed", edge_key) per triple; prior = full row dict or None;
    # receipt.node_ids = nodes + removed_nodes; edge_keys = edges + sorted(removed_edge_set)
async def get_commit(self, ctx, commit_id) -> dict | None       # :778 — graph_commits row + payload (decoded JSON)
    # + items [{item_type, item_key, prior}] where prior is the RAW JSON TEXT (string) or None
async def list_commits(self, ctx, run_id=None, agent_id=None, limit=50) -> list[dict]   # :807 — columns commit_id, op,
    # agent_id, run_id, asserted_by, reason, committed_at, reverted_at; newest first; [] when the tenant db is missing
async def revert_commit(self, ctx, commit_id) -> dict           # :846 — NO agent_id parameter; returns
    # {"error": ...} (unknown / already reverted / no items / {"error", "conflicts": [...]})
    # or {"status": "reverted", "commit_id", "restored", "deleted"}; stamps reverted_at, does NOT create a new commit
# nodes columns (prior shape): node_id, kind, title, source_uri, parent_id, summary, content_ref, embedding_ref,
#   provenance, domain_tags (JSON text), assertion (JSON text)                           # persist_sqlite.py:50-62
# edges columns (prior shape): source_id, target_id, kind, provenance, confidence, source_uri, assertion   # :67-76

# graphindex/persist_arango.py — server precedent for seq ordering
async def _next_seq(self, ctx) -> int                           # :465 (max seq + 1, under the tenant lock)
async def revert_commit(self, ctx, commit_id) -> dict           # :759-853 — conflict = other non-reverted commit with seq > this_seq

# tests/knowledge/graphindex/persistence_conformance.py
ALL_CASES = [case_apply_and_revert, case_seq_monotonic, case_edge_key_identity, case_incident_edge_preimages,
             case_revert_conflict, case_slice_atomic_idempotent, case_missing_store_reads_empty]      # :136-144
# NOTE: every case calls persistence.revert_commit(ctx, commit_id) WITHOUT agent_id (:42, :74, :85)
```

### Does NOT Exist
- ~~`CommitReceipt.seq`~~ — no such field (`schema.py:282-287`); `seq` is stored on `GCommit` only.
- ~~A `seq` column in SQLite `graph_commits`~~ — SQLite orders by implicit `rowid` (`persist_sqlite.py:886-893`).
- ~~A revert that writes a new commit~~ — SQLite and Arango stamp `reverted_at` on the original; the Protocol docstring line "revert is itself a new commit" is not what any backend or the conformance suite does.
- ~~Arithmetic / increment ops in the HelixDB DSL~~ — not in the spec §6 op list; `seq` is computed in Python and guarded by a conditional entry.
- ~~`HelixPersistence.export_commits` / `import_commits`~~ — TASK-4393.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/graphindex/persist_helix.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/knowledge/graphindex/test_commit_protocol_helix.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/graphindex/protocols.py#GraphPersistence",
    "sym:packages/ai-parrot/src/parrot/knowledge/graphindex/protocols.py#IncrementalPersistence",
    "sym:packages/ai-parrot/src/parrot/knowledge/graphindex/protocols.py#edge_key",
    "sym:packages/ai-parrot/src/parrot/knowledge/graphindex/schema.py#GraphUpdate",
    "sym:packages/ai-parrot/src/parrot/knowledge/graphindex/schema.py#CommitReceipt",
    "sym:packages/ai-parrot/src/parrot/knowledge/graphindex/persist_sqlite.py#SQLitePersistence",
    "sym:packages/ai-parrot/src/parrot/knowledge/graphindex/persist_arango.py#ArangoPersistence"
  ]
}
```

---

## Implementation Notes

### Spec drift found at task time (follow the REAL code)
- **`revert_commit` returns a `dict`**, not a `CommitReceipt` (spec §3 M7 skeleton): SQLite (`:846`), Arango (`:759`), Null (`backends.py`) and the conformance cases (`"error" in result`) all use the dict shape.
- **`revert_commit(ctx, commit_id, *, agent_id: str = "", run_id: str | None = None)`** — the Protocol declares `agent_id` keyword-only without a default, but every conformance case omits it; `NullPersistence` already uses `agent_id: str = ""`. Use the default.
- **`list_commits` takes `run_id` / `agent_id` keywords**, not `**filters` (spec skeleton).
- **`seq` exposure**: `get_commit` / `list_commits` rows include `seq` (SQLite rows do not); callers comparing across backends compare the SQLite key set.

### Canonical pre-image shape (cross-task decision — TASK-4393/4394 rely on it)
`GCommitItem.prior` is a **JSON string** (or `None`) whose object has exactly the SQLite column set:
nodes → `node_id, kind, title, source_uri, parent_id, summary, content_ref, embedding_ref, provenance, domain_tags, assertion`
(`domain_tags` / `assertion` as JSON text); edges → `source_id, target_id, kind, provenance, confidence, source_uri, assertion`.
Edge `domain_tags` is not part of the SQLite edge row; a restored Helix edge gets `{}`. This makes a
history imported from SQLite revertible on HelixDB and vice-versa.

### Algorithm (decided here)
- **apply_update** (under `self._tenant_locks[ctx.tenant_id]`):
  1. read phase (read batch): current node props for `update.nodes ∪ update.removed_nodes`; incident edges of each removed node; current edge props for every `(src, dst, kind)` in `update.edges` and `removed_edges ∪ incident`; current `Meta gi_commit_seq` value `N` (absent ⇒ 0).
  2. build items exactly like SQLite (`:640-680`), deduplicated on `(item_type, item_key)`; dedupe `update.edges` by `edge_key` (conformance `case_edge_key_identity` passes the same edge twice).
  3. ONE write batch: conditional entry on `Meta gi_commit_seq == N` (or `var_empty` when `N == 0`) guarding **every** entry: set `gi_commit_seq = N + 1`, upsert nodes, find-or-add edges, drop removed edges, drop removed nodes, add `GCommit(seq=N+1, …, payload=update.model_dump_json(), reverted_at=None)` and its `GCommitItem`s (each with `commit_id`, `item_key`, `item_type`, `prior`, `seq`).
  4. if the condition failed (another client won `N+1`) re-run from step 1, at most 5 attempts, then raise `HelixWriteRejected("gi_commit_seq")`.
- **revert_commit**: same lock; read `GCommit` (unknown / already reverted ⇒ error dict); read its items (none ⇒ error dict); conflict = any `GCommitItem` with the same `item_key`, a different `commit_id`, whose `GCommit` has `seq > this.seq` and `reverted_at is None` ⇒ `{"error": "revert_commit: later commits touched the same items", "conflicts": sorted(...)}`. Otherwise ONE write batch in this order: (a) delete edges whose prior is `None`, (b) delete nodes whose prior is `None`, (c) restore nodes from prior, (d) restore edges from prior, (e) set `reverted_at` on the `GCommit`. Nodes before edges because a HelixDB edge needs both endpoints.
- Messages and dict keys match SQLite byte-for-byte (`persist_sqlite.py:866-972`).

### Key Constraints
- No new top-level `helixdb` import; `orjson` for JSON; `self.logger.info` once per commit / revert (SQLite wording with `HelixPersistence.` prefix).
- Never retry a write that was *rejected* (`HelixWriteRejected` from the client) — only the lost-CAS case retries (spec §7 "do not retry a write automatically unless the full request is safe to replay").

### References in Codebase
- `graphindex/persist_sqlite.py:622-972` — semantics and messages.
- `graphindex/persist_arango.py:465-475, 759-853` — `seq`-based conflict detection.

---

## Implementation Blueprint

### Steps (in order)
1. Re-read `persist_helix.py` as TASK-4383 left it; confirm the anchor below occurs once — *why*: the methods go inside the class.
2. Insert the block; fill the markers — *why*: algorithm fixed in Implementation Notes.
3. Write `test_commit_protocol_helix.py`; run `ALL_CASES` on helix-memory — *why*: FEAT-540 conformance is AC4.
4. `ruff check --fix`; run Validation Commands.

### `packages/ai-parrot/src/parrot/knowledge/graphindex/persist_helix.py` (MODIFY)
```python
# occurrences: expected 1 once TASK-4383 lands (verify: grep -c -F 'async def create_helix_persistence(' packages/ai-parrot/src/parrot/knowledge/graphindex/persist_helix.py)
# BEFORE — insert immediately above the module-level line `async def create_helix_persistence(` (still inside the class body)
    # -- commit protocol (FEAT-540 GraphPersistence semantics) ----------------------------------------
    _SEQ_KEY = "gi_commit_seq"
    _SEQ_RETRIES = 5

    @staticmethod
    def _node_prior(props: Optional[dict[str, Any]]) -> Optional[str]:
        """Encode a GNode as the canonical SQLite ``nodes`` row JSON (or ``None`` when absent)."""
        if props is None:
            return None
        cols = ("node_id", "kind", "title", "source_uri", "parent_id", "summary", "content_ref",
                "embedding_ref", "provenance", "domain_tags", "assertion")
        return orjson.dumps({c: props.get(c) for c in cols}).decode()

    @staticmethod
    def _edge_prior(src: str, dst: str, kind: str, props: Optional[dict[str, Any]]) -> Optional[str]:
        """Encode an edge as the canonical SQLite ``edges`` row JSON (or ``None`` when absent)."""
        if props is None:
            return None
        return orjson.dumps({"source_id": src, "target_id": dst, "kind": kind, "provenance": props.get("provenance"),
                             "confidence": props.get("confidence"), "source_uri": props.get("source_uri"),
                             "assertion": props.get("assertion")}).decode()

    async def apply_update(self, ctx: TenantContext, update: GraphUpdate) -> CommitReceipt:
        """Apply ``update`` + record GCommit/GCommitItems in ONE batch, ``seq`` CAS-allocated (spec §3 M7)."""
        client = await self._client(ctx)
        commit_id = uuid.uuid4().hex[:16]
        committed_at = _now_iso()
        async with self._tenant_locks[ctx.tenant_id]:
            for attempt in range(self._SEQ_RETRIES):
                # FILL IN: steps 1-3 of "Algorithm" — read phase, items (SQLite order + dedupe), one guarded write
                #   batch; on a lost CAS `continue`, else break — bounded by case_* in ALL_CASES + AC21
                raise NotImplementedError
            else:
                raise HelixWriteRejected(f"{self._SEQ_KEY}: lost {self._SEQ_RETRIES} seq races")
        self.logger.info("HelixPersistence.apply_update: commit %s (%s) — %d nodes, %d edges, %d removed",
                         commit_id, update.op, len(update.nodes), len(update.edges), len(update.removed_edges))
        # FILL IN: return CommitReceipt(commit_id, op, node_ids=nodes+removed_nodes,
        #   edge_keys=edges+sorted(removed_edge_set), committed_at, warnings=[]) — SQLite :770-776 parity
        raise NotImplementedError

    async def get_commit(self, ctx: TenantContext, commit_id: str) -> Optional[dict[str, Any]]:
        """GCommit props (+ decoded ``payload``) and ``items`` [{item_type, item_key, prior(JSON text)}]; None if unknown."""
        # FILL IN: lookup_by_key("GCommit", "commit_id", …); items via GCommitItem where commit_id — SQLite :778 shape
        raise NotImplementedError

    async def list_commits(self, ctx: TenantContext, *, run_id: Optional[str] = None,
                           agent_id: Optional[str] = None, limit: int = 50) -> list[dict[str, Any]]:
        """Commit summaries (no payload), newest first by ``seq``; ``[]`` for a tenant that never committed."""
        # FILL IN: GCommit filtered by run_id/agent_id, order_by seq desc, limit; keys = SQLite :838 columns + seq
        raise NotImplementedError

    async def revert_commit(self, ctx: TenantContext, commit_id: str, *, agent_id: str = "",
                            run_id: Optional[str] = None) -> dict[str, Any]:
        """Restore a commit's pre-images in ONE batch; refused when a later non-reverted commit touched an item."""
        client = await self._client(ctx)
        async with self._tenant_locks[ctx.tenant_id]:
            # FILL IN: "Algorithm → revert_commit": error dicts, seq-based conflicts, ordered batch (a)-(e),
            #   then return {"status": "reverted", "commit_id", "restored", "deleted"} — bounded by
            #   case_apply_and_revert / case_incident_edge_preimages / case_revert_conflict
            raise NotImplementedError

```
Also add `import uuid` and `from parrot.knowledge.graphindex.schema import CommitReceipt, GraphUpdate` to the
existing import block (`grep -c -F 'from parrot.knowledge.graphindex.schema import AssertionMeta, UniversalEdge, UniversalNode'` → expected 1; extend that line), and `from parrot.knowledge.helix.errors import HelixWriteRejected`.

**Why**: `seq` must be allocated inside the same atomic write as the graph change (FEAT-540
contract, spec AC21) and HelixDB has no increment op, so a guarded conditional entry on the
observed counter is the only atomic form; the per-tenant lock removes in-process races so the
retry only fires on cross-process contention. The pre-image shape is SQLite's so history is
backend-portable.

### `packages/ai-parrot/tests/knowledge/graphindex/test_commit_protocol_helix.py` (CREATE)
See Test Specification.

### FILL IN checklist
- [ ] `apply_update` — read phase, item building, guarded batch, retry; bounded by `ALL_CASES` + AC21
- [ ] `get_commit` / `list_commits` — SQLite row shapes + `seq`; bounded by AC-3
- [ ] `revert_commit` — conflict rule, ordered single batch; bounded by `case_revert_conflict`, `case_incident_edge_preimages`

---

## Acceptance Criteria

- [ ] **AC-1** (spec AC4) every case in `ALL_CASES` passes on `helix-memory`.
- [ ] **AC-2** `isinstance(p, GraphPersistence) and isinstance(p, IncrementalPersistence)` for a `HelixPersistence`.
- [ ] **AC-3** For the same update sequence, `get_commit` / `list_commits` on HelixDB and on `SQLitePersistence` return the same keys (Helix adds `seq`), the same item `(item_type, item_key)` sets, priors that decode to equal dicts, and the same error dicts from `revert_commit`.
- [ ] **AC-4** `seq` values of three successive commits are `1, 2, 3` and `Meta gi_commit_seq == 3`.
- [ ] **AC-5** (spec AC21, live) `test_commit_seq_and_edge_key_atomic`: two `HelixPersistence` instances (two clients) on the same server database issue concurrent `apply_update`s ⇒ distinct `seq`s, no duplicate `edge_key`; node removal records incident edges and revert restores them. Skips without a reachable `HELIXDB_URL`.
- [ ] **AC-6** `ruff check` clean on the modified file.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/graphindex/test_commit_protocol_helix.py -q`
- `pytest packages/ai-parrot/tests/knowledge/graphindex/test_persist_helix.py -q`
- `pytest packages/ai-parrot/tests/knowledge/graphindex/test_graph_backends.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/graphindex/test_commit_protocol_helix.py
from __future__ import annotations

import asyncio
import os
import socket
import uuid
from typing import Any
from unittest.mock import MagicMock
from urllib.parse import urlparse

import pytest

from parrot.knowledge.graphindex.persist_helix import HelixPersistence
from parrot.knowledge.graphindex.persist_sqlite import SQLitePersistence
from parrot.knowledge.graphindex.protocols import GraphPersistence, IncrementalPersistence
from parrot.knowledge.helix.settings import HelixMode, HelixSettings, resolve_helix_settings

from .persistence_conformance import ALL_CASES

pytest.importorskip("helixdb_uniffi", reason="helix-db-embedded not installed (ai-parrot[helixdb-embedded])")


def _ctx(tenant: str = "t1") -> Any:
    ctx = MagicMock()
    ctx.tenant_id = tenant
    return ctx


@pytest.fixture
def settings_factory():
    run = uuid.uuid4().hex[:8]
    return lambda ctx: HelixSettings(mode=HelixMode.MEMORY, database=f"gi_{ctx.tenant_id}_{run}")


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ALL_CASES, ids=lambda c: c.__name__)
async def test_helix_memory_conformance(case, settings_factory) -> None:
    p = HelixPersistence(settings_factory)
    try:
        await case(p, _ctx())
    finally:
        await p.close()


def test_protocols(settings_factory) -> None:
    p = HelixPersistence(settings_factory)
    assert isinstance(p, GraphPersistence) and isinstance(p, IncrementalPersistence)


@pytest.mark.asyncio
async def test_commit_shapes_match_sqlite(settings_factory, tmp_path) -> None:
    # FILL IN: same scripted updates on SQLitePersistence(tmp_path) and HelixPersistence; compare get_commit /
    #   list_commits key sets (minus "seq"), item sets, decoded priors, revert error dicts — AC-3
    ...


@pytest.mark.asyncio
async def test_seq_counter(settings_factory) -> None: ...   # AC-4


def _reachable(url: str | None) -> bool:
    if not url:
        return False
    parsed = urlparse(url)
    try:
        with socket.create_connection((parsed.hostname, parsed.port or 80), timeout=1):
            return True
    except OSError:
        return False


@pytest.mark.live
@pytest.mark.asyncio
@pytest.mark.skipif(not _reachable(os.getenv("HELIXDB_URL")), reason="HelixDB live fixture unavailable: set HELIXDB_URL")
async def test_commit_seq_and_edge_key_atomic() -> None:
    # FILL IN: database = f"gi_live_{uuid4().hex[:8]}"; two HelixPersistence(lambda ctx: resolve_helix_settings(database=…));
    #   asyncio.gather 10 apply_update each, half sharing one edge; assert distinct seqs (list_commits) and one stored
    #   edge per edge_key (load_graph); remove a node, revert, edges restored — AC-5
    ...
```

---

## Agent Instructions

1. Work in the feature worktree (`python -m scripts.sdd.ensure_worktree --slug helixdb-provider --feature-id FEAT-670`).
2. Read spec §3 M7, AC4, AC21 and `persist_sqlite.py:622-972` before writing.
3. TASK-4383 must be `done` in `sdd/tasks/index/helixdb-provider.json`.
4. Verify the Codebase Contract (the anchor in `persist_helix.py` and the TASK-4372..4374 names).
5. Status `in-progress` → commit the index only.
6. Implement; never change TASK-4383's serialisation helpers' encoding (history portability depends on it).
7. Run Validation Commands with `PYTHONPATH=packages/ai-parrot/src`; a skip because `helixdb_uniffi` is absent is not a pass (see TASK-4383 rule 7). The live test is expected to skip without `HELIXDB_URL` — record that in the Completion Note.
8. Commit only the listed files; `scripts/sdd/close_task.sh TASK-4384 helixdb-provider verified`.
9. Fill in the Completion Note; commit the SDD state.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**:
