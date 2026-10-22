# TASK-4387: HelixOntologyGraphStore — GraphDocumentStore surface + factory

**Feature**: FEAT-670 — HelixDB graph provider
**Spec**: `sdd/specs/helixdb-provider.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-4374
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 8 (G4, AC7). FEAT-540 (merged) split the ontology store into two ABCs in
`ontology/contracts.py`: `GraphDocumentStore` (collection / document / edge CRUD) and
`OntologyTraversalStore` (typed traversals). This task creates `ontology/helix_graph_store.py` with
`HelixOntologyGraphStore` implementing the **document/edge half** on HelixDB (one database per tenant,
`ont_<tenant>`), plus `create_helix_ontology_store` — the factory TASK-4392 registers as
`register_ontology_backend("helixdb", …)`. The traversal half (`is_reachable`, `get_document_by_id`,
`find_by_field`, `search_by_name`, `execute_pattern`, `execute_query`) is TASK-4388, in the same file.

This class also stores the data the **authorization** checks traverse (`reports_to` edges, `department`
fields) — so tenant isolation and the storage conventions fixed here are security-relevant.

---

## Scope

- Create `ontology/helix_graph_store.py`:
  - `HelixOntologyGraphStore(GraphDocumentStore, OntologyTraversalStore)` with `dialect: ClassVar[str] = "helix"`,
    `__init__(settings_factory)`, a per-database client cache, `close()`.
  - All 14 `GraphDocumentStore` methods, semantics mirroring `ArangoOntologyGraphStore`.
  - The six `OntologyTraversalStore` methods as `raise NotImplementedError("TASK-4388")` placeholders **only so the
    class is instantiable** — TASK-4388 replaces them (they are abstract; without bodies the ABC cannot be built).
  - `ontology_database_name(tenant_id)` + `default_ontology_settings(ctx)` + `create_helix_ontology_store(...)`.
- Tests `tests/knowledge/ontology/test_helix_graph_store.py` (InMemory mode).

**NOT in scope**: typed traversals (TASK-4388); the registration row in `contracts.py` / `helix/__init__.py`
(TASK-4392); editing `graph_store.py`, `authorization.py`, `entity_resolver.py`, `mixin.py`,
`graphindex/loader.py`, `parrot_tools/*` (spec M8 — FEAT-540 already migrated callers).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/ontology/helix_graph_store.py` | CREATE | HelixOntologyGraphStore (document/edge surface) + factory |
| `packages/ai-parrot/tests/knowledge/ontology/test_helix_graph_store.py` | CREATE | contract tests on InMemory |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.ontology.contracts import GraphDocumentStore, OntologyTraversalStore, DynamicQuery  # verified: contracts.py:26,106,17
from parrot.knowledge.ontology.graph_store import UpsertResult            # verified: graph_store.py:24 (inserted/updated/unchanged ints)
from parrot.knowledge.ontology.schema import TenantContext, TraversalPattern   # verified: schema.py:531 (tenant_id, arango_db, pgvector_schema, ontology), :261
# created by TASK-4372/4373/4374 — not on dev when written; verify with grep on pickup:
from parrot.knowledge.helix.settings import HelixSettings, HelixMode, resolve_helix_settings   # TASK-4372 (HelixSettings.with_database exists)
from parrot.knowledge.helix.client import HelixClient, open_helix_client                     # TASK-4373 (read(batch,*,query_name), write(batch,*,query_name), close())
from parrot.knowledge.helix.bootstrap import PlaneSchema, LabelSpec, ensure_plane             # TASK-4374
from parrot.knowledge.helix import dsl as helix_dsl                                          # TASK-4374: lookup_by_key, upsert_node_entries, find_or_add_edge_entries, text_search
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/ontology/contracts.py — GraphDocumentStore (ABC) :26
async def initialize_tenant(self, ctx: TenantContext) -> None                                              # :30
async def ensure_collection(self, ctx: TenantContext, name: str, edge: bool = False) -> None               # :34
async def upsert_nodes(self, ctx, collection: str, nodes: list[dict], key_field: str) -> UpsertResult     # :38
async def create_edges(self, ctx, edge_collection: str, edges: list[dict]) -> int                         # :48
async def get_all_nodes(self, ctx, collection: str) -> list[dict]                                         # :52
async def soft_delete_nodes(self, ctx, collection: str, keys: list[str]) -> None                          # :56
async def get_document(self, ctx, collection: str, key: str) -> dict | None                               # :60
async def upsert_document(self, ctx, collection: str, doc: dict) -> None                                  # :64
async def insert_document(self, ctx, collection: str, doc: dict) -> None                                  # :68
async def remove_document(self, ctx, collection: str, key: str) -> bool                                   # :72
async def query_documents(self, ctx, collection: str, filters: dict | None = None, sort_desc: str | None = None, limit: int | None = None) -> list[dict]  # :76
async def get_all_edges(self, ctx, collection: str) -> list[dict]                                         # :87
async def edges_incident(self, ctx, collection: str, node_id: str) -> list[dict]                          # :91
async def remove_edge_by_triple(self, ctx, collection: str, source_id: str, target_id: str, kind: str) -> bool  # :95
# OntologyTraversalStore (ABC) :106 — dialect: ClassVar[str] :109; abstract is_reachable :112, get_document_by_id :125,
#   find_by_field :129, search_by_name :142, execute_pattern :155, execute_query :165
# register_ontology_backend(name, factory) :172; create_ontology_graph_store(backend, **options) :182 → factory(**options)

# packages/ai-parrot/src/parrot/knowledge/ontology/graph_store.py — reference semantics (ArangoOntologyGraphStore :62, dialect "aql" :78)
#   upsert_nodes :513 — match on key_field; INSERT sets _key = doc[key_field], _active = true; UPDATE sets _active = true;
#     counts inserted / updated / unchanged (OLD == NEW)
#   create_edges :616 — dedupe on (_from, _to); returns number newly created
#   get_all_nodes :693 — `FILTER doc._active != false`
#   soft_delete_nodes :722 — UPDATE {_key} WITH {_active: false}
#   ensure_collection :775; get_document :803 (by _key); upsert_document :827 (full replace by _key, doc must include _key)
#   insert_document :855 (auto _key when absent); remove_document :874 (hard remove, True when removed)
#   query_documents :902 — ANDed equality filters, `SORT doc.<sort_desc> DESC`, LIMIT
#   get_all_edges :943; edges_incident :969 — `e.source_id == @node_id OR e.target_id == @node_id`
#   remove_edge_by_triple :996 — `e.source_id == @src AND e.target_id == @tgt AND e.kind == @kind`
#   initialize_tenant :102 — creates collections per ctx.ontology.entities[*].collection / relations[*].edge_collection,
#     key_field indexes, and ctx.ontology.search_views (ArangoSearch)
# schema.py EntityDef.collection / key_field (str | None) :56-58; RelationDef.edge_collection :~130;
#   MergedOntology.search_views (dict)
# authorization.py:47 _tenant_context builds a TenantContext with an EMPTY ontology and arango_db f"{tenant}_ontology"
#   → database selection must depend on ctx.tenant_id only, never on ctx.ontology or ctx.arango_db.
```

### Does NOT Exist
- ~~`parrot.knowledge.ontology.helix_graph_store`~~ — created here.
- ~~`OntologyGraphStore`~~ in `graph_store.py` — renamed `ArangoOntologyGraphStore` by FEAT-540 (spec §6 is stale).
- ~~`ArangoOntologyGraphStore.execute_traversal`~~ — removed by FEAT-540.
- ~~an `upsert` op in the HelixDB DSL~~ — use `helix_dsl.upsert_node_entries` (conditional entries).
- ~~HelixDB dangling edges~~ — `add_e` needs both endpoint nodes; HelixDB is a multigraph (dedupe yourself).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/ontology/helix_graph_store.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/knowledge/ontology/test_helix_graph_store.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/ontology/contracts.py#GraphDocumentStore",
    "sym:packages/ai-parrot/src/parrot/knowledge/ontology/contracts.py#OntologyTraversalStore",
    "sym:packages/ai-parrot/src/parrot/knowledge/ontology/contracts.py#DynamicQuery",
    "sym:packages/ai-parrot/src/parrot/knowledge/ontology/graph_store.py#UpsertResult",
    "sym:packages/ai-parrot/src/parrot/knowledge/ontology/graph_store.py#ArangoOntologyGraphStore",
    "sym:packages/ai-parrot/src/parrot/knowledge/ontology/schema.py#TenantContext"
  ]
}
```

---

## Implementation Notes

### Storage conventions (decided here — TASK-4386 / 4388 rely on them)
- **Database per tenant**: `ont_<tenant_id>`; `tenant_id` must match `^[A-Za-z0-9_]{1,64}$` else `ValueError`
  (no cross-tenant aliasing via crafted ids). Derived from `ctx.tenant_id` only.
- **Vertices**: HelixDB label = collection name (`_IDENT`-checked); properties = the document's top-level fields
  plus `_key`, `_id = f"{collection}/{_key}"`, `_active` (bool) and `search_text` (lower-cased space-join of the
  top-level `str` values, truncated to 64 KiB — HelixDB per-document text limit) for `search_by_name`.
  Nested dict/list values: JSON-encode under the same property only if the SDK rejects them — FILL IN after
  checking the wheel; document the choice.
- **Edges**: label = edge collection; properties = the edge document (incl. `_from`, `_to`, `source_id`,
  `target_id`, `kind` when present) plus `_key` / `_id`. Created with `find_or_add_edge_entries` (dedupe on
  `_from`,`_to` like Arango :616). An edge whose `_from`/`_to` vertex does not exist is skipped with a
  `logger.warning` and not counted (HelixDB cannot store dangling edges — Arango can; record in Completion Note).
- **Plane bootstrap**: `PlaneSchema(plane="ontology", schema_version="1", labels=[LabelSpec(label=c,
  unique_key="_key", equality=["_id", "_active"], text_property="search_text") …], edge_labels=[…])` built from
  `ctx.ontology`; `ensure_collection` bootstraps one label lazily. `ctx.ontology.search_views` → one
  `logger.warning` per view ("ArangoSearch views are not supported on HelixDB; skipped").
- **Clients**: one `HelixClient` per database, opened lazily through `open_helix_client(settings_factory(ctx))`,
  cached in a dict guarded by an `asyncio.Lock`; `close()` closes them all. All writes go through
  `HelixClient.write`, all reads through `HelixClient.read` with a stable `query_name` (`"ont.<method>"`).

### Drift vs spec
- Spec §6 names `OntologyGraphStore` (graph_store.py:53) — it is now `ArangoOntologyGraphStore` at :62.
- `edges_incident` / `remove_edge_by_triple` match on `source_id` / `target_id` / `kind` (GraphIndex edge fields),
  not `_from`/`_to` — mirror that exactly.
- The factory signature follows `create_ontology_graph_store(backend, **options)` → `factory(**options)`
  (contracts.py:198-200); `create_helix_ontology_store(*, settings_factory=None, **_)` defaults the factory to
  `default_ontology_settings`.

---

## Implementation Blueprint

### Steps (in order)
1. Confirm TASK-4372/4373/4374 symbols exist (settings, client, bootstrap, dsl); read their signatures.
2. Write the module skeleton (class, client cache, tenant naming, factory).
3. Implement the 14 document/edge methods using `helix_dsl` builders + `read_batch`/`write_batch`.
4. Write tests on InMemory mode.

### `packages/ai-parrot/src/parrot/knowledge/ontology/helix_graph_store.py` (CREATE)
```python
"""HelixDB ontology graph store (FEAT-670 M8): GraphDocumentStore + OntologyTraversalStore, dialect "helix"."""
from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Callable, Mapping
from typing import Any, ClassVar

from parrot.knowledge.helix.bootstrap import LabelSpec, PlaneSchema, ensure_plane
from parrot.knowledge.helix.client import HelixClient, open_helix_client
from parrot.knowledge.helix.settings import HelixSettings, resolve_helix_settings
from parrot.knowledge.ontology.contracts import DynamicQuery, GraphDocumentStore, OntologyTraversalStore
from parrot.knowledge.ontology.graph_store import UpsertResult
from parrot.knowledge.ontology.schema import TenantContext, TraversalPattern

logger = logging.getLogger(__name__)
_TENANT = re.compile(r"^[A-Za-z0-9_]{1,64}$")
_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_SEARCH_TEXT_MAX = 64 * 1024


def ontology_database_name(tenant_id: str) -> str:
    """``ont_<tenant_id>``; rejects ids that could alias another tenant's database."""
    if not _TENANT.match(tenant_id or ""):
        raise ValueError(f"tenant_id {tenant_id!r} is not a safe HelixDB database suffix")
    return f"ont_{tenant_id}"


def default_ontology_settings(ctx: TenantContext) -> HelixSettings:
    return resolve_helix_settings(database=ontology_database_name(ctx.tenant_id))


def _label(name: str) -> str:
    if not _IDENT.match(name or ""):
        raise ValueError(f"{name!r} is not a valid collection label")
    return name


class HelixOntologyGraphStore(GraphDocumentStore, OntologyTraversalStore):
    """Ontology graph store on HelixDB — one database per tenant (``ont_<tenant>``)."""

    dialect: ClassVar[str] = "helix"

    def __init__(self, settings_factory: Callable[[TenantContext], HelixSettings] | None = None) -> None:
        self._settings_factory = settings_factory or default_ontology_settings
        self._clients: dict[str, HelixClient] = {}
        self._lock = asyncio.Lock()
        self.logger = logger

    async def _client(self, ctx: TenantContext) -> HelixClient:
        settings = self._settings_factory(ctx)
        # FILL IN: settings.database must equal ontology_database_name(ctx.tenant_id) unless a custom factory
        #   was injected (tests) — never derive it from ctx.arango_db / ctx.ontology (authorization.py:47)
        async with self._lock:
            client = self._clients.get(settings.database)
            if client is None:
                client = await open_helix_client(settings)
                self._clients[settings.database] = client
            return client

    async def close(self) -> None:
        async with self._lock:
            clients, self._clients = list(self._clients.values()), {}
        for client in clients:
            await client.close()

    @staticmethod
    def _vertex_props(collection: str, doc: Mapping[str, Any], key: str, active: bool = True) -> dict[str, Any]:
        props = dict(doc)
        props.update({"_key": key, "_id": f"{collection}/{key}", "_active": active})
        text = " ".join(str(v) for v in doc.values() if isinstance(v, str)).lower()
        props["search_text"] = text[:_SEARCH_TEXT_MAX]
        return props

    async def initialize_tenant(self, ctx: TenantContext) -> None:
        # FILL IN: build PlaneSchema from ctx.ontology.entities (collection) + relations (edge_collection) using the
        #   LabelSpec convention in Implementation Notes; ensure_plane(client, schema); warn once per search_view
        raise NotImplementedError

    async def ensure_collection(self, ctx: TenantContext, name: str, edge: bool = False) -> None:
        # FILL IN: single-label PlaneSchema (edge → edge_labels=[name], labels=[]) via ensure_plane — idempotent
        raise NotImplementedError

    async def upsert_nodes(
        self, ctx: TenantContext, collection: str, nodes: list[dict[str, Any]], key_field: str
    ) -> UpsertResult:
        # FILL IN: _label(collection), _IDENT key_field; read existing props by _key (one read batch), classify
        #   inserted / updated / unchanged (props equal ignoring search_text), then ONE write batch of
        #   upsert_node_entries — parity with graph_store.py:513
        raise NotImplementedError

    async def create_edges(self, ctx: TenantContext, edge_collection: str, edges: list[dict[str, Any]]) -> int:
        # FILL IN: find_or_add_edge_entries on (_from, _to); skip+warn when an endpoint vertex is missing;
        #   return the number newly created — parity with graph_store.py:616
        raise NotImplementedError

    # FILL IN: get_all_nodes (_active != False), soft_delete_nodes (set_property _active False),
    #   get_document (by _key), upsert_document (full replace — drop stale props; requires "_key"),
    #   insert_document (generate uuid4 hex _key when absent), remove_document (drop; True when existed),
    #   query_documents (_IDENT-checked filter keys and sort_desc; equality where + order_by desc + limit ≤ 800),
    #   get_all_edges, edges_incident (source_id == node OR target_id == node), remove_edge_by_triple
    #   (source_id, target_id, kind; True when ≥1 dropped) — each mirrors the graph_store.py line cited in the contract

    # ── OntologyTraversalStore — implemented by TASK-4388 ─────────────────────────────
    async def is_reachable(self, ctx, start_id, target_id, *, edge_collection, max_depth, direction="outbound") -> bool:
        raise NotImplementedError("TASK-4388")

    async def get_document_by_id(self, ctx: TenantContext, doc_id: str) -> dict[str, Any] | None:
        raise NotImplementedError("TASK-4388")

    async def find_by_field(self, ctx, collection, field, value, *, filters=None, limit=2) -> list[dict[str, Any]]:
        raise NotImplementedError("TASK-4388")

    async def search_by_name(self, ctx, collection, needle, *, field="name", filters=None, limit=10) -> list[dict[str, Any]]:
        raise NotImplementedError("TASK-4388")

    async def execute_pattern(self, ctx, pattern: TraversalPattern, params, collection_binds=None) -> list[dict[str, Any]]:
        raise NotImplementedError("TASK-4388")

    async def execute_query(self, ctx: TenantContext, query: DynamicQuery) -> list[dict[str, Any]]:
        raise NotImplementedError("TASK-4388")


def create_helix_ontology_store(
    *, settings_factory: Callable[[TenantContext], HelixSettings] | None = None, **_: Any
) -> HelixOntologyGraphStore:
    """``register_ontology_backend("helixdb", …)`` target (registered by TASK-4392)."""
    return HelixOntologyGraphStore(settings_factory=settings_factory)
```
**Why this shape**: database selection from `tenant_id` only is the tenant-isolation boundary (the authorization
checker passes a synthetic ctx); the `_id`/`_key`/`_active`/`search_text` properties are the contract TASK-4386's
op-tree and TASK-4388's typed traversals query. Keep signatures identical to the ABC (copy type hints from
contracts.py when filling in).

### FILL IN checklist
- [ ] `_client` database guard
- [ ] `initialize_tenant`, `ensure_collection` — PlaneSchema per conventions; search_views warning
- [ ] `upsert_nodes` counts parity; `create_edges` dedupe + dangling skip
- [ ] the remaining 10 methods — parity with the cited graph_store.py lines
- [ ] nested-value encoding decision (after checking the wheel)

---

## Acceptance Criteria

- [ ] AC7 (part): `isinstance(store, GraphDocumentStore)` and `isinstance(store, OntologyTraversalStore)`;
      `HelixOntologyGraphStore.dialect == "helix"`; class is instantiable.
- [ ] Every document/edge op behaves like the Arango reference on InMemory (upsert counts, soft delete hides from
      `get_all_nodes`, edge dedupe, triple removal, incident edges, equality query + sort + limit).
- [ ] `ontology_database_name("a/b")`, `("")`, `("x"*65)` raise `ValueError`; two tenants never share a client.
- [ ] Non-identifier collection / filter / sort names raise `ValueError` before any SDK call.
- [ ] `ruff check` clean; no edit to `graph_store.py` / `authorization.py` / `entity_resolver.py` / `mixin.py`.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/ontology/test_helix_graph_store.py -q`
- `pytest packages/ai-parrot/tests/knowledge/ontology/test_contracts.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/ontology/test_helix_graph_store.py
from datetime import datetime, timezone

import pytest

pytest.importorskip("helixdb")

from parrot.knowledge.helix.settings import HelixMode, HelixSettings
from parrot.knowledge.ontology.contracts import GraphDocumentStore, OntologyTraversalStore
from parrot.knowledge.ontology.helix_graph_store import HelixOntologyGraphStore, ontology_database_name
from parrot.knowledge.ontology.schema import MergedOntology, TenantContext


def _ctx(tenant: str = "t1") -> TenantContext:
    onto = MergedOntology(name="t", version="1", entities={}, relations={}, traversal_patterns={}, layers=[],
                          merge_timestamp=datetime.now(timezone.utc))
    return TenantContext(tenant_id=tenant, arango_db="ignored", pgvector_schema=tenant, ontology=onto)


@pytest.fixture
async def store():
    # the helix_memory_settings fixture lives in tests/knowledge/helix/conftest.py and is NOT visible here
    s = HelixOntologyGraphStore(lambda ctx: HelixSettings(mode=HelixMode.MEMORY, database=ontology_database_name(ctx.tenant_id)))
    yield s
    await s.close()


def test_contracts_and_dialect(store) -> None:
    assert isinstance(store, GraphDocumentStore) and isinstance(store, OntologyTraversalStore)
    assert HelixOntologyGraphStore.dialect == "helix"


@pytest.mark.parametrize("bad", ["", "a/b", "x" * 65, "t1;drop"])
def test_tenant_database_name_rejects(bad: str) -> None:
    with pytest.raises(ValueError):
        ontology_database_name(bad)


@pytest.mark.asyncio
async def test_upsert_soft_delete_roundtrip(store) -> None:
    ctx = _ctx()
    await store.ensure_collection(ctx, "employees")
    r1 = await store.upsert_nodes(ctx, "employees", [{"employee_id": "e1", "name": "Ana"}], "employee_id")
    r2 = await store.upsert_nodes(ctx, "employees", [{"employee_id": "e1", "name": "Ana"}], "employee_id")
    assert (r1.inserted, r2.unchanged) == (1, 1)
    assert (await store.get_document(ctx, "employees", "e1"))["_id"] == "employees/e1"
    await store.soft_delete_nodes(ctx, "employees", ["e1"])
    assert await store.get_all_nodes(ctx, "employees") == []


@pytest.mark.asyncio
async def test_edges_dedupe_incident_and_triple_removal(store) -> None:
    # FILL IN: two vertices, create_edges twice with the same _from/_to → 1 then 0; edges_incident by source_id;
    #   remove_edge_by_triple True then False; dangling edge skipped (count 0)
    ...


@pytest.mark.asyncio
async def test_tenants_are_isolated(store) -> None:
    # FILL IN: upsert in tenant t1; get_document in tenant t2 returns None
    ...
```

---

## Agent Instructions

1. **Work in the feature worktree** `feat-FEAT-670-helixdb-provider`
   (`python -m scripts.sdd.ensure_worktree --slug helixdb-provider --feature-id FEAT-670`), never on `dev`.
2. Read spec §3 Module 8, §6 "HelixDB SDK surface", AC7.
3. Check `Depends-on` (TASK-4374) is `done` in `sdd/tasks/index/helixdb-provider.json`.
4. Re-verify the Codebase Contract: `grep -n 'async def' packages/ai-parrot/src/parrot/knowledge/ontology/contracts.py`,
   and the TASK-4372/4373/4374 symbols (`grep -n '^def \|^async def \|^class ' packages/ai-parrot/src/parrot/knowledge/helix/*.py`).
5. Mark `in-progress` in the per-spec index; commit only that file.
6. Implement from the blueprint; complete every `# FILL IN:`; leave the six traversal methods as the
   `NotImplementedError("TASK-4388")` stubs (TASK-4388 owns them).
7. Run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`; `ruff check --fix` the touched files.
8. **Security review is mandatory**: run `/sdd-codereview TASK-4387` (adversarial, codex second opinion) before
   closing. Focus: tenant isolation (database naming, client cache keying), identifier validation before SDK calls,
   soft-delete visibility. Triage every finding CONFIRM / REJECT / ESCALATE in the Completion Note.
9. Commit only the listed files: `feat(helixdb-provider): TASK-4387 — HelixOntologyGraphStore document surface`.
10. `scripts/sdd/close_task.sh TASK-4387 helixdb-provider verified`, fill the Completion Note, commit SDD state.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**:
