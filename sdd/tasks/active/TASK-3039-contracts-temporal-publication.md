# TASK-3039: Recoverable GraphIndex temporal revision publisher

**Feature**: FEAT-539 - Contracts Card & Ontology
**Spec**: `sdd/specs/contracts-card-ontology.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-3029, TASK-3035
**Assigned-to**: unassigned
**Parallel**: true
**Parallelism notes**: Execute in core worktree feat-FEAT-539-contracts-card-ontology. May run alongside ready tasks with disjoint owned files after all dependencies complete. No concurrent edits to any file listed below. M8 commits must be integrated into the core lane before the delta job. Packaging task alone owns pyproject.toml/uv.lock; DOCX task alone owns bookstore/library.py.

---

## Context

Implements M6 in spec §3 and the corresponding normative §2 behavior. Covers AC7; full feature acceptance remains governed by spec §§4–5.

## Scope

- Map each immutable card revision to GraphUpdate using existing NodeKind.DOCUMENT, stable contracts:contract:<id> identity, canonical source and version/effective interval metadata with historical snapshot in versioned content.
- Drain durable temporal outbox under tenant serialization using separate configured schemas; record receipts and observable retry state.
- Use stable run_id and list_commits/get_commit validation to recover crash-after-commit-before-receipt without duplicate logical publication. Handle retraction tombstones; do not expose global revert.
- Provide scoped recorded-time history/as_of/diff adapters separately from contractual contract_in_force semantics.

**NOT in scope**: implementation owned by other tasks, new dependencies beyond the separately assigned approved rapidfuzz extra, verification UI, OCR, automatic messages, new scheduler or transport infrastructure. Do not modify generic ontology/GraphIndex APIs to bypass the contracts adapters.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/contracts/temporal.py` | CREATE | Task-owned deliverable |
| `packages/ai-parrot/tests/knowledge/contracts/test_temporal.py` | CREATE | Focused verification / fixtures |

## Codebase Contract (Anti-Hallucination)

Relevant spec references were re-read on 2026-09-09 against dev `7ba8ef6b0`. These are source-verified contracts, not a claim that optional integrations were connected. New dependency interfaces come from spec §2 and must be verified after their owning tasks commit.

### Verified Imports

```python
from parrot.knowledge.graphindex.schema import GraphUpdate, UniversalNode, UniversalEdge, NodeKind, EdgeKind  # packages/ai-parrot/src/parrot/knowledge/graphindex/schema.py:233
from parrot.knowledge.graphindex.persist_postgres import PostgresPersistence  # packages/ai-parrot/src/parrot/knowledge/graphindex/persist_postgres.py:207
```

### Existing Signatures to Use

| Existing callable | Verified signature / constraint | Source |
|---|---|---|
| PostgresPersistence constructor | (self, dsn: Optional[str] = None, *, pool: Optional[asyncpg.Pool] = None, schema: str = "graphindex") -> None | packages/ai-parrot/src/parrot/knowledge/graphindex/persist_postgres.py:226 |
| apply_update | async (self, ctx: TenantContext, update: GraphUpdate) -> CommitReceipt; independent transaction and generated commit_id | packages/ai-parrot/src/parrot/knowledge/graphindex/persist_postgres.py:834 |
| list_commits / get_commit | async list_commits(self, ctx, run_id=None, agent_id=None, limit=50); async get_commit(self, ctx, commit_id) | packages/ai-parrot/src/parrot/knowledge/graphindex/persist_postgres.py:1005; packages/ai-parrot/src/parrot/knowledge/graphindex/persist_postgres.py:976 |
| GraphIndexToolkit temporal tools | async graph_as_of(timestamp), graph_concept_history(concept_id), graph_diff(concept_id, t1, t2) | packages/ai-parrot-tools/src/parrot_tools/graphindex/toolkit.py:1214 |

### Does NOT Exist

- All task CREATE paths and contracts public interfaces are new at decomposition time; do not import unfinished dependency outputs.
- No SQLite catalog, generic BookCard inheritance or scheduler integration is authorized.
- PostgresPersistence is not a ContractCatalogStore; passing TenantContext does not tenant-scope all temporal reads or join apply_update to catalog transactions.

## Implementation Notes

Use strict type hints, Pydantic v2, async entrypoints, black/isort and lazy optional dependencies with actionable errors. Offload synchronous parsing/content reads. Keep core independent of parrot_tools and parrot.scheduler. Validate configured identifiers and bind user SQL/AQL values. Treat source documents as untrusted data. Re-read dependency contracts and owned files before editing; do not overwrite another worker's changes.

### Dependency interfaces

- `TASK-3029`: Catalog aliases, audit, sources and publication state; inspect its completed artifact and committed interface before use.
- `TASK-3035`: Verification and refresh preserve human decisions; inspect its completed artifact and committed interface before use.

## Acceptance Criteria

- [ ] Live GraphIndex tests show successive versions and late-recorded effective amendment with distinct recorded/effective answers.
- [ ] Injected crash recovers validated receipt without a second logical version; mismatched payload is not accepted.
- [ ] Identical slugs across schemas cannot leak temporal reads; failed target is observable and retryable.
- [ ] Changes stay within owned files, imports are verified and appropriate focused validation is recorded.

## Test Specification

1. Live GraphIndex tests show successive versions and late-recorded effective amendment with distinct recorded/effective answers.
2. Injected crash recovers validated receipt without a second logical version; mismatched payload is not accepted.
3. Identical slugs across schemas cannot leak temporal reads; failed target is observable and retryable.

Validation: `uv run pytest packages/ai-parrot/tests/knowledge/contracts/test_temporal.py -q`

Store execution logs in `artifacts/logs/task-3039.log`. Use frozen dates, synthetic sources, fake structured adapters and explicit failure injection. Live Postgres suites require explicit `GRAPHINDEX_PG_DSN` and temporary schemas; no default DSN fallback. Arango suites require explicit test configuration. Missing services skip only those suites and do not count as live acceptance. Do not fabricate benchmark results or pilot signoff.

## Agent Instructions

1. Read the full spec and this scope; confirm all dependency tasks are completed and committed.
2. Use the designated worktree; verify every referenced import/signature and update stale contracts before code changes.
3. Update only `sdd/tasks/index/contracts-card-ontology.json` assignment/status timestamps for this task, never the historical monolithic index.
4. Implement only owned files, validate acceptance criteria and record real results.
5. Move this artifact to `sdd/tasks/completed/TASK-3039-contracts-temporal-publication.md` when complete, update its per-spec index entry, and commit implementation plus SDD state.
6. Fill in the completion note; unavailable external acceptance must remain pending rather than being reported as successful.

## Completion Note

Pending execution. Record executor, completion date, implementation summary, validation evidence and deviations when this task is completed.
