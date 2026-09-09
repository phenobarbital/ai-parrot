# TASK-3038: Full-catalog graph reconciliation and retraction

**Feature**: FEAT-539 - Contracts Card & Ontology
**Spec**: `sdd/specs/contracts-card-ontology.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-3037
**Assigned-to**: unassigned
**Parallel**: false
**Parallelism notes**: Execute in core worktree feat-FEAT-539-contracts-card-ontology. Run after listed dependencies; shared-file edits are serialized by this DAG. No concurrent edits to any file listed below. M8 commits must be integrated into the core lane before the delta job. Packaging task alone owns pyproject.toml/uv.lock; DOCX task alone owns bookstore/library.py.

---

## Context

Implements M5 in spec §3 and the corresponding normative §2 behavior. Covers AC5, AC6; full feature acceptance remains governed by spec §§4–5.

## Scope

- Implement publish_all/publish/retract with dedicated configured contracts tenant manager, startup domain check, tenant lock and durable target receipts.
- publish(card) delegates to a complete validated catalog publish; pre-extract before mutation, retain base Employee/Department targets and avoid unrelated base-source refresh.
- Seed standards before requires discovery, synchronize nodes then reconcile all deterministic scalar/property edges. Normalize source_id/target_id/kind and replace obsolete endpoint/property edges within feature-owned collections only.
- Retract contracts/obligations and incident edges, preserve shared parties/people/history, queue temporal tombstones. Read back intended nodes/edges before marking revision published; expose partial failures and reject stale/incomplete projections.

**NOT in scope**: implementation owned by other tasks, new dependencies beyond the separately assigned approved rapidfuzz extra, verification UI, OCR, automatic messages, new scheduler or transport infrastructure. Do not modify generic ontology/GraphIndex APIs to bypass the contracts adapters.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/contracts/graph_loader.py` | CREATE | Task-owned deliverable |
| `packages/ai-parrot/tests/knowledge/contracts/test_graph_loader.py` | CREATE | Focused verification / fixtures |

## Codebase Contract (Anti-Hallucination)

Relevant spec references were re-read on 2026-09-09 against dev `7ba8ef6b0`. These are source-verified contracts, not a claim that optional integrations were connected. New dependency interfaces come from spec §2 and must be verified after their owning tasks commit.

### Verified Imports

```python
from parrot.knowledge.ontology.refresh import OntologyRefreshPipeline, RefreshReport  # packages/ai-parrot/src/parrot/knowledge/ontology/refresh.py:41
from parrot.knowledge.ontology.discovery import RelationDiscovery  # packages/ai-parrot/src/parrot/knowledge/ontology/discovery.py:52
from parrot.knowledge.ontology.graph_store import OntologyGraphStore  # packages/ai-parrot/src/parrot/knowledge/ontology/graph_store.py:34
from parrot.knowledge.ontology.tenant import TenantOntologyManager  # packages/ai-parrot/src/parrot/knowledge/ontology/tenant.py:92
```

### Existing Signatures to Use

| Existing callable | Verified signature / constraint | Source |
|---|---|---|
| OntologyRefreshPipeline.run | async (self, tenant_id: str, domain: str or None = None) -> RefreshReport; extract(fields=property_names), no filters | packages/ai-parrot/src/parrot/knowledge/ontology/refresh.py:94 |
| RelationDiscovery.discover | async (self, ctx: TenantContext, relation_def: RelationDef, source_data: list[dict[str, Any]], target_data: list[dict[str, Any]]) -> DiscoveryResult | packages/ai-parrot/src/parrot/knowledge/ontology/discovery.py:79 |
| execute_traversal | async (self, ctx: TenantContext, aql: str, bind_vars: dict or None = None, collection_binds: dict[str, str] or None = None) -> list[dict[str, Any]] | packages/ai-parrot/src/parrot/knowledge/ontology/graph_store.py:234 |
| upsert_nodes | async (self, ctx: TenantContext, collection: str, nodes: list[dict[str, Any]], key_field: str) -> UpsertResult; copies key field to _key | packages/ai-parrot/src/parrot/knowledge/ontology/graph_store.py:274 |
| create_edges | async (self, ctx: TenantContext, edge_collection: str, edges: list[dict[str, Any]]) -> int; UPDATE {} on duplicate endpoints | packages/ai-parrot/src/parrot/knowledge/ontology/graph_store.py:372 |
| edges_incident / remove_edge_by_triple | Edges keyed by source_id/target_id/kind, not just _from/_to | packages/ai-parrot/src/parrot/knowledge/ontology/graph_store.py:725; packages/ai-parrot/src/parrot/knowledge/ontology/graph_store.py:752 |
| TenantOntologyManager.resolve | (self, tenant_id: str, domain: str or None = None) -> TenantContext; cache keyed by tenant | packages/ai-parrot/src/parrot/knowledge/ontology/tenant.py:92 |

### New design interfaces (not existing imports)

Implement only this task’s scoped portion; sibling methods belong to their designated dependencies or follow-up tasks.

| Interface | Normative contract from spec §2 |
|---|---|
| ContractGraphLoader | async publish_all(), publish(card), retract(contract_id); report includes partial/unavailable target state and errors |

### Does NOT Exist

