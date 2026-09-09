# TASK-3054: Cross-store integration and regression acceptance

**Feature**: FEAT-539 - Contracts Card & Ontology
**Spec**: `sdd/specs/contracts-card-ontology.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-3025, TASK-3026, TASK-3027, TASK-3028, TASK-3029, TASK-3030, TASK-3031, TASK-3032, TASK-3033, TASK-3034, TASK-3035, TASK-3036, TASK-3037, TASK-3038, TASK-3039, TASK-3040, TASK-3041, TASK-3042, TASK-3043, TASK-3044, TASK-3045, TASK-3046, TASK-3047, TASK-3048, TASK-3049, TASK-3050, TASK-3051, TASK-3052
**Assigned-to**: unassigned
**Parallel**: false
**Parallelism notes**: Execute in core worktree feat-FEAT-539-contracts-card-ontology. Run after listed dependencies; shared-file edits are serialized by this DAG. No concurrent edits to any file listed below. M8 commits must be integrated into the core lane before the delta job. Packaging task alone owns pyproject.toml/uv.lock; DOCX task alone owns bookstore/library.py.

---

## Context

Implements M1–M12 in spec §3 and the corresponding normative §2 behavior. Covers AC1, AC2, AC3, AC4, AC5, AC6, AC7, AC8, AC9, AC10, AC11, AC12, AC13; full feature acceptance remains governed by spec §§4–5.

## Scope

- Create shared synthetic English MSA/SOW/amendment/NDA/contradictory-clause fixtures, generated small PDF/DOCX/text/image-only PDF and two tenants reusing slugs/node IDs; freeze dates and inject boundary failures.
- Run real Postgres atomicity/isolation, GraphIndex recovery/history and Arango domain initialization/all ten AQL pattern tests, including first-publish standards, owner changes, retraction, family/search mapping.
- Run fake Graph -> ingest -> verify -> graph/temporal -> both answer producers -> retire -> refresh -> watcher end-to-end and affected bookstore/O365 regressions.
- Use explicit GRAPHINDEX_PG_DSN and temporary schemas only; Arango also requires explicit config. Missing services skip only relevant suites but do not satisfy full acceptance. Save logs in artifacts/logs/.

**NOT in scope**: implementation owned by other tasks, new dependencies beyond the separately assigned approved rapidfuzz extra, verification UI, OCR, automatic messages, new scheduler or transport infrastructure. Do not modify generic ontology/GraphIndex APIs to bypass the contracts adapters.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/knowledge/contracts/test_integration.py` | CREATE | Focused verification / fixtures |
| `packages/ai-parrot/tests/knowledge/contracts/conftest.py` | CREATE | Focused verification / fixtures |
| `packages/ai-parrot-tools/tests/contracts/test_end_to_end.py` | CREATE | Focused verification / fixtures |
| `packages/ai-parrot-tools/tests/contracts/conftest.py` | CREATE | Focused verification / fixtures |

## Codebase Contract (Anti-Hallucination)

Relevant spec references were re-read on 2026-09-09 against dev `7ba8ef6b0`. These are source-verified contracts, not a claim that optional integrations were connected. New dependency interfaces come from spec §2 and must be verified after their owning tasks commit.

### Verified Imports

```python
from parrot.knowledge.pageindex.toolkit import PageIndexToolkit  # packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py:377
from parrot.knowledge.ontology.graph_store import OntologyGraphStore  # packages/ai-parrot/src/parrot/knowledge/ontology/graph_store.py:34
from parrot.knowledge.graphindex.persist_postgres import PostgresPersistence  # packages/ai-parrot/src/parrot/knowledge/graphindex/persist_postgres.py:207
from parrot_tools.o365.base import O365Tool, O365ToolArgsSchema  # packages/ai-parrot-tools/src/parrot_tools/o365/base.py:31
```

### Existing Signatures to Use

