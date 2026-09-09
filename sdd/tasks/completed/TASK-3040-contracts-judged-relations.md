# TASK-3040: Explicit bounded relation judgements and invalidation

**Feature**: FEAT-539 - Contracts Card & Ontology
**Spec**: `sdd/specs/contracts-card-ontology.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-3029, TASK-3035, TASK-3038
**Assigned-to**: unassigned
**Parallel**: false
**Parallelism notes**: Execute in core worktree feat-FEAT-539-contracts-card-ontology. Run after listed dependencies; shared-file edits are serialized by this DAG. No concurrent edits to any file listed below. M8 commits must be integrated into the core lane before the delta job. Packaging task alone owns pyproject.toml/uv.lock; DOCX task alone owns bookstore/library.py.

---

## Context

Implements M7 in spec §3 and the corresponding normative §2 behavior. Covers AC8; full feature acceptance remains governed by spec §§4–5.

## Scope

- Implement deterministic same-counterparty/family/obligation-kind candidate sets with stable order/max_candidates and one structured call per source contract per batch.
- Implement relate_contracts and explicit ingest relation-stage wiring; persist all outcomes including none with model/rationale/confidence/source hashes. Reject unknown/self/cross-tenant endpoints and constrain references_obligation to cross-contract clauses.
- Canonicalize symmetric conflicts pairs and make either-direction traversal work. Invalidate changed-source edges, preserve judgement history and replace active result on force; no retrieval-time judgement.

**NOT in scope**: implementation owned by other tasks, new dependencies beyond the separately assigned approved rapidfuzz extra, verification UI, OCR, automatic messages, new scheduler or transport infrastructure. Do not modify generic ontology/GraphIndex APIs to bypass the contracts adapters.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/contracts/relations.py` | CREATE | Task-owned deliverable |
| `packages/ai-parrot/src/parrot/knowledge/contracts/library.py` | MODIFY | Task-owned deliverable |
| `packages/ai-parrot/tests/knowledge/contracts/test_relations.py` | CREATE | Focused verification / fixtures |

## Codebase Contract (Anti-Hallucination)

Relevant spec references were re-read on 2026-09-09 against dev `7ba8ef6b0`. These are source-verified contracts, not a claim that optional integrations were connected. New dependency interfaces come from spec §2 and must be verified after their owning tasks commit.

### Verified Imports

```python
from parrot.knowledge.ontology.graph_store import OntologyGraphStore  # packages/ai-parrot/src/parrot/knowledge/ontology/graph_store.py:34
```

### Existing Signatures to Use

| Existing callable | Verified signature / constraint | Source |
|---|---|---|
| execute_traversal | async (self, ctx: TenantContext, aql: str, bind_vars: dict or None = None, collection_binds: dict[str, str] or None = None) -> list[dict[str, Any]] | packages/ai-parrot/src/parrot/knowledge/ontology/graph_store.py:234 |
| upsert_nodes | async (self, ctx: TenantContext, collection: str, nodes: list[dict[str, Any]], key_field: str) -> UpsertResult; copies key field to _key | packages/ai-parrot/src/parrot/knowledge/ontology/graph_store.py:274 |
| create_edges | async (self, ctx: TenantContext, edge_collection: str, edges: list[dict[str, Any]]) -> int; UPDATE {} on duplicate endpoints | packages/ai-parrot/src/parrot/knowledge/ontology/graph_store.py:372 |
| edges_incident / remove_edge_by_triple | Edges keyed by source_id/target_id/kind, not just _from/_to | packages/ai-parrot/src/parrot/knowledge/ontology/graph_store.py:725; packages/ai-parrot/src/parrot/knowledge/ontology/graph_store.py:752 |
| Bookstore relation patterns | deterministic_relations(cards, *, now, ...), async judge_relations(adapter, card, candidates, *, model_name=""); book-specific models, precedent only | packages/ai-parrot/src/parrot/knowledge/bookstore/relations.py:141; packages/ai-parrot/src/parrot/knowledge/bookstore/relations.py:372 |

### New design interfaces (not existing imports)

Implement only this task’s scoped portion; sibling methods belong to their designated dependencies or follow-up tasks.

| Interface | Normative contract from spec §2 |
|---|---|
| ContractLibrary | async add_contract(source, *, source_uri, force=False), add_folder(folder, *, recursive=False, force=False), verify_card(contract_id, fields, *, user, expected_revision), refresh_card(contract_id, *, source=None), relate_contracts(contract_ids=None, *, force=False); ingest returns card-or-null + added/updated/skipped and an explicit reason in the report |

### Does NOT Exist

- All task CREATE paths and contracts public interfaces are new at decomposition time; do not import unfinished dependency outputs.
- No SQLite catalog, generic BookCard inheritance or scheduler integration is authorized.
- OntologyRefreshPipeline.run has no filters argument and no atomic multi-collection publish; create_edges does not update existing edge properties.
- PropertyDef has no datetime/nested-model type; RelationDef has no symmetric flag.

