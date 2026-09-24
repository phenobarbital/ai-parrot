# TASK-3712: ManualGraphLoader over owned collections only (M9)

**Feature**: FEAT-601 — Procedure Graph (training agent)
**Spec**: `sdd/specs/training-agent.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3701, TASK-3710, TASK-3711
**Assigned-to**: unassigned

---

## Context

Spec §3 **Module 9** (loader half), AC5, AC11. `ManualGraphLoader` is the only write path from
the manual catalog into the tenant's ArangoDB ontology graph — a copy of `ContractGraphLoader`
restricted to `OWNED_VERTEX_COLLECTIONS` / `OWNED_EDGE_COLLECTIONS`. Technician collections
(`tech_tip`, `tech_tip_on`, `tech_tip_by`) are never read for reconciliation, never
soft-deleted and never edge-pruned; after publication the loader calls `relink_tips` for every
manual whose revision changed and attaches the report (`complete()` is False when relinking
failed). Duplicate `(_from,_to)` links are merged into one edge with list-valued properties
**before** writing, because `create_edges` upserts on endpoints (proposal F010).

Parallelism: reads OWNED_*/resolve_context from TASK-3701 (manuals/domain.py); calls
relink_tips/RelinkReport from TASK-3710 (manuals/tips.py); snapshots via ManualCardDataSource
from TASK-3711 (manuals/datasource.py).

---

## Scope

- Create `packages/ai-parrot/src/parrot/knowledge/manuals/graph_loader.py` with `EdgeSpec`,
  `GraphPublicationReport`, `ManualGraphLoader` per the spec §3 M9 skeleton.
- `EdgeSpec.document()` = `{_from, _to, source_id, target_id, kind, origin, **properties}`
  (`origin="manual"` always).
- `desired_edges(snapshot)`: deterministic + sorted, built from the TASK-3711 record fields —
  `documents` (Manual→Procedure), `assembles` (Procedure→Equipment), `has_step` (Procedure→Step,
  `order`), `precedes` (Step→Step, `kind`), `requires_part` (`quantity`, `contexts: list`),
  `requires_tool`, `warns`, `illustrated_by` (`roles: list`, `confidence`, `origin`),
  `overview_media`, `depicts` (`callouts: list`, `confidence`, `origin`), `shares_module`,
  `supersedes`. Duplicate `(collection, source, target)` ⇒ ONE spec with list props merged
  (roles/contexts/callouts, sorted, deduped; `confidence` = max).
- `publish_all`: context → snapshot (failure ⇒ error, no writes) → capture pre-publish manual
  revisions → upsert owned vertices → soft-delete owned vertices absent from the snapshot →
  `_reconcile_edges` (owned edge collections only; list-prop aware stale comparison) →
  `_verify` read-back → `relink_tips` for each manual whose revision changed →
  `published = report.complete()`.
- `publish(card)` delegates to `publish_all` (documented, as contracts `:594-609`).
- `retract(manual_id)`: soft-delete the manual's owned vertices, remove owned edges incident to
  them; technician collections untouched (their tips become orphaned on the next relink).
- `context()` via `domain.resolve_context(self._tenant_manager, catalog.tenant_id)`;
  `startup_check()` raises `ProceduresDomainNotLoaded` (AC11).
- Write `packages/ai-parrot/tests/knowledge/manuals/test_graph_loader.py`.

**NOT in scope**: the relink algorithm itself (TASK-3710), datasource projection (TASK-3711),
live Arango tests (TASK-3730), CLI (TASK-3727).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/manuals/graph_loader.py` | CREATE | owned-collection reconciliation + relink hook |
| `packages/ai-parrot/tests/knowledge/manuals/test_graph_loader.py` | CREATE | merge, technician isolation, triple/origin, domain check |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.ontology.schema import TenantContext  # verified: packages/ai-parrot/src/parrot/knowledge/ontology/schema.py:529
# Created by TASK-3701 (packages/ai-parrot/src/parrot/knowledge/manuals/domain.py):
from parrot.knowledge.manuals.domain import (
    OWNED_EDGE_COLLECTIONS, OWNED_VERTEX_COLLECTIONS, PROCEDURES_DOMAIN, TECHNICIAN_COLLECTIONS,
    ProceduresDomainNotLoaded, default_tenant_manager, resolve_context,
)
# Created by TASK-3702 / TASK-3699 / TASK-3710 / TASK-3711:
from parrot.knowledge.manuals.catalog import ManualCatalogStore
from parrot.knowledge.manuals.models import ManualCard
from parrot.knowledge.manuals.tips import RelinkReport, relink_tips
from parrot.knowledge.manuals.datasource import ManualCardDataSource
```

### Existing Signatures to Use
```python
# Template — packages/ai-parrot/src/parrot/knowledge/contracts/graph_loader.py
class EdgeSpec(BaseModel): collection; source_collection; source_key; target_collection; target_key; properties   # :106-154
    source_id / target_id / triple properties; document() -> {_from,_to,source_id,target_id,kind,**properties}      # :126-154
