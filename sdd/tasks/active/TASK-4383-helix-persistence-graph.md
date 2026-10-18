# TASK-4383: `HelixPersistence` — GraphIndex graph plane on HelixDB (persist / slice / staleness / load)

**Feature**: FEAT-670 — HelixDB graph provider
**Spec**: `sdd/specs/helixdb-provider.spec.md` (§3 Module 7, first half; §2 data-model mapping; §4 `test_persistence_conformance[helix-memory]`)
**Status**: pending
**Priority**: high
**Estimated effort**: L
**Depends-on**: TASK-4374
**Assigned-to**: unassigned

---

## Context

FEAT-540 (merged on `dev` @ `6fd231dc2`) made every GraphIndex backend a registered
implementation of the structural `GraphPersistence` Protocol
(`graphindex/protocols.py:103`) plus optional capabilities such as `IncrementalPersistence`
(`:156`). Spec §3 M7 adds the HelixDB implementation, one HelixDB **database per tenant**
(resolved Q7: `gi_<tenant>`), built only on the `parrot.knowledge.helix` package
(TASK-4372 settings/errors, TASK-4373 client, TASK-4374 bootstrap + DSL helpers).

M7 is split in two: this task creates `graphindex/persist_helix.py` with the **graph plane**
(`persist_graph`, `replace_document_slice`, `is_stale`, `load_graph`, `close`, the plane schema
and the registry factory `create_helix_persistence`). TASK-4384 adds the **commit protocol**
(`apply_update` / `get_commit` / `list_commits` / `revert_commit`) to the same file. The registry
row is TASK-4392's (M4) — this task registers nothing.

The behavioural reference is `SQLitePersistence` (`graphindex/persist_sqlite.py:139`); the
server-backend reference (per-tenant lock, `seq` ordering) is `ArangoPersistence`
(`graphindex/persist_arango.py:198`).

---

## Scope

- Create `packages/ai-parrot/src/parrot/knowledge/graphindex/persist_helix.py` with:
  - `GRAPHINDEX_PLANE: PlaneSchema` — labels `GNode`, `GFile`, `GCommit`, `GCommitItem`, `Meta` (the two commit
    labels are declared here so the plane bootstraps once; TASK-4384 writes them).
  - `HelixPersistence(settings_factory)` with `close`, `persist_graph`, `replace_document_slice`,
    `is_stale`, `load_graph`, `file_hashes` and the private helpers `_client(ctx)` / node+edge
    (de)serialisers.
  - `async def create_helix_persistence(*, settings_factory, **_) -> HelixPersistence`.
- Store nodes/edges so that `load_graph` rehydrates exactly the `UniversalNode` / `UniversalEdge`
  shapes `SQLitePersistence` returns (skip-and-warn on unknown enum values, `persist_sqlite.py:527-586`).
- Write `packages/ai-parrot/tests/knowledge/graphindex/test_persist_helix.py`: the FEAT-540
  conformance cases that need no commit protocol (`case_slice_atomic_idempotent`,
  `case_missing_store_reads_empty`, `case_errors_propagate`) on `helix-memory`, plus
  round-trip / staleness / tenant-isolation tests.