- All task CREATE paths and contracts public interfaces are new at decomposition time; do not import unfinished dependency outputs.
- No SQLite catalog, generic BookCard inheritance or scheduler integration is authorized.
- OntologyRefreshPipeline.run has no filters argument and no atomic multi-collection publish; create_edges does not update existing edge properties.
- PropertyDef has no datetime/nested-model type; RelationDef has no symmetric flag.

## Implementation Notes

Use strict type hints, Pydantic v2, async entrypoints, black/isort and lazy optional dependencies with actionable errors. Offload synchronous parsing/content reads. Keep core independent of parrot_tools and parrot.scheduler. Validate configured identifiers and bind user SQL/AQL values. Treat source documents as untrusted data. Re-read dependency contracts and owned files before editing; do not overwrite another worker's changes.

### Dependency interfaces

- `TASK-3037`: Catalog-backed ContractCard datasource; inspect its completed artifact and committed interface before use.

## Acceptance Criteria

- [ ] Single-card publication never deactivates unrelated cards; first publish has every standard/parent/party/owner/signatory edge.
- [ ] Owner/property changes remove old edges; retraction preserves shared nodes and unrelated graph collections.
- [ ] Extraction failures, empty snapshots, partial writes and false-success/readback failures remain retryable and unpublished.
- [ ] Changes stay within owned files, imports are verified and appropriate focused validation is recorded.

## Test Specification

1. Single-card publication never deactivates unrelated cards; first publish has every standard/parent/party/owner/signatory edge.
2. Owner/property changes remove old edges; retraction preserves shared nodes and unrelated graph collections.
3. Extraction failures, empty snapshots, partial writes and false-success/readback failures remain retryable and unpublished.

Validation: `uv run pytest packages/ai-parrot/tests/knowledge/contracts/test_graph_loader.py -q`

Store execution logs in `artifacts/logs/task-3038.log`. Use frozen dates, synthetic sources, fake structured adapters and explicit failure injection. Live Postgres suites require explicit `GRAPHINDEX_PG_DSN` and temporary schemas; no default DSN fallback. Arango suites require explicit test configuration. Missing services skip only those suites and do not count as live acceptance. Do not fabricate benchmark results or pilot signoff.

## Agent Instructions

1. Read the full spec and this scope; confirm all dependency tasks are completed and committed.
2. Use the designated worktree; verify every referenced import/signature and update stale contracts before code changes.
3. Update only `sdd/tasks/index/contracts-card-ontology.json` assignment/status timestamps for this task, never the historical monolithic index.
4. Implement only owned files, validate acceptance criteria and record real results.
5. Move this artifact to `sdd/tasks/completed/TASK-3038-contracts-graph-publication.md` when complete, update its per-spec index entry, and commit implementation plus SDD state.
6. Fill in the completion note; unavailable external acceptance must remain pending rather than being reported as successful.

## Completion Note

Completed 2026-09-09 by sdd-worker (Claude Opus 5).

**Implementation**: created `parrot/knowledge/contracts/graph_loader.py`.
`ContractGraphLoader` resolves a **dedicated** contracts `TenantOntologyManager`
(the generic one caches by tenant, not tenant+domain) and fails startup with
`ContractsDomainNotLoaded` when the resolved ontology lacks the contracts entities.
`publish_all` runs under a per-tenant lock: pre-extract a complete prevalidated
snapshot (an extraction failure aborts instead of presenting an empty snapshot the
generic diff would read as "delete everything"), upsert nodes in seed order with
ComplianceStandard first so `requires` links on the first publish, soft-delete only
feature-owned vertices (contract/obligation) absent from the snapshot — shared
Party/Person/Standard identity is never deactivated — then reconcile edges and
finally **read back** the intended node and edge sets before setting
`published=True`. `desired_edges` derives all eleven deterministic relations in
Python from the snapshot, so edges to later-loaded targets exist immediately; every
written edge carries `_from`/`_to` **plus** `source_id`/`target_id`/`kind` so the
generic removal helpers can address it. Reconciliation removes obsolete endpoints,
rewrites edges whose properties changed (`create_edges` never updates properties) and
normalises bare discovery edges — all restricted to the eleven feature-owned edge
collections. `publish(card)` deliberately delegates to `publish_all`. `retract`
deactivates the contract and its obligations, removes only their incident
feature-owned edges, and leaves shared parties/people, unrelated collections and
catalog history/audit untouched.

**Validation**: `pytest .../test_graph_loader.py -q` -> 22 passed (whole contracts
suite 429 passed, `artifacts/logs/task-3038.log`); ruff clean. The fake graph store
reproduces the two real behaviours that matter (endpoint-keyed `create_edges` that
never updates properties; `get_all_nodes` hiding soft-deleted rows). Tests cover
first-publish completeness of every edge kind, standards-before-requires, parent/
amendment resolution on first publish, single-card publication not deactivating
others, owner change removing the old edge, property rewrite, discovery-edge
normalisation, cleanup never touching `reports_to`, retraction preserving shared
nodes, and four failure shapes — extraction failure, partial write, a **false
success** caught by read-back (no errors but nothing stored), and a read-back failure
— all leaving the revision unpublished and retryable.

**Deviations**: none. Real AQL/ArangoDB execution remains the integration gate
(TASK-3054).