class GraphPublicationReport(BaseModel): ... ; complete property                                                  # :157-179
class ContractGraphLoader:                                                                                          # :182
    __init__(*, catalog, graph_store, tenant_manager=None, datasource=None, ontology_dir=None, domain=...)         # :197-214 (asyncio.Lock at :212)
    async def context(self)            # :227-245 — NOTE contracts is async; the spec skeleton makes ours sync `def context(self) -> TenantContext`
    async def startup_check(self)      # :247
    @staticmethod def desired_edges(snapshot) -> list[EdgeSpec]   # :254-408
    async def publish_all(self)        # :437-500 — preflight snapshot, upsert, soft-delete absent owned vertices, reconcile, verify
    async def _reconcile_edges(...)    # :502-548 — remove obsolete / stale-prop edges by triple, then create_edges(wanted)
    async def _verify(...)             # :550-592
    async def publish(self, card)      # :594-609 — delegates to publish_all
    async def retract(self, id)        # :611-675 — soft_delete + edges_incident + remove_edge_by_triple per owned edge collection

# packages/ai-parrot/src/parrot/knowledge/ontology/graph_store.py (OntologyGraphStore)
async def upsert_nodes(self, ctx, collection, nodes, key_field) -> UpsertResult     # :311 (UpsertResult :21 — inserted/updated)
async def create_edges(self, ctx, edge_collection, edges) -> int                     # :411 — UPSERT {_from,_to} … UPDATE {} ; count inflated on no-op (F010)
async def get_all_nodes(self, ctx, collection) -> list[dict]                         # :488 — hides soft-deleted
async def soft_delete_nodes(self, ctx, collection, keys) -> None                     # :517 — sets _active:false
async def get_all_edges(self, ctx, collection) -> list[dict]                         # :738
async def edges_incident(self, ctx, collection, node_id) -> list[dict]               # :764
async def remove_edge_by_triple(self, ctx, collection, source_id, target_id, kind) -> bool  # :791
```

### Does NOT Exist
- ~~An `origin` filter in `ContractGraphLoader`~~ — docstring mention only (`graph_loader.py:115`); origin is new here.
- ~~Per-card deletion in `publish`~~ — delegates to `publish_all` (F003).
- ~~Edge property UPDATE via `create_edges`~~ — it never updates; remove by triple then recreate.
- ~~Any read/write of `tech_tip*` inside `publish_all`/`_reconcile_edges`/`retract`~~ — only `relink_tips` (TASK-3710) touches them.
- ~~Importing `parrot.knowledge.contracts.graph_loader`~~ — copy, never import contracts.
- ~~`from parrot.knowledge.ontology import …` (package root)~~ — submodules only (AC17).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/manuals/graph_loader.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/knowledge/manuals/test_graph_loader.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/ontology/schema.py#TenantContext",
    "sym:packages/ai-parrot/src/parrot/knowledge/ontology/graph_store.py#OntologyGraphStore.upsert_nodes",
    "sym:packages/ai-parrot/src/parrot/knowledge/ontology/graph_store.py#OntologyGraphStore.create_edges",
    "sym:packages/ai-parrot/src/parrot/knowledge/ontology/graph_store.py#OntologyGraphStore.get_all_nodes",
    "sym:packages/ai-parrot/src/parrot/knowledge/ontology/graph_store.py#OntologyGraphStore.soft_delete_nodes",
    "sym:packages/ai-parrot/src/parrot/knowledge/ontology/graph_store.py#OntologyGraphStore.get_all_edges",
    "sym:packages/ai-parrot/src/parrot/knowledge/ontology/graph_store.py#OntologyGraphStore.edges_incident",
    "sym:packages/ai-parrot/src/parrot/knowledge/ontology/graph_store.py#OntologyGraphStore.remove_edge_by_triple"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Worktree tests: `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src:packages/ai-parrot-integrations/src pytest …`.
- Ontology imports from submodules only (AC17). No new dependency. Google docstrings, strict hints, Pydantic v2, `logger` not `print`.
- Spec report fields are **ints** (`edges_created: int`, `edges_removed: int`), unlike contracts' dicts — keep the spec shape; do not treat `create_edges`' return as "created" in logs (inflated count).
- **Relink inputs**: before upserting, read each owned `manual` node's `revision` (`get_all_nodes(ctx, "manual")`). For every card whose revision differs from the graph, `previous_steps` = steps of `ManualCard.model_validate(card.versions[-2].card_snapshot)` (the previous `ManualVersion`), `current_steps` = steps of the card. Missing previous version ⇒ no relink (first publish).
- Stale-property comparison must treat list props order-insensitively (`sorted`) because `desired_edges` sorts them.
- Tests: `FakeGraphStore` from `packages/ai-parrot/tests/knowledge/_support/graph.py` (TASK-3698), `InMemoryManualCatalog` from `_support/catalog.py` (TASK-3702). Pre-seed `tech_tip`, `tech_tip_on`, `tech_tip_by` and assert they are byte-identical after `publish_all` and `retract`.

### References in Codebase
- `packages/ai-parrot/src/parrot/knowledge/contracts/graph_loader.py:182-675` — full template.

---

## Implementation Blueprint

### Steps (in order)
1. Write `EdgeSpec` + `GraphPublicationReport` per skeleton (add `origin`, `tip_relink`, `complete()` method) — *why*: AC5 requires the origin/triple on every edge and TASK-3713's `IngestResult` reads the relink report.
2. Implement `desired_edges` with a merge step keyed by `(collection, source_id, target_id)` — *why*: F010 edge collapse would otherwise silently drop the second role.
3. Implement `publish_all` / `_reconcile_edges` / `_verify` iterating **only** `OWNED_*` — *why*: AC5 technician isolation.
4. Hook `relink_tips` after verify; fold failures into `complete()` — *why*: "the publication report carries link-maintenance failures instead of claiming success".
5. Implement `retract` — *why*: AC5 retract never touches technician collections.
6. Write tests — *why*: `test_desired_edges_merges_duplicate_pairs`, `test_publish_all_never_touches_technician_collections`, `test_edges_carry_origin_and_triple` are spec §4 M9.

### `packages/ai-parrot/src/parrot/knowledge/manuals/graph_loader.py` (CREATE) — part 1: models
```python
"""Publish the manual catalog into the tenant ontology graph (FEAT-601 M9).

Only manual-owned collections are reconciled. Technician collections are
never read, pruned or deleted here; tips are re-linked afterwards.
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, Literal, Mapping, Optional, Sequence

from pydantic import BaseModel, Field

from parrot.knowledge.ontology.schema import TenantContext

from .catalog import ManualCatalogStore
from .datasource import ManualCardDataSource
from .domain import (
    OWNED_EDGE_COLLECTIONS, OWNED_VERTEX_COLLECTIONS, PROCEDURES_DOMAIN, TECHNICIAN_COLLECTIONS,
    ProceduresDomainNotLoaded, default_tenant_manager, resolve_context,
)
from .models import ManualCard
from .tips import RelinkReport, relink_tips

logger = logging.getLogger(__name__)

ENTITY_COLLECTIONS: dict[str, str] = {
    "Equipment": "equipment", "Manual": "manual", "Procedure": "procedure", "Step": "step",
    "Part": "part", "Tool": "tool", "Hazard": "hazard", "Media": "media",
}
ENTITY_KEYS: dict[str, str] = {e: f"{c}_id" for e, c in ENTITY_COLLECTIONS.items()}
SEED_ORDER: tuple[str, ...] = ("Equipment", "Part", "Tool", "Hazard", "Media", "Manual", "Procedure", "Step")
LIST_PROPERTIES: frozenset[str] = frozenset({"roles", "contexts", "callouts"})
assert not set(TECHNICIAN_COLLECTIONS) & (set(OWNED_VERTEX_COLLECTIONS) | set(OWNED_EDGE_COLLECTIONS))


class EdgeSpec(BaseModel):
    """One deterministic edge the projection intends to exist."""

    collection: str
    source_collection: str
    source_key: str
    target_collection: str
    target_key: str
    properties: dict[str, Any] = Field(default_factory=dict)
    origin: Literal["manual"] = "manual"

    @property
    def source_id(self) -> str:
        return f"{self.source_collection}/{self.source_key}"

    @property
    def target_id(self) -> str:
        return f"{self.target_collection}/{self.target_key}"

    def document(self) -> dict[str, Any]:
        """Edge document: ``_from/_to`` + ``source_id/target_id/kind`` triple + ``origin`` + properties."""
        return {"_from": self.source_id, "_to": self.target_id, "source_id": self.source_id,
                "target_id": self.target_id, "kind": self.collection, "origin": self.origin, **self.properties}


class GraphPublicationReport(BaseModel):
    """What one publication attempt achieved; ``published`` only after read-back."""

    published: bool = False
    nodes_upserted: dict[str, int] = Field(default_factory=dict)
    edges_created: int = 0
    edges_removed: int = 0
    deactivated: dict[str, list[str]] = Field(default_factory=dict)
    missing_nodes: list[str] = Field(default_factory=list)
    missing_edges: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    tip_relink: Optional[RelinkReport] = None

    def complete(self) -> bool:
        """False on any error/missing item or any failed tip relink."""
        failed = bool(self.tip_relink and self.tip_relink.failed)
        return not (self.errors or self.missing_nodes or self.missing_edges or failed)
```
**Why**: the `assert` documents the disjointness invariant at import time (Known Risk "tip loss on
re-publish"). `tip_relink` is a single report in the spec; when several manuals relink in one run,
merge them into one `RelinkReport(manual_id="*")` or keep the last and log others — FILL IN below.

### `graph_loader.py` — part 2: loader (append below part 1)
```python
class ManualGraphLoader:
    """Reconcile manual-owned collections; never touches technician collections."""

    def __init__(self, *, catalog: ManualCatalogStore, graph_store: Any, tenant_manager: Any = None,
                 datasource: Optional[ManualCardDataSource] = None, ontology_dir: str | Path | None = None,
                 domain: str = PROCEDURES_DOMAIN) -> None:
        self.catalog = catalog
        self.graph_store = graph_store
        self.domain = domain
        self._tenant_manager = tenant_manager or default_tenant_manager(ontology_dir)
        self.datasource = datasource or ManualCardDataSource(config={"catalog": catalog})
        self._lock = asyncio.Lock()
        self._ctx: Optional[TenantContext] = None

    def context(self) -> TenantContext:
        """Resolve (and cache) the procedures tenant context; raises ProceduresDomainNotLoaded."""
        if self._ctx is None:
            self._ctx = resolve_context(self._tenant_manager, self.catalog.tenant_id)
        return self._ctx

    async def startup_check(self) -> None:
        """Fail fast when the procedures domain is not loaded (AC11)."""
        self.context()

    @staticmethod
    def desired_edges(snapshot: dict[str, list[dict[str, Any]]]) -> list[EdgeSpec]:
        """Deterministic, sorted edges; duplicate (collection, source, target) merged into list props."""
        # FILL IN: one builder per relation (table in Scope) from TASK-3711 record fields
        # FILL IN: merge dupes — LIST_PROPERTIES union+sorted, confidence=max, other props must agree (else keep first + logger.warning)
        # FILL IN: shares_module — derive only from data the snapshot carries; if none, emit none and document
        raise NotImplementedError

    @staticmethod
    def _node_payload(record: dict[str, Any], key_field: str) -> dict[str, Any]:
        """Vertex payload: ``_key`` = record[key_field]; drop relational-only fields (lists of dicts for edges)."""
        raise NotImplementedError

    async def publish_all(self) -> GraphPublicationReport:
        """Snapshot → upsert → soft-delete absent owned vertices → reconcile edges → verify → relink tips."""
        report = GraphPublicationReport()
        async with self._lock:
            try:
                ctx = self.context()
            except ProceduresDomainNotLoaded as exc:
                report.errors.append(str(exc))
                return report
            # FILL IN: snapshot preflight (exception ⇒ errors, return — never write on a failed extraction)
            # FILL IN: previous = {n["manual_id"]: n.get("revision") for n in get_all_nodes(ctx, "manual")}
            # FILL IN: upsert SEED_ORDER; soft-delete absent keys for every OWNED_VERTEX_COLLECTIONS collection
            # FILL IN: desired = self.desired_edges(snapshot); await self._reconcile_edges(ctx, desired, report); await self._verify(...)
            # FILL IN: relink for cards whose revision changed (see Implementation Notes) → report.tip_relink
            report.published = report.complete()
        return report

    async def _reconcile_edges(self, ctx: TenantContext, wanted: Sequence[EdgeSpec], report: GraphPublicationReport) -> None:
        """Only OWNED_EDGE_COLLECTIONS: remove obsolete/stale (list-aware) by triple, then create wanted."""
        raise NotImplementedError

    async def _verify(self, ctx: TenantContext, snapshot: Mapping[str, Any], wanted: Sequence[EdgeSpec],
                      report: GraphPublicationReport) -> None:
        """Read back intended vertices/edges into missing_nodes/missing_edges."""
        raise NotImplementedError

    async def publish(self, card: ManualCard) -> GraphPublicationReport:
        """v1: full-catalog reconciliation (a one-card snapshot would retract the rest)."""
        logger.info("Publishing manual %s via a full-catalog reconciliation", card.manual_id)
        return await self.publish_all()

    async def retract(self, manual_id: str) -> GraphPublicationReport:
        """Soft-delete the manual's owned vertices + remove incident owned edges; tech_tip* untouched."""
        # FILL IN: vertex keys from datasource.snapshot(filters={"manual_id": manual_id}); edges_incident per OWNED_EDGE_COLLECTIONS
        raise NotImplementedError
