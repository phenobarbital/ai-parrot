# TASK-3060: Compile safe metadata and parent filters

**Feature**: FEAT-542 - Local LanceDB Vector, Full-Text and Hybrid Search
**Spec**: `sdd/specs/lancedb-vector-store.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h) — target 3 hours
**Depends-on**: TASK-3059
**Assigned-to**: unassigned
**Parallel**: true
**Parallelism notes**: Can run alongside lifecycle and origin work after models. File ownership is disjoint from other eligible parallel tasks; dependencies still gate start.
**Acceptance coverage**: AC5

---

## Context

M1 shared prefilter compiler ensures vector, FTS, hybrid and deletion never disagree about selector semantics.

The spec is marked approved. Its checked section 8 answers require fully offline agent operation after provisioning, concurrent independent writers, graph federation only, and whole-origin failure; they override older draft assumptions. TASK-3057 must reconcile the spec and prove the SDK/offline/concurrency contracts before dependent implementation begins. Do not reinstate single-writer-only or storage-only-offline behavior.

---

## Scope

- Compile AND mappings with exact typed equality, homogeneous scalar membership and null/absent matching; empty IN matches nothing; reject mixed/null-containing lists, nested operators and unknown fields.
- Add the documented parent exclusion unless include_parents=True: explicit parent markers always win, absent markers remain searchable.
- Use only declared physical identifiers and correctly encoded literals; reject raw SQL, unknown operational expressions, NUL and non-finite values.
- Expose a separate deletion path requiring a non-empty explicit selector and omitting only the search-specific parent predicate. Produce one final prefilter string for all query legs.

**NOT in scope**: SDK query builders, delete execution, global authorization semantics and arbitrary SQL support.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-embeddings/src/parrot/stores/lancedb_filters.py` | CREATE | Declared-field typed predicate compiler |
| `packages/ai-parrot-embeddings/tests/test_lancedb_filters.py` | CREATE | Filter and hostile-input matrix |

Ownership is exclusive to this task for the listed responsibility. You are not alone in the codebase: preserve others' changes, do not revert unrelated edits, and accommodate completed dependency work. New files listed here are proposed outputs, not already-verified imports. Shared backend files are deliberately sequenced by dependencies.

---

## Codebase Contract (Anti-Hallucination)

Verified by source inspection on `dev` on 2026-09-10. This is not a claim of runtime SDK/import testing. Re-read relevant definitions before implementation; if paths/signatures changed, update the contract first. Symbols delivered by dependencies must be verified in their committed files before import.

### Verified Imports

```python
from pydantic import BaseModel, Field  # packages/ai-parrot/src/parrot/stores/models.py:13
from parrot.models.stores import SearchResult  # packages/ai-parrot-tools/src/parrot_tools/multistoresearch/origins/vector.py:11
```

### Existing Signatures to Use

| Verified source | Existing contract |
|---|---|
| `packages/ai-parrot/src/parrot/stores/models.py:19` | Document(page_content: str, metadata: Dict[str, Any]); metadata defaults to an empty mapping. |
| `packages/ai-parrot/src/parrot/models/stores.py:46` | SearchResult requires id: str, content: str, score: float; distance at :74 returns score unchanged. |
| `packages/ai-parrot/src/parrot/models/stores.py:79` | OriginHit has optional id/score, content/metadata, origin, origin_kind and native_rank >= 1. |
| `packages/ai-parrot/src/parrot/models/stores.py:162` | StoreConfig has embedding_model, dimension=768, metric_type='COSINE', index_type='IVF_FLAT', table/schema/dsn and extra. |
| `packages/ai-parrot/src/parrot/stores/abstract.py:245` | async similarity_search(self, query: str, collection: Union[str, None] = None, limit: int = 2, similarity_threshold: float = 0.0, search_strategy: str = 'auto', metadata_filters: Union[dict, None] = None, include_parents: bool = False, **kwargs) -> list. |
| `packages/ai-parrot/src/parrot/stores/abstract.py:258` | Documented parent exclusion: is_full_document=True OR document_type in ('parent', 'parent_chunk'); unmarked legacy rows remain eligible. |
| `packages/ai-parrot/src/parrot/models/stores.py:74` | SearchResult.distance returns score without conversion; FTS compatibility must not pretend BM25 is a vector distance. |

### Does NOT Exist

