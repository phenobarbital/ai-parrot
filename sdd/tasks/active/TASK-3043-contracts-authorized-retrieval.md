# TASK-3043: Deterministic authorized retrieval and typed pattern binds

**Feature**: FEAT-539 - Contracts Card & Ontology
**Spec**: `sdd/specs/contracts-card-ontology.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-3029, TASK-3035, TASK-3036, TASK-3038
**Assigned-to**: unassigned
**Parallel**: true
**Parallelism notes**: Execute in core worktree feat-FEAT-539-contracts-card-ontology. May run alongside ready tasks with disjoint owned files after all dependencies complete. No concurrent edits to any file listed below. M8 commits must be integrated into the core lane before the delta job. Packaging task alone owns pyproject.toml/uv.lock; DOCX task alone owns bookstore/library.py.

---

## Context

Implements M9 in spec §3 and the corresponding normative §2 behavior. Covers AC5, AC10; full feature acceptance remains governed by spec §§4–5.

## Scope

- Implement shared trusted request context and authorization-before-read entry gate; every direct SQL/graph/evidence read uses reader OR owner policy, default deny and fixed tenant configuration.
- Implement ten explicit typed patterns from spec §2 with most-specific trigger, full-question standard aliases, exact/alias/normalized fuzzy catalog entity matching and optional configured non-generative ranking; uncertain/ambiguous matching returns typed clarification.
- Bind dates/status/kind/top_k and explicit _key versus Employee _id mapping; allowlist YAML AQL only, reject stale/inactive/incomplete graph revisions, retain SQL search/window/queue availability without Arango.
- Apply my_contracts management-chain restriction to returned cards and subsequent evidence reads. Retrieval accepts no LLM client; authorization occurs before protected entity resolution.

**NOT in scope**: implementation owned by other tasks, new dependencies beyond the separately assigned approved rapidfuzz extra, verification UI, OCR, automatic messages, new scheduler or transport infrastructure. Do not modify generic ontology/GraphIndex APIs to bypass the contracts adapters.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/contracts/__init__.py` | CREATE | Task-owned deliverable |
| `packages/ai-parrot-tools/src/parrot_tools/contracts/retrieval.py` | CREATE | Task-owned deliverable |
| `packages/ai-parrot-tools/tests/contracts/test_retrieval.py` | CREATE | Focused verification / fixtures |
| `packages/ai-parrot-tools/tests/contracts/test_authorization.py` | CREATE | Focused verification / fixtures |

## Codebase Contract (Anti-Hallucination)

Relevant spec references were re-read on 2026-09-09 against dev `7ba8ef6b0`. These are source-verified contracts, not a claim that optional integrations were connected. New dependency interfaces come from spec §2 and must be verified after their owning tasks commit.

### Verified Imports

```python
from parrot.knowledge.ontology.graph_store import OntologyGraphStore  # packages/ai-parrot/src/parrot/knowledge/ontology/graph_store.py:34
from parrot.knowledge.ontology.authorization import AuthorizationChecker  # packages/ai-parrot/src/parrot/knowledge/ontology/authorization.py:43
from parrot.knowledge.ontology.tenant import TenantOntologyManager  # packages/ai-parrot/src/parrot/knowledge/ontology/tenant.py:92
```

### Existing Signatures to Use

| Existing callable | Verified signature / constraint | Source |
|---|---|---|
| execute_traversal | async (self, ctx: TenantContext, aql: str, bind_vars: dict or None = None, collection_binds: dict[str, str] or None = None) -> list[dict[str, Any]] | packages/ai-parrot/src/parrot/knowledge/ontology/graph_store.py:234 |
| upsert_nodes | async (self, ctx: TenantContext, collection: str, nodes: list[dict[str, Any]], key_field: str) -> UpsertResult; copies key field to _key | packages/ai-parrot/src/parrot/knowledge/ontology/graph_store.py:274 |
| create_edges | async (self, ctx: TenantContext, edge_collection: str, edges: list[dict[str, Any]]) -> int; UPDATE {} on duplicate endpoints | packages/ai-parrot/src/parrot/knowledge/ontology/graph_store.py:372 |
| edges_incident / remove_edge_by_triple | Edges keyed by source_id/target_id/kind, not just _from/_to | packages/ai-parrot/src/parrot/knowledge/ontology/graph_store.py:725; packages/ai-parrot/src/parrot/knowledge/ontology/graph_store.py:752 |
| AuthorizationChecker.check | async (self, spec: AuthorizationSpec, user_context: dict[str, Any], resolved_entities: dict[str, str], tenant_id: str) -> tuple[bool, str or None]; OR rules | packages/ai-parrot/src/parrot/knowledge/ontology/authorization.py:62 |
| _check_same_department | DOCUMENT(@target_id).department; matches any target, constructs tenant_id + "_ontology" database | packages/ai-parrot/src/parrot/knowledge/ontology/authorization.py:293 |
| TenantOntologyManager.resolve | (self, tenant_id: str, domain: str or None = None) -> TenantContext; cache keyed by tenant | packages/ai-parrot/src/parrot/knowledge/ontology/tenant.py:92 |