```
**Why**: `context()` is sync per the spec skeleton (contracts' is async) because
`resolve_context` is a pure resolve over the dedicated manager. `ManualCardDataSource`'s first
positional arg is `name`, so pass `config=` by keyword.

### `packages/ai-parrot/tests/knowledge/manuals/test_graph_loader.py` (CREATE)
```python
"""ManualGraphLoader reconciliation (FEAT-601 M9, AC5, AC11)."""
from __future__ import annotations

import pytest

pytest.importorskip("parrot_loaders")

from parrot.knowledge.manuals.graph_loader import EdgeSpec, ManualGraphLoader  # noqa: E402

from .._support.catalog import InMemoryManualCatalog  # TASK-3702  # noqa: E402
from .._support.graph import FakeGraphStore  # TASK-3698  # noqa: E402


def test_desired_edges_merges_duplicate_pairs() -> None:
    """Two (step, media) links primary+secondary ⇒ one EdgeSpec with roles=['primary','secondary']."""


@pytest.mark.asyncio
async def test_publish_all_never_touches_technician_collections() -> None:
    """Pre-seeded tech_tip/tech_tip_on/tech_tip_by identical after publish_all and retract."""


@pytest.mark.asyncio
async def test_edges_carry_origin_and_triple() -> None:
    """Every written edge has source_id/target_id/kind/origin."""