- LanceDBConfig, LanceDBHybridHit and lancedb_models.py are new task deliverables, not current core types.
- A shared HybridSearchResult or globally comparable origin score does not exist.
- No backend-neutral hybrid_search contract is defined by AbstractStore.
- fulltext_search and typed LanceDB hybrid results are new backend contracts, not inherited query implementations.
- New helpers listed in dependency tasks are not pre-existing repository APIs. Use the gate/completion contracts, then verify their actual implementations.
- No guarantee of fully offline inference or concurrent-process correctness follows merely from opening a local LanceDB directory.

---

## Implementation Notes

### Pattern to Follow

Can run alongside lifecycle and origin work after models. Verify any new SDK expression API through gate evidence instead of inventing parameter binding.

Use the existing contracts above without changing unrelated shared behavior. Keep async public operations non-blocking, strict type hints, Pydantic structured records and black/isort formatting. Keep SDK access inside the embeddings backend, never in the origin adapter.

### Key Constraints

- Complete only this task's deliverable; do not implement later tasks opportunistically.
- Never remove or silently downgrade approved offline or concurrent-writer requirements.
- No schema overwrite, broad deletion, automatic version pruning, remote fallback or new storage server.
- Preserve caller documents and shared embedding ownership. Do not log document text, vectors, credentials or filter values.
- Respect optional dependency boundaries; follow approval policy before introducing unapproved packages.
- Capture test commands, dependency versions and outcomes under `artifacts/logs/TASK-3060-lancedb.log`; real-model/benchmark evidence must distinguish provisioning from execution.

### References in Codebase

The task-specific locations above and the spec's sections 2, 4, 5, 6 and 8 are authoritative. Read any additional implementation API before relying on it; do not guess builder methods from a class name.

---

## Acceptance Criteria

- [ ] U2 matrix covers every documented filter shape and parent marker combination.
- [ ] Unsupported filter inputs fail before any SDK operation.
- [ ] Vector, FTS and hybrid callers can reuse exactly one conjunctive predicate.
- [ ] Delete predicate construction cannot silently become delete-all.
- [ ] Tests in this task's Test Specification pass; failures are not hidden by mocks, skips or relaxed assertions where real SDK/model execution is required.
- [ ] Scope-owned code passes formatting/type checks appropriate to the repository, and the completion note records actual commands and evidence.

---

## Test Specification

| Test | Required behavior |
|---|---|
| `test_filter_type_and_null_matrix` | Exact types, membership, empty lists and missing/null projection. |
| `test_parent_visibility_matrix` | Parent flags/types excluded even with is_chunk=True; legacy rows remain. |
| `test_filter_injection_rejected_or_escaped` | Quotes, SQL-like literal values and malicious identifiers cannot broaden scope. |
| `test_empty_delete_filter_rejected` | Destructive empty selectors are never compiled as unrestricted deletion. |

Intended command after dependencies are implemented:

```bash
uv run pytest packages/ai-parrot-embeddings/tests/test_lancedb_filters.py -v
```

These are test contracts, not executed test results or placeholder production implementations. Use pytest-asyncio for async cases, temporary directories for datasets, bounded subprocess joins, and explicit process barriers for race tests. Reuse the deterministic 8-D fixture unless real local model evidence is explicitly required. Required feature tests may not all skip just because the SDK or assets were omitted.

---

## Agent Instructions

1. Read the spec and the approved-answer precedence in this task.
2. Work only inside the FEAT-542 feature worktree. Verify dependency tasks are `done` in `sdd/tasks/index/lancedb-vector-store.json` and their task files are under `sdd/tasks/completed/`.
3. Re-verify every needed import/signature and dependency-produced helper before writing code.
4. Update only this task entry in `sdd/tasks/index/lancedb-vector-store.json` to `in-progress`, with assignment/start timestamps. Never use the historical monolithic index.
5. Outline the implementation plan and uncertainties, then implement within the listed file ownership. Preserve unrelated work.
6. Run all task acceptance checks and save logs; unresolved gate failures prevent completion.
7. Move this task to `sdd/tasks/completed/TASK-3060-lancedb-safe-metadata-filters.md`, update its per-spec entry to `done` with completion time and file path, and fill the completion note.
8. Commit only scoped implementation plus this task's SDD state. Follow the execution/review workflow before pushing.

---

## Completion Note

**Completed by**: not started
**Date**: not completed
**Notes**: Pending execution; no implementation or acceptance tests run during task decomposition.
**Deviations from spec**: The checked answers supersede stale prose; TASK-3057 reconciles that discrepancy before implementation.