## Implementation Notes

Use strict type hints, Pydantic v2, async entrypoints, black/isort and lazy optional dependencies with actionable errors. Offload synchronous parsing/content reads. Keep core independent of parrot_tools and parrot.scheduler. Validate configured identifiers and bind user SQL/AQL values. Treat source documents as untrusted data. Re-read dependency contracts and owned files before editing; do not overwrite another worker's changes.

### Dependency interfaces

- `TASK-3029`: Catalog aliases, audit, sources and publication state; inspect its completed artifact and committed interface before use.
- `TASK-3035`: Verification and refresh preserve human decisions; inspect its completed artifact and committed interface before use.
- `TASK-3038`: Full-catalog graph reconciliation and retraction; inspect its completed artifact and committed interface before use.

## Acceptance Criteria

- [ ] Fake adapter verifies bounded calls, membership and endpoint rejection, symmetric pair identity and cross-contract obligation rules.
- [ ] Replay without force reuses eligible stored outcome, force appends history, and source hash changes invalidate stale edges.
- [ ] Ingest/explicit relate path is wired; deterministic retrieval never invokes judgement.
- [ ] Changes stay within owned files, imports are verified and appropriate focused validation is recorded.

## Test Specification

1. Fake adapter verifies bounded calls, membership and endpoint rejection, symmetric pair identity and cross-contract obligation rules.
2. Replay without force reuses eligible stored outcome, force appends history, and source hash changes invalidate stale edges.
3. Ingest/explicit relate path is wired; deterministic retrieval never invokes judgement.

Validation: `uv run pytest packages/ai-parrot/tests/knowledge/contracts/test_relations.py -q`

Store execution logs in `artifacts/logs/task-3040.log`. Use frozen dates, synthetic sources, fake structured adapters and explicit failure injection. Live Postgres suites require explicit `GRAPHINDEX_PG_DSN` and temporary schemas; no default DSN fallback. Arango suites require explicit test configuration. Missing services skip only those suites and do not count as live acceptance. Do not fabricate benchmark results or pilot signoff.

## Agent Instructions

1. Read the full spec and this scope; confirm all dependency tasks are completed and committed.
2. Use the designated worktree; verify every referenced import/signature and update stale contracts before code changes.
3. Update only `sdd/tasks/index/contracts-card-ontology.json` assignment/status timestamps for this task, never the historical monolithic index.
4. Implement only owned files, validate acceptance criteria and record real results.
5. Move this artifact to `sdd/tasks/completed/TASK-3040-contracts-judged-relations.md` when complete, update its per-spec index entry, and commit implementation plus SDD state.
6. Fill in the completion note; unavailable external acceptance must remain pending rather than being reported as successful.

## Completion Note

Completed 2026-09-09 by sdd-worker (Claude Opus 5).

**Implementation**: created `parrot/knowledge/contracts/relations.py` and wired
`ContractLibrary.relate_contracts`. `candidate_contracts` builds a deterministic,
bounded candidate set (shared counterparty, then contract family, then overlapping
obligation kinds, then contract id; `max_candidates` default 8).
`ContractRelationStage.relate` spends exactly **one** structured call per source
contract per batch, records every outcome including `none` — and explicitly records
`none` for candidates the judge did not answer, so replay does not re-ask — with
model, rationale, confidence and both endpoint source hashes. It rejects
self-judgements and any endpoint that was not one of the offered candidates (which is
also what blocks unknown/cross-tenant endpoints), and constrains
`references_obligation` to two obligations of *different* contracts, degrading an
invalid one to `none`. `conflicts_with` pairs are canonicalised so the symmetric
relation is stored once and traverses from either endpoint. Every run first calls
`invalidate_relations` for the source hash, so a refreshed document deactivates
judgements made against the old text (history is preserved, not deleted). Without
`force` an active judgement is skipped; with `force` a new judgement is appended and
the active result replaced. The library gained `relate_contracts(contract_ids,
force=False)` plus an opt-in `relate_on_ingest` flag — judgement is explicit and
never happens at retrieval time.

**Validation**: `pytest .../test_relations.py -q` -> 23 passed (whole contracts suite
473 passed, `artifacts/logs/task-3040.log`); ruff clean. A counting fake adapter pins
one call per source contract, candidate membership/ordering/bounding, self and
non-candidate endpoint rejection, the canonical symmetric pair traversable both ways,
cross-contract obligation validation, unknown outcomes degrading to `none`, batch
failure isolation, replay reuse vs `--force` history, source-hash invalidation, a
`none` verdict removing a previously active relation, the ingest wiring, and that
deterministic reads never invoke the judge.

**Deviations**: none.