@pytest.mark.asyncio
async def test_startup_check_foreign_manager_raises() -> None:
    """A tenant manager on a foreign ontology dir ⇒ ProceduresDomainNotLoaded (AC11)."""


@pytest.mark.asyncio
async def test_relink_failure_makes_report_incomplete() -> None:
    """Revision change + failing relink ⇒ report.complete() is False and published is False."""
```

### FILL IN checklist
- [ ] `desired_edges` builders + merge; bounded by F010 / AC5
- [ ] `_node_payload` drops relational fields
- [ ] `publish_all` preflight, soft-delete, relink inputs (previous version snapshot); bounded by U3
- [ ] `_reconcile_edges` list-aware stale check, owned collections only
- [ ] `_verify` read-back
- [ ] `retract` owned-only
- [ ] multiple-manual relink merge policy for `tip_relink`
- [ ] five tests

---

## Acceptance Criteria

- [ ] `publish_all`/`retract` never read, soft-delete or prune `tech_tip`, `tech_tip_on`, `tech_tip_by` (AC5).
- [ ] Every owned edge carries `source_id/target_id/kind/origin`; duplicate `(_from,_to)` merged before write (AC5).
- [ ] Foreign-dir tenant manager ⇒ `ProceduresDomainNotLoaded` at `startup_check` (AC11).
- [ ] Relink failures make `complete()` False.
- [ ] `ruff check packages/ai-parrot/src/parrot/knowledge/manuals/graph_loader.py` clean.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/manuals/test_graph_loader.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/manuals/test_graph_loader.py
def test_desired_edges_merges_duplicate_pairs(): ...                 # spec §4 M9
async def test_publish_all_never_touches_technician_collections(): ... # spec §4 M9
async def test_edges_carry_origin_and_triple(): ...                  # spec §4 M9
async def test_startup_check_foreign_manager_raises(): ...           # AC11
async def test_relink_failure_makes_report_incomplete(): ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify `Depends-on` tasks are in `tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
4. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
5. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-3712-manual-graph-loader.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