**NOT in scope**: `apply_update` / `get_commit` / `list_commits` / `revert_commit` and the full
`ALL_CASES` run (TASK-4384); the `GraphBackendSpec` row and `project_options` mapping (TASK-4392);
`export_commits` / `import_commits` (TASK-4393); any edit to `graphindex/backends.py`,
`factory.py`, `loader.py`, `wiki/runtime.py`; embeddings / hybrid / temporal capabilities (not
declared for helixdb).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/graphindex/persist_helix.py` | CREATE | `GRAPHINDEX_PLANE`, `HelixPersistence` graph plane, `create_helix_persistence` |
| `packages/ai-parrot/tests/knowledge/graphindex/test_persist_helix.py` | CREATE | helix-memory conformance subset + round-trip tests |

---

## Codebase Contract (Anti-Hallucination)

Verified 2026-10-16 on `dev` @ `1c239a5ca` (FEAT-540 merged).

### Verified Imports
```python
from parrot.knowledge.graphindex.protocols import edge_key, GraphPersistence, IncrementalPersistence  # protocols.py:12, :103, :156
from parrot.knowledge.graphindex.schema import AssertionMeta, UniversalEdge, UniversalNode           # schema.py:100, :184, :149
from parrot.knowledge.ontology.schema import TenantContext                                          # ontology/schema.py:531
# Created by TASK-4372..4374 (spec §2 "New Public Interfaces" / §3 M1) — re-verify in the worktree before use:
from parrot.knowledge.helix.settings import HelixSettings                       # TASK-4372 (+ HelixSettings.with_database)
from parrot.knowledge.helix.client import HelixClient, open_helix_client, _sdk  # TASK-4373 (_sdk = lazy helixdb module accessor)
from parrot.knowledge.helix.bootstrap import LabelSpec, PlaneSchema, ensure_plane  # TASK-4374
from parrot.knowledge.helix import dsl                                          # TASK-4374: lookup_by_key, upsert_node_entries, find_or_add_edge_entries
from parrot.knowledge.helix.errors import HelixExtraMissing, HelixUnavailable   # TASK-4372
# test-only
from .persistence_conformance import case_errors_propagate, case_missing_store_reads_empty, case_slice_atomic_idempotent  # tests/knowledge/graphindex/persistence_conformance.py:91,115,121 (test_graph_backends.py:23 uses this relative form)
```

### Existing Signatures to Use
```python
# graphindex/protocols.py
def edge_key(source_id: str, target_id: str, kind: str) -> str                    # :12 — "src|dst|kind"
class GraphPersistence(Protocol):                                                  # :103 (runtime_checkable)
    async def persist_graph(self, ctx, nodes, edges) -> dict[str, Any]             # :125
    async def replace_document_slice(self, ctx, document_uri, nodes, edges) -> dict[str, Any]  # :126
    async def load_graph(self, ctx) -> tuple[list[Any], list[Any]]                 # :133
    # apply_update / get_commit / list_commits / revert_commit / close            # :134-152 (commit half → TASK-4384)
class IncrementalPersistence(Protocol):                                            # :156
    async def is_stale(self, ctx, source_uri: str, mtime: float, sha1: str) -> bool

# graphindex/persist_sqlite.py — behavioural reference
class SQLitePersistence:                                                           # :139
    async def persist_graph(...) -> {"nodes_persisted": N, "edges_persisted": M}   # :260 (INSERT OR REPLACE, edges source_uri=None)
    async def replace_document_slice(...) -> {"nodes_replaced": old_count, "edges_replaced": len(edges)}  # :338
        # deletes nodes with source_uri == uri EXCEPT 'odoo-model://%', edges stamped with uri, then orphan edges;
        # new edges stamped with their SOURCE node's source_uri (:410-423)
    async def close(self) -> None                                                  # :460
    async def file_hashes(self, ctx) -> list[tuple[str, str]]                      # :463 sorted by source_uri
    async def is_stale(self, ctx, source_uri, mtime, sha1) -> bool                 # :478 True when unknown / sha1 differs / mtime differs
    async def _upsert_files(self, conn, nodes) -> None                             # :210 (files row per distinct node.source_uri)
    def _row_to_node(row) / _row_to_edge(row)                                      # :527 / :561 skip-and-warn on bad enums
    async def load_graph(self, ctx) -> tuple[list[UniversalNode], list[UniversalEdge]]  # :588 — empty when the db is missing

# graphindex/schema.py
class UniversalNode(BaseModel): node_id, kind: NodeKind, title, source_uri, content_ref, summary, embedding_ref,
                                domain_tags: dict, parent_id, provenance: Provenance, assertion: AssertionMeta|None   # :149-181
class UniversalEdge(BaseModel): source_id, target_id, kind: EdgeKind, provenance, confidence, assertion, domain_tags  # :184-214

# graphindex/persist_arango.py — server-backend precedent
class ArangoPersistence:                       # :198 — per-tenant asyncio.Lock (self._tenant_locks), close() at :218
async def create_arango_persistence(*, graph_store=None, arango_params=None, tenant_ctx=None) -> ArangoPersistence  # :856 (registry factory shape)