| Existing callable | Verified signature / constraint | Source |
|---|---|---|
| PageIndexToolkit | async create_tree(self, tree_name: str, doc_name: Optional[str] = None) -> dict[str, Any]; delete_tree/get_tree take tree_name | packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py:377 |
| insert_markdown | async (self, tree_name: str, markdown: str, parent_node_id: Optional[str] = None, doc_name: Optional[str] = None) -> dict[str, Any] | packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py:692 |
| import_pdf | async (self, tree_name: str, pdf_path: str, parent_node_id: Optional[str] = None, with_summaries: bool = True, with_doc_description: bool = False) -> dict[str, Any] | packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py:803 |
| execute_traversal | async (self, ctx: TenantContext, aql: str, bind_vars: dict or None = None, collection_binds: dict[str, str] or None = None) -> list[dict[str, Any]] | packages/ai-parrot/src/parrot/knowledge/ontology/graph_store.py:234 |
| upsert_nodes | async (self, ctx: TenantContext, collection: str, nodes: list[dict[str, Any]], key_field: str) -> UpsertResult; copies key field to _key | packages/ai-parrot/src/parrot/knowledge/ontology/graph_store.py:274 |
| create_edges | async (self, ctx: TenantContext, edge_collection: str, edges: list[dict[str, Any]]) -> int; UPDATE {} on duplicate endpoints | packages/ai-parrot/src/parrot/knowledge/ontology/graph_store.py:372 |
| edges_incident / remove_edge_by_triple | Edges keyed by source_id/target_id/kind, not just _from/_to | packages/ai-parrot/src/parrot/knowledge/ontology/graph_store.py:725; packages/ai-parrot/src/parrot/knowledge/ontology/graph_store.py:752 |
| PostgresPersistence constructor | (self, dsn: Optional[str] = None, *, pool: Optional[asyncpg.Pool] = None, schema: str = "graphindex") -> None | packages/ai-parrot/src/parrot/knowledge/graphindex/persist_postgres.py:226 |
| apply_update | async (self, ctx: TenantContext, update: GraphUpdate) -> CommitReceipt; independent transaction and generated commit_id | packages/ai-parrot/src/parrot/knowledge/graphindex/persist_postgres.py:834 |
| list_commits / get_commit | async list_commits(self, ctx, run_id=None, agent_id=None, limit=50); async get_commit(self, ctx, commit_id) | packages/ai-parrot/src/parrot/knowledge/graphindex/persist_postgres.py:1005; packages/ai-parrot/src/parrot/knowledge/graphindex/persist_postgres.py:976 |
| O365Tool._execute_graph_operation | async (self, client: O365Client, **kwargs) -> Any; _execute handles authentication and ToolResult | packages/ai-parrot-tools/src/parrot_tools/o365/base.py:200 |

### Does NOT Exist

- All task CREATE paths and contracts public interfaces are new at decomposition time; do not import unfinished dependency outputs.
- No SQLite catalog, generic BookCard inheritance or scheduler integration is authorized.
- OntologyRefreshPipeline.run has no filters argument and no atomic multi-collection publish; create_edges does not update existing edge properties.
- PropertyDef has no datetime/nested-model type; RelationDef has no symmetric flag.
- PostgresPersistence is not a ContractCatalogStore; passing TenantContext does not tenant-scope all temporal reads or join apply_update to catalog transactions.

## Implementation Notes

Use strict type hints, Pydantic v2, async entrypoints, black/isort and lazy optional dependencies with actionable errors. Offload synchronous parsing/content reads. Keep core independent of parrot_tools and parrot.scheduler. Validate configured identifiers and bind user SQL/AQL values. Treat source documents as untrusted data. Re-read dependency contracts and owned files before editing; do not overwrite another worker's changes.

### Dependency interfaces