### Does NOT Exist

- All task CREATE paths and contracts public interfaces are new at decomposition time; do not import unfinished dependency outputs.
- No SQLite catalog, generic BookCard inheritance or scheduler integration is authorized.
- OntologyRefreshPipeline.run has no filters argument and no atomic multi-collection publish; create_edges does not update existing edge properties.
- PropertyDef has no datetime/nested-model type; RelationDef has no symmetric flag.
- Unmodified OntologyRAGMixin does not enforce the required pre-read authorization ordering; hybrid_concept_match targets Concepts, not Contracts.
- BOE SpanVerifier is domain-specific and the legal crew builder is inspection-only, not an executable contracts runner.

## Implementation Notes

Use strict type hints, Pydantic v2, async entrypoints, black/isort and lazy optional dependencies with actionable errors. Offload synchronous parsing/content reads. Keep core independent of parrot_tools and parrot.scheduler. Validate configured identifiers and bind user SQL/AQL values. Treat source documents as untrusted data. Re-read dependency contracts and owned files before editing; do not overwrite another worker's changes.

### Dependency interfaces

- `TASK-3029`: Catalog aliases, audit, sources and publication state; inspect its completed artifact and committed interface before use.
- `TASK-3035`: Verification and refresh preserve human decisions; inspect its completed artifact and committed interface before use.
- `TASK-3036`: Contracts ontology vocabulary and allowlisted patterns; inspect its completed artifact and committed interface before use.
- `TASK-3038`: Full-catalog graph reconciliation and retraction; inspect its completed artifact and committed interface before use.

## Acceptance Criteria

- [ ] All ten bind sets include null kind, bounded top_k, injected dates and SOC 2 alias with trigger intact.
- [ ] Missing/forged principal, independent read roles, cross-tenant access, direct-tool bypass and my_contracts narrowing are tested before protected reads.
- [ ] Ambiguity returns clarification; stale/inactive projections fail closed; deterministic SQL reports work without Arango and no LLM calls occur.
- [ ] Changes stay within owned files, imports are verified and appropriate focused validation is recorded.

## Test Specification

1. All ten bind sets include null kind, bounded top_k, injected dates and SOC 2 alias with trigger intact.
2. Missing/forged principal, independent read roles, cross-tenant access, direct-tool bypass and my_contracts narrowing are tested before protected reads.
3. Ambiguity returns clarification; stale/inactive projections fail closed; deterministic SQL reports work without Arango and no LLM calls occur.

Validation: `uv run pytest packages/ai-parrot-tools/tests/contracts/test_retrieval.py packages/ai-parrot-tools/tests/contracts/test_authorization.py -q`

Store execution logs in `artifacts/logs/task-3043.log`. Use frozen dates, synthetic sources, fake structured adapters and explicit failure injection. Live Postgres suites require explicit `GRAPHINDEX_PG_DSN` and temporary schemas; no default DSN fallback. Arango suites require explicit test configuration. Missing services skip only those suites and do not count as live acceptance. Do not fabricate benchmark results or pilot signoff.

## Agent Instructions

1. Read the full spec and this scope; confirm all dependency tasks are completed and committed.
2. Use the designated worktree; verify every referenced import/signature and update stale contracts before code changes.
3. Update only `sdd/tasks/index/contracts-card-ontology.json` assignment/status timestamps for this task, never the historical monolithic index.
4. Implement only owned files, validate acceptance criteria and record real results.
5. Move this artifact to `sdd/tasks/completed/TASK-3043-contracts-authorized-retrieval.md` when complete, update its per-spec index entry, and commit implementation plus SDD state.
6. Fill in the completion note; unavailable external acceptance must remain pending rather than being reported as successful.

## Completion Note

Pending execution. Record executor, completion date, implementation summary, validation evidence and deviations when this task is completed.