# tests/knowledge/graphindex/persistence_conformance.py
async def case_slice_atomic_idempotent(persistence, ctx, *, stores: bool = True) -> None   # :91
async def case_missing_store_reads_empty(persistence, ctx) -> None                         # :115
async def case_errors_propagate(broken, ctx) -> None                                       # :121 — persist_graph must RAISE
# tests/knowledge/graphindex/test_graph_backends.py:31 — ctx = MagicMock(); ctx.tenant_id = "t1"
```

### Does NOT Exist
- ~~`CommitReceipt.seq`~~ — `CommitReceipt` (`schema.py:269-287`) has no `seq` field although the `GraphPersistence` docstring mentions one; `seq` lives only on the stored `GCommit` (TASK-4384).
- ~~An edge unique index in HelixDB~~ — only node indexes (`IndexSpec.node_*`, spec §6); edge identity is enforced by `dsl.find_or_add_edge_entries` inside one batch.
- ~~A `range` field on `LabelSpec`~~ — spec §2 `LabelSpec` has `unique_key`, `equality`, `text_property`, `vector_property_prefix` only; spec §3 M7's "range seq" cannot be declared → `seq` is an `equality` property, ordered with `order_by`.
- ~~`parrot.knowledge.graphindex.persist_helix`~~, ~~`HelixPersistence`~~, ~~`create_helix_persistence`~~ — created here.
- ~~A `helixdb` registry row in `graphindex/backends.py`~~ — TASK-4392; built-in names today are `("sqlite", "null", "postgres", "arangodb")` (`test_graph_backends.py:38`).
- ~~`helixdb` / `helixdb_uniffi` importable in the shared `.venv`~~ — not installed on 2026-10-16 (`ModuleNotFoundError`); helix tests skip until TASK-4373's dev-group wheels are synced.
- ~~Fixtures from `tests/knowledge/helix/conftest.py` in this test directory~~ — conftest fixtures are not shared across sibling directories; define a local `settings_factory` fixture.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/graphindex/persist_helix.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/knowledge/graphindex/test_persist_helix.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/graphindex/protocols.py#edge_key",
    "sym:packages/ai-parrot/src/parrot/knowledge/graphindex/protocols.py#GraphPersistence",
    "sym:packages/ai-parrot/src/parrot/knowledge/graphindex/protocols.py#IncrementalPersistence",
    "sym:packages/ai-parrot/src/parrot/knowledge/graphindex/schema.py#UniversalNode",
    "sym:packages/ai-parrot/src/parrot/knowledge/graphindex/schema.py#UniversalEdge",
    "sym:packages/ai-parrot/src/parrot/knowledge/graphindex/schema.py#AssertionMeta",
    "sym:packages/ai-parrot/src/parrot/knowledge/graphindex/persist_sqlite.py#SQLitePersistence",
    "sym:packages/ai-parrot/src/parrot/knowledge/graphindex/persist_arango.py#create_arango_persistence",
    "sym:packages/ai-parrot/src/parrot/knowledge/ontology/schema.py#TenantContext"
  ]
}
```

---

## Implementation Notes

### Spec drift found at task time (follow the REAL code)
- **Factory option name**: spec §2 table says `required_options=("settings",)`, §3 M4 says `("settings_factory",)`. The constructor takes a `settings_factory` (§3 M7); this task uses **`settings_factory`** and TASK-4392's row must declare `required_options=("settings_factory",)`.
- **`load_graph` on a fresh tenant**: FEAT-540 requires "missing tenant store reads as empty, never as an error". In server mode the database `gi_<tenant>` may not exist yet; `_client(ctx)` bootstraps lazily, so the first read creates an empty plane — acceptable (SQLite returns `[]` without creating; the observable contract is identical).
- **`persist_graph` atomicity**: the Protocol only requires atomicity for `apply_update` and `replace_document_slice`. `persist_graph` may be split into several write batches (HelixDB admits ≤ 8 MiB queued text per write, spec §7) — `replace_document_slice` must stay ONE batch.

