# TASK-3044: Versioned citation and claim verification gate

**Feature**: FEAT-539 - Contracts Card & Ontology
**Spec**: `sdd/specs/contracts-card-ontology.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-3029, TASK-3033, TASK-3043
**Assigned-to**: unassigned
**Parallel**: true
**Parallelism notes**: Execute in core worktree feat-FEAT-539-contracts-card-ontology. May run alongside ready tasks with disjoint owned files after all dependencies complete. No concurrent edits to any file listed below. M8 commits must be integrated into the core lane before the delta job. Packaging task alone owns pyproject.toml/uv.lock; DOCX task alone owns bookstore/library.py.

---

## Context

Implements M10 in spec §3 and the corresponding normative §2 behavior. Covers AC10; full feature acceptance remains governed by spec §§4–5.

## Scope

- Implement contracts-specific deterministic draft/citation verifier using only this request authorized dossier and exact archived evidence.
- Require contract/version/hash/node/page identity, nonempty verbatim quote, unretired evidence and trusted title/page/verification metadata. Carry broad node suppression through unchanged-excerpt mappings.
- Represent claim-to-citation support explicitly and remove unsupported claims with rejected citations; unrelated surviving evidence cannot rescue free prose.
- Derive verified/mixed/extracted provenance (empty evidence => extracted); preserve visible stale state. Zero surviving lookup citations becomes not_found; enforce every answer-kind invariant.

**NOT in scope**: implementation owned by other tasks, new dependencies beyond the separately assigned approved rapidfuzz extra, verification UI, OCR, automatic messages, new scheduler or transport infrastructure. Do not modify generic ontology/GraphIndex APIs to bypass the contracts adapters.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/contracts/verifier.py` | CREATE | Task-owned deliverable |
| `packages/ai-parrot-tools/tests/contracts/test_verifier.py` | CREATE | Focused verification / fixtures |

## Codebase Contract (Anti-Hallucination)

Relevant spec references were re-read on 2026-09-09 against dev `7ba8ef6b0`. These are source-verified contracts, not a claim that optional integrations were connected. New dependency interfaces come from spec §2 and must be verified after their owning tasks commit.

### Verified Imports

```python
from parrot.knowledge.pageindex.content_store import NodeContentStore  # packages/ai-parrot/src/parrot/knowledge/pageindex/content_store.py:197
```

### Existing Signatures to Use

| Existing callable | Verified signature / constraint | Source |
|---|---|---|
| loader_for | (self, tree_name: str) -> Callable[[str], Optional[str]]; synchronous body reader | packages/ai-parrot/src/parrot/knowledge/pageindex/content_store.py:197 |

### Does NOT Exist

- All task CREATE paths and contracts public interfaces are new at decomposition time; do not import unfinished dependency outputs.
- No SQLite catalog, generic BookCard inheritance or scheduler integration is authorized.
- Unmodified OntologyRAGMixin does not enforce the required pre-read authorization ordering; hybrid_concept_match targets Concepts, not Contracts.
- BOE SpanVerifier is domain-specific and the legal crew builder is inspection-only, not an executable contracts runner.

## Implementation Notes

Use strict type hints, Pydantic v2, async entrypoints, black/isort and lazy optional dependencies with actionable errors. Offload synchronous parsing/content reads. Keep core independent of parrot_tools and parrot.scheduler. Validate configured identifiers and bind user SQL/AQL values. Treat source documents as untrusted data. Re-read dependency contracts and owned files before editing; do not overwrite another worker's changes.

### Dependency interfaces

- `TASK-3029`: Catalog aliases, audit, sources and publication state; inspect its completed artifact and committed interface before use.
- `TASK-3033`: Immutable tenant and version-scoped evidence storage; inspect its completed artifact and committed interface before use.
- `TASK-3043`: Deterministic authorized retrieval and typed pattern binds; inspect its completed artifact and committed interface before use.

## Acceptance Criteria

- [ ] Unknown node, wrong version/hash/page, empty/mismatched quote, foreign dossier, retirement and renumbered unchanged excerpt are rejected.
- [ ] Orphan claims disappear even when another citation passes; zero survivors becomes not_found.
- [ ] Mixed/stale provenance and handoff evidence are checked consistently; verifier never calls an LLM.
- [ ] Changes stay within owned files, imports are verified and appropriate focused validation is recorded.

## Test Specification

1. Unknown node, wrong version/hash/page, empty/mismatched quote, foreign dossier, retirement and renumbered unchanged excerpt are rejected.
2. Orphan claims disappear even when another citation passes; zero survivors becomes not_found.
3. Mixed/stale provenance and handoff evidence are checked consistently; verifier never calls an LLM.

Validation: `uv run pytest packages/ai-parrot-tools/tests/contracts/test_verifier.py -q`

Store execution logs in `artifacts/logs/task-3044.log`. Use frozen dates, synthetic sources, fake structured adapters and explicit failure injection. Live Postgres suites require explicit `GRAPHINDEX_PG_DSN` and temporary schemas; no default DSN fallback. Arango suites require explicit test configuration. Missing services skip only those suites and do not count as live acceptance. Do not fabricate benchmark results or pilot signoff.

## Agent Instructions

1. Read the full spec and this scope; confirm all dependency tasks are completed and committed.
2. Use the designated worktree; verify every referenced import/signature and update stale contracts before code changes.
3. Update only `sdd/tasks/index/contracts-card-ontology.json` assignment/status timestamps for this task, never the historical monolithic index.
4. Implement only owned files, validate acceptance criteria and record real results.
5. Move this artifact to `sdd/tasks/completed/TASK-3044-contracts-citation-verifier.md` when complete, update its per-spec index entry, and commit implementation plus SDD state.
6. Fill in the completion note; unavailable external acceptance must remain pending rather than being reported as successful.

## Completion Note

Pending execution. Record executor, completion date, implementation summary, validation evidence and deviations when this task is completed.