- `TASK-3025`: Typed contract models and standard aliases; inspect its completed artifact and committed interface before use.
- `TASK-3026`: Tenant-bound asynchronous catalog protocol; inspect its completed artifact and committed interface before use.
- `TASK-3027`: Postgres schema and atomic card writes; inspect its completed artifact and committed interface before use.
- `TASK-3028`: Catalog search, date windows and verification queue; inspect its completed artifact and committed interface before use.
- `TASK-3029`: Catalog aliases, audit, sources and publication state; inspect its completed artifact and committed interface before use.
- `TASK-3030`: Bounded evidenced header and obligation extraction; inspect its completed artifact and committed interface before use.
- `TASK-3031`: Deterministic assembly, status and parent resolution; inspect its completed artifact and committed interface before use.
- `TASK-3032`: Public asynchronous DOCX conversion helper; inspect its completed artifact and committed interface before use.
- `TASK-3033`: Immutable tenant and version-scoped evidence storage; inspect its completed artifact and committed interface before use.
- `TASK-3034`: Staged library ingestion and canonical source identity; inspect its completed artifact and committed interface before use.
- `TASK-3035`: Verification and refresh preserve human decisions; inspect its completed artifact and committed interface before use.
- `TASK-3036`: Contracts ontology vocabulary and allowlisted patterns; inspect its completed artifact and committed interface before use.
- `TASK-3037`: Catalog-backed ContractCard datasource; inspect its completed artifact and committed interface before use.
- `TASK-3038`: Full-catalog graph reconciliation and retraction; inspect its completed artifact and committed interface before use.
- `TASK-3039`: Recoverable GraphIndex temporal revision publisher; inspect its completed artifact and committed interface before use.
- `TASK-3040`: Explicit bounded relation judgements and invalidation; inspect its completed artifact and committed interface before use.
- `TASK-3041`: O365 drive delta pages, validation and retry helper; inspect its completed artifact and committed interface before use.
- `TASK-3042`: SharePoint and OneDrive delta tools and registration; inspect its completed artifact and committed interface before use.
- `TASK-3043`: Deterministic authorized retrieval and typed pattern binds; inspect its completed artifact and committed interface before use.
- `TASK-3044`: Versioned citation and claim verification gate; inspect its completed artifact and committed interface before use.
- `TASK-3045`: Shared answer authorization, release and audit service; inspect its completed artifact and committed interface before use.
- `TASK-3046`: Prefixed read tools and confirming administration; inspect its completed artifact and committed interface before use.
- `TASK-3047`: Executable fixed contracts answer runner; inspect its completed artifact and committed interface before use.
- `TASK-3048`: ReAct ContractsAgent with shared release gate; inspect its completed artifact and committed interface before use.
- `TASK-3049`: Durable O365 delta ingestion job; inspect its completed artifact and committed interface before use.
- `TASK-3050`: Deterministic renewal and obligation reports; inspect its completed artifact and committed interface before use.
- `TASK-3051`: Contracts operator CLI and administrative commands; inspect its completed artifact and committed interface before use.
- `TASK-3052`: Declare approved rapidfuzz extra and refresh lock; inspect its completed artifact and committed interface before use.

## Acceptance Criteria

- [ ] All configured unit/live integration/regression suites pass with failure injection and no tenant/evidence leak.
- [ ] Every ten-pattern query executes with real bindings; historical evidence survives refresh and crash recovery avoids duplicate logical versions.
- [ ] Record suite results and services actually exercised; unavailable live suites leave feature acceptance pending.
- [ ] Changes stay within owned files, imports are verified and appropriate focused validation is recorded.

## Test Specification

1. All configured unit/live integration/regression suites pass with failure injection and no tenant/evidence leak.
2. Every ten-pattern query executes with real bindings; historical evidence survives refresh and crash recovery avoids duplicate logical versions.
3. Record suite results and services actually exercised; unavailable live suites leave feature acceptance pending.

Validation: `uv run pytest packages/ai-parrot/tests/knowledge/contracts/test_integration.py packages/ai-parrot-tools/tests/contracts/test_end_to_end.py -q`

Store execution logs in `artifacts/logs/task-3054.log`. Use frozen dates, synthetic sources, fake structured adapters and explicit failure injection. Live Postgres suites require explicit `GRAPHINDEX_PG_DSN` and temporary schemas; no default DSN fallback. Arango suites require explicit test configuration. Missing services skip only those suites and do not count as live acceptance. Do not fabricate benchmark results or pilot signoff.

## Agent Instructions

1. Read the full spec and this scope; confirm all dependency tasks are completed and committed.
2. Use the designated worktree; verify every referenced import/signature and update stale contracts before code changes.
3. Update only `sdd/tasks/index/contracts-card-ontology.json` assignment/status timestamps for this task, never the historical monolithic index.
4. Implement only owned files, validate acceptance criteria and record real results.
5. Move this artifact to `sdd/tasks/completed/TASK-3054-contracts-live-integration.md` when complete, update its per-spec index entry, and commit implementation plus SDD state.
6. Fill in the completion note; unavailable external acceptance must remain pending rather than being reported as successful.

## Completion Note

Pending execution. Record executor, completion date, implementation summary, validation evidence and deviations when this task is completed.