### Data-model mapping (normative for this file and TASK-4384/4393)
- `GNode`: unique `node_id`; equality `kind`, `source_uri`, `parent_id`; text property `search_text` = `title + "\n" + summary` (mirror of `nodes_fts(title, summary)`); every other `UniversalNode` field stored as a top-level property; `domain_tags` and `assertion` as JSON strings (same encoding as `_tags_json` / `_assertion_json`, `persist_sqlite.py:122-131`).
- Edges: HelixDB edge labelled with `kind.value`, properties `edge_key` (= `edge_key(src, dst, kind)`), `provenance`, `confidence`, `source_uri`, `assertion` (JSON), `domain_tags` (JSON). Always written through `dsl.find_or_add_edge_entries` (multigraph — never a bare `add_e`).
- `GFile`: unique `source_uri`; `mtime`, `sha1`, `indexed_at`.
- `GCommit` (unique `commit_id`; equality `run_id`, `agent_id`, `seq`) and `GCommitItem` (unique `item_id` = `f"{commit_id}|{item_type}|{item_key}"`; equality `commit_id`, `item_key`) — declared only.
- `Meta`: unique `key` (bootstrap writes `schema_version`; TASK-4384 adds `gi_commit_seq`).

### Key Constraints
- Async throughout; `self.logger = logging.getLogger(__name__)`; Google docstrings; 120 columns.
- **Never import `helixdb` at module top** — the module must import without the extra (the registry imports it lazily, and `HelixExtraMissing` is raised by `open_helix_client`). Prefer the `parrot.knowledge.helix.dsl` builders; for any other DSL op (`g`, `read_batch`, `write_batch`, `Predicate`, `BatchCondition`, `drop`, `value_map` …) call the lazy accessor `parrot.knowledge.helix.client._sdk()` (TASK-4373 `client.py`, used by TASK-4374's `dsl.py`) inside the function.
- No `httpx` import (TID251 is exempted only for `helix/client.py`).
- One `HelixClient` per tenant, opened lazily under a per-tenant `asyncio.Lock`; `ensure_plane(client, GRAPHINDEX_PLANE)` once per client; `close()` closes every client and is idempotent.
- Backend errors propagate (`HelixUnavailable`, `HelixWriteRejected`, driver errors) — never swallowed into empty results.

### References in Codebase
- `graphindex/persist_sqlite.py:260-460, 527-620` — semantics to mirror.
- `graphindex/persist_arango.py:198-240, 856-888` — lock + factory shape.

---

## Implementation Blueprint

### Steps (in order)
1. Read the TASK-4372..4374 modules in the worktree and confirm the names in Verified Imports (`HelixClient.read/write`, `ensure_plane`, `LabelSpec`, `PlaneSchema`, `dsl.*`) — *why*: they were spec skeletons when this task was written.
2. Write `persist_helix.py` from the block below and fill the markers — *why*: the method set is the FEAT-540 graph half; TASK-4384 appends the commit half above `create_helix_persistence`.
3. Write the test module; run it with the embedded wheel installed — *why*: the conformance subset is the acceptance gate.
4. `ruff check --fix` both files; run Validation Commands.

### `packages/ai-parrot/src/parrot/knowledge/graphindex/persist_helix.py` (CREATE)
```python
"""HelixDB persistence backend for GraphIndex (FEAT-670 M7).

One HelixDB database per tenant (``gi_<tenant>``, resolved Q7). Satisfies FEAT-540's
``GraphPersistence`` + ``IncrementalPersistence`` structurally; ``SQLitePersistence`` is the
behavioural reference. The commit protocol lives in the second half of this class (TASK-4384).
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Callable, Optional

import orjson

from parrot.knowledge.graphindex.protocols import edge_key
from parrot.knowledge.graphindex.schema import AssertionMeta, UniversalEdge, UniversalNode
from parrot.knowledge.helix import dsl
from parrot.knowledge.helix.bootstrap import LabelSpec, PlaneSchema, ensure_plane
from parrot.knowledge.helix.client import HelixClient, open_helix_client
from parrot.knowledge.helix.settings import HelixSettings
from parrot.knowledge.ontology.schema import TenantContext

logger = logging.getLogger(__name__)

GRAPHINDEX_PLANE = PlaneSchema(
    plane="graphindex",
    schema_version="1",
    labels=[
        LabelSpec(label="GNode", unique_key="node_id", equality=["kind", "source_uri", "parent_id"],
                  text_property="search_text"),
        LabelSpec(label="GFile", unique_key="source_uri"),
        LabelSpec(label="GCommit", unique_key="commit_id", equality=["run_id", "agent_id", "seq"]),
        LabelSpec(label="GCommitItem", unique_key="item_id", equality=["commit_id", "item_key"]),
        LabelSpec(label="Meta", unique_key="key"),
    ],
    edge_labels=["*"],
)
_CANONICAL_PREFIX = "odoo-model://"  # never deleted by replace_document_slice (persist_sqlite.py:351)


def _now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string (SQLite format)."""
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")


def _node_props(node: UniversalNode) -> dict[str, Any]:
    """Serialise a node to GNode properties (JSON for dict/assertion, search_text for BM25)."""
    # FILL IN: every UniversalNode field; domain_tags/assertion JSON-encoded exactly like persist_sqlite._tags_json /
    #   _assertion_json; search_text = f"{node.title}\n{node.summary or ''}" — bounded by load_graph round-trip test
    raise NotImplementedError


def _props_to_node(props: dict[str, Any]) -> Optional[UniversalNode]:
    """Rehydrate a GNode; ``None`` + warning on unknown enum values (persist_sqlite.py:527 parity)."""
    # FILL IN: inverse of _node_props, try/except → logger.warning + None — bounded by skip-and-warn parity
    raise NotImplementedError


def _edge_props(edge: UniversalEdge, source_uri: Optional[str]) -> dict[str, Any]:
    """Serialise an edge to HelixDB edge properties keyed by ``edge_key``."""
    return {
        "edge_key": edge_key(edge.source_id, edge.target_id, edge.kind.value),
        "provenance": edge.provenance.value,
        "confidence": edge.confidence,
        "source_uri": source_uri,
        "assertion": None if edge.assertion is None
        else orjson.dumps(edge.assertion.model_dump(exclude_none=True)).decode(),
        "domain_tags": orjson.dumps(edge.domain_tags).decode(),
    }


def _props_to_edge(src: str, dst: str, kind: str, props: dict[str, Any]) -> Optional[UniversalEdge]:
    """Rehydrate an edge; ``None`` + warning on unknown enum values."""
    try:
        raw = props.get("assertion")
        return UniversalEdge(
            source_id=src, target_id=dst, kind=kind, provenance=props.get("provenance", "extracted"),
            confidence=props.get("confidence"), assertion=AssertionMeta(**orjson.loads(raw)) if raw else None,
            domain_tags=orjson.loads(props["domain_tags"]) if props.get("domain_tags") else {},
        )
    except Exception as exc:  # noqa: BLE001 — skip-and-warn, like SQLitePersistence._row_to_edge
        logger.warning("HelixPersistence: skipping unreadable edge (%r → %r): %s", src, dst, exc)
        return None


class HelixPersistence:
    """GraphIndex persistence on HelixDB; one database per tenant (resolved Q7)."""

    def __init__(self, settings_factory: Callable[[TenantContext], HelixSettings]) -> None:
        self._settings_factory = settings_factory
        self._clients: dict[str, HelixClient] = {}
        self._tenant_locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self.logger = logger

    async def _client(self, ctx: TenantContext) -> HelixClient:
        """Open (once per tenant) the tenant client and bootstrap GRAPHINDEX_PLANE."""
        tenant = ctx.tenant_id
        if tenant not in self._clients:
            async with self._tenant_locks[f"open:{tenant}"]:
                if tenant not in self._clients:
                    client = await open_helix_client(self._settings_factory(ctx))
                    await ensure_plane(client, GRAPHINDEX_PLANE)
                    self._clients[tenant] = client
        return self._clients[tenant]

    async def close(self) -> None:
        """Close every tenant client (idempotent)."""
        clients, self._clients = list(self._clients.values()), {}
        for client in clients:
            await client.close()

    async def persist_graph(self, ctx: TenantContext, nodes: list[UniversalNode],
                            edges: list[UniversalEdge]) -> dict[str, Any]:
        """Upsert all nodes/edges (+ GFile rows); returns ``{"nodes_persisted", "edges_persisted"}``."""
        client = await self._client(ctx)
        # FILL IN: write batches of dsl.upsert_node_entries (GNode, GFile per distinct source_uri with
        #   mtime/sha1 from node.domain_tags like SQLitePersistence._upsert_files) + dsl.find_or_add_edge_entries
        #   (source_uri=None, as SQLite :312); split into several batches when text exceeds ~4 MiB — bounded by spec §7
        raise NotImplementedError

    async def replace_document_slice(self, ctx: TenantContext, document_uri: str, nodes: list[UniversalNode],
                                     edges: list[UniversalEdge]) -> dict[str, Any]:
        """ONE write batch: drop the document's GNodes (except canonical) and stamped edges, then add."""
        client = await self._client(ctx)
        async with self._tenant_locks[ctx.tenant_id]:
            # FILL IN: count old nodes (read); one write batch: drop GNode where source_uri == document_uri unless it
            #   starts with _CANONICAL_PREFIX (drop removes incident edges), drop edges whose source_uri == document_uri,
            #   upsert nodes, find-or-add edges stamped with their source node's source_uri — bounded by
            #   case_slice_atomic_idempotent; return {"nodes_replaced": old_count, "edges_replaced": len(edges)}
            raise NotImplementedError

    async def file_hashes(self, ctx: TenantContext) -> list[tuple[str, str]]:
        """Return every ``(source_uri, sha1)`` GFile pair sorted by ``source_uri``."""
        # FILL IN: read all GFile value_map(["source_uri", "sha1"]), sort — bounded by persist_sqlite.py:463 parity
        raise NotImplementedError

    async def is_stale(self, ctx: TenantContext, source_uri: str, mtime: float, sha1: str) -> bool:
        """True when the file is unknown or its stored ``sha1``/``mtime`` differ (persist_sqlite.py:478 parity)."""
        client = await self._client(ctx)
        # FILL IN: dsl.lookup_by_key("GFile", "source_uri", source_uri) → row; None ⇒ True; compare sha1 then mtime
        raise NotImplementedError

    async def load_graph(self, ctx: TenantContext) -> tuple[list[UniversalNode], list[UniversalEdge]]:
        """Return the CURRENT graph; ``([], [])`` for a tenant that never wrote."""
        client = await self._client(ctx)
        # FILL IN: read every GNode (value_map) → _props_to_node; read every edge with its endpoints' node_id and
        #   label → _props_to_edge; drop None rows — bounded by case_missing_store_reads_empty + round-trip test
        raise NotImplementedError


async def create_helix_persistence(
    *, settings_factory: Callable[[TenantContext], HelixSettings], **_: Any
) -> HelixPersistence:
    """``GraphBackendSpec`` factory target (row added by TASK-4392).

    Raises:
        HelixExtraMissing: When the ``helix-db`` SDK is absent (raised on first client open).
    """
    return HelixPersistence(settings_factory)
```
**Why this shape**: the per-tenant client cache + lock mirrors `ArangoPersistence` and keeps one
database per tenant (Q7). `create_helix_persistence` is the **last** definition in the file —
TASK-4384 inserts the commit methods into the class right above it and TASK-4393 the history
transfer methods; do not move it. Node/edge serialisation is shared by both later tasks, so its
encoding (JSON strings, `edge_key` property) must not change.

### `packages/ai-parrot/tests/knowledge/graphindex/test_persist_helix.py` (CREATE)
See Test Specification; the module starts with
`pytest.importorskip("helixdb_uniffi", reason="helix-db-embedded not installed (ai-parrot[helixdb-embedded])")`.

### FILL IN checklist
- [ ] `_node_props` / `_props_to_node` — encoding parity with SQLite; bounded by round-trip test
- [ ] `persist_graph` — batch splitting; bounded by spec §7 admission limits
- [ ] `replace_document_slice` — one batch, canonical nodes kept; bounded by `case_slice_atomic_idempotent`
- [ ] `file_hashes`, `is_stale`, `load_graph` — SQLite parity; bounded by AC-3/AC-4 below

---

## Acceptance Criteria

- [ ] **AC-1** (spec AC4, partial) `case_slice_atomic_idempotent`, `case_missing_store_reads_empty` and `case_errors_propagate` pass on `helix-memory`.
- [ ] **AC-2** `persist_graph` → `load_graph` round-trips every `UniversalNode` / `UniversalEdge` field (including `assertion`, `domain_tags`, `confidence`); a duplicate edge in one call yields one stored edge.
- [ ] **AC-3** `is_stale` is `True` for unknown files and for changed `sha1` / `mtime`, `False` after `persist_graph` with matching values; `file_hashes` is sorted.
- [ ] **AC-4** Tenants are isolated: two `ctx.tenant_id`s → two databases (`settings_factory` called per tenant), neither sees the other's nodes.
- [ ] **AC-5** `isinstance(HelixPersistence(...), IncrementalPersistence)` is `True`; `import parrot.knowledge.graphindex.persist_helix` succeeds without `helixdb` installed.
- [ ] **AC-6** `ruff check packages/ai-parrot/src/parrot/knowledge/graphindex/persist_helix.py` is clean (no `httpx`, no top-level `helixdb`).

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/graphindex/test_persist_helix.py -q`
- `pytest packages/ai-parrot/tests/knowledge/graphindex/test_graph_backends.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/graphindex/test_persist_helix.py
from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import MagicMock

import pytest

from parrot.knowledge.graphindex.persist_helix import HelixPersistence
from parrot.knowledge.graphindex.protocols import IncrementalPersistence
from parrot.knowledge.helix.settings import HelixMode, HelixSettings

from .persistence_conformance import case_errors_propagate, case_missing_store_reads_empty, case_slice_atomic_idempotent

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
@pytest.mark.parametrize("case", [case_slice_atomic_idempotent, case_missing_store_reads_empty])
async def test_conformance_graph_half(case, settings_factory) -> None:
    p = HelixPersistence(settings_factory)
    try:
        await case(p, _ctx())
    finally:
        await p.close()


@pytest.mark.asyncio
async def test_errors_propagate() -> None:
    # FILL IN: a settings_factory producing an unusable target (e.g. SERVER mode at an unreachable URL with
    #   probe_retries=1, probe_timeout_s=0.1) so persist_graph raises HelixUnavailable
    ...


@pytest.mark.asyncio
async def test_round_trip_all_fields(settings_factory) -> None: ...      # AC-2
@pytest.mark.asyncio
async def test_is_stale_and_file_hashes(settings_factory) -> None: ...   # AC-3
@pytest.mark.asyncio
async def test_tenant_isolation(settings_factory) -> None: ...           # AC-4
def test_incremental_protocol(settings_factory) -> None:
    assert isinstance(HelixPersistence(settings_factory), IncrementalPersistence)
```

---

## Agent Instructions

1. **Work in the feature worktree** (`python -m scripts.sdd.ensure_worktree --slug helixdb-provider --feature-id FEAT-670`).
2. **Read the spec** §3 M7 and §2 data-model mapping.
3. **Check dependencies** — TASK-4374 must be `done` in `sdd/tasks/index/helixdb-provider.json`.
4. **Verify the Codebase Contract** — especially the TASK-4372..4374 names; fix this file's contract first if they differ.
5. Set status `in-progress` in the per-spec index and commit only that file.
6. **Implement** from the blueprint; never rename `HelixPersistence`, `create_helix_persistence`, `GRAPHINDEX_PLANE` or move `create_helix_persistence` from the end of the file.
7. Run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src` (worktree rule); a skip because `helixdb_uniffi` is absent is NOT a pass — install the dev-group wheels from TASK-4373 in a task-local environment, or close as `done-with-issues` stating the skip.
8. Commit only the two listed files; close with `scripts/sdd/close_task.sh TASK-4383 helixdb-provider verified`.
9. Fill in the Completion Note and commit the SDD state.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**:
