# TASK-3064: Implement exact cosine search and tool-compatible thresholds

**Feature**: FEAT-542 — Local LanceDB Vector, Full-Text and Hybrid Search
**Spec**: `sdd/specs/lancedb-vector-store.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h) — target 3 hours
**Depends-on**: TASK-3063
**Assigned-to**: unassigned
**Parallel**: false
**Parallelism notes**: Sequential/gated task. Sequential backend writer after mutation task. Preserve SearchResult.distance as raw score; the tool's input threshold is minimum similarity, not an output-score reinterpretation.
**Acceptance coverage**: AC2, AC5, AC6

---

## Context

First M3 retrieval task; complete the required vector-store abstract surface before public registration.

The spec is marked approved. Its checked section 8 answers require fully offline agent operation after provisioning, concurrent independent writers, graph federation only, and whole-origin failure; they override older draft assumptions. TASK-3057 must reconcile the spec and prove the SDK/offline/concurrency contracts before dependent implementation begins. Do not reinstate single-writer-only or storage-only-offline behavior.

---

## Scope

- Implement the exact inherited similarity_search signature with positive integer limits, blank-query handling, missing-collection errors and lazy query embedding.
- Apply the shared collection/metadata/parent prefilter before limiting candidates and execute exact COSINE/FLAT only.
- Return SearchResult with raw cosine distance and namespaced identity/provenance. Convert enabled minimum-similarity thresholds to distance predicates; distinguish base zero-disabled threshold from explicit tool score_threshold=0.
- Accept only documented aliases/kwargs, combine both enabled thresholds by strictness, and explicitly reject unsupported strategies, metrics/custom columns and MMR.
- Verify the backend is now concrete and all AbstractStore abstract operations are implemented; do not register it here.

**NOT in scope**: FTS/hybrid, ANN, MMR implementation, shared score-model changes and dispatch editing.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-embeddings/src/parrot/stores/lancedb.py` | MODIFY | Exact similarity search, result conversion and explicit MMR rejection |
| `packages/ai-parrot-embeddings/tests/test_lancedb_vector_search.py` | CREATE | Vector contracts and tool argument compatibility |

Ownership is exclusive to this task for the listed responsibility. You are not alone in the codebase: preserve others' changes, do not revert unrelated edits, and accommodate completed dependency work. New files listed here are proposed outputs, not already-verified imports. Shared backend files are deliberately sequenced by dependencies.

---

## Codebase Contract (Anti-Hallucination)

Verified by source inspection on `dev` on 2026-09-10. This is not a claim of runtime SDK/import testing. Re-read relevant definitions before implementation; if paths/signatures changed, update the contract first. Symbols delivered by dependencies must be verified in their committed files before import.

### Verified Imports

```python
from parrot.models.stores import SearchResult  # packages/ai-parrot-tools/src/parrot_tools/multistoresearch/origins/vector.py:11
from pydantic import BaseModel, Field  # packages/ai-parrot/src/parrot/stores/models.py:13
from parrot.stores import AbstractStore  # packages/ai-parrot-embeddings/tests/test_namespace_imports.py:151
```

### Existing Signatures to Use

| Verified source | Existing contract |
|---|---|
| `packages/ai-parrot/src/parrot/stores/abstract.py:245` | async similarity_search(self, query: str, collection: Union[str, None] = None, limit: int = 2, similarity_threshold: float = 0.0, search_strategy: str = 'auto', metadata_filters: Union[dict, None] = None, include_parents: bool = False, **kwargs) -> list. |
| `packages/ai-parrot/src/parrot/stores/abstract.py:258` | Documented parent exclusion: is_full_document=True OR document_type in ('parent', 'parent_chunk'); unmarked legacy rows remain eligible. |
| `packages/ai-parrot/src/parrot/models/stores.py:74` | SearchResult.distance returns score without conversion; FTS compatibility must not pretend BM25 is a vector distance. |
| `packages/ai-parrot/src/parrot/stores/models.py:19` | Document(page_content: str, metadata: Dict[str, Any]); metadata defaults to an empty mapping. |
| `packages/ai-parrot/src/parrot/models/stores.py:46` | SearchResult requires id: str, content: str, score: float; distance at :74 returns score unchanged. |
| `packages/ai-parrot/src/parrot/models/stores.py:79` | OriginHit has optional id/score, content/metadata, origin, origin_kind and native_rank >= 1. |
| `packages/ai-parrot/src/parrot/models/stores.py:162` | StoreConfig has embedding_model, dimension=768, metric_type='COSINE', index_type='IVF_FLAT', table/schema/dsn and extra. |
| `packages/ai-parrot/src/parrot/stores/__init__.py:6` | supported_stores currently maps postgres, milvus, kb, faiss_store, arango and bigquery; preserve values including existing mismatches. |
| `packages/ai-parrot/src/parrot/interfaces/vector.py:42` | _get_database_store(self, store: dict) -> AbstractStore dynamically imports parrot.stores.{name}; passes store dict and embedding fields through. |
| `packages/ai-parrot/src/parrot/tools/vectorstoresearch.py:131` | _create_store(self) -> AbstractStore passes embedding_model/dimension/metric_type/index_type, table/schema/dsn and overlays StoreConfig.extra. |
| `packages/ai-parrot/src/parrot/tools/vectorstoresearch.py:184` | async _execute(self, query: str, limit: int = 10, score_threshold: Optional[float] = None, metadata_filters: Optional[Dict[str, Any]] = None, use_mmr: bool = False, lambda_mult: float = 0.5, **kwargs) -> Union[List[Dict[str, Any]], ToolResult]. |
| `packages/ai-parrot/src/parrot/tools/vectorstoresearch.py:211` | Search kwargs include table/schema, content_column='document', embedding_column='embedding', metadata_column='cmetadata', id_column='id'; similarity_search at :242, opt-in mmr_search at :239. |
| `packages/ai-parrot-embeddings/tests/test_store_backends_present.py:27` | Exact supported_stores assertion; satellite namespace initializer is forbidden at :49. |
| `packages/ai-parrot-embeddings/tests/test_namespace_imports.py:126` | Second exact supported_stores assertion; extend only the intentional key. |

### Does NOT Exist

- No backend-neutral hybrid_search contract is defined by AbstractStore.
- fulltext_search and typed LanceDB hybrid results are new backend contracts, not inherited query implementations.
- LanceDBConfig, LanceDBHybridHit and lancedb_models.py are new task deliverables, not current core types.
- A shared HybridSearchResult or globally comparable origin score does not exist.
- Adding a dispatch key does not add StoreType/adaptive-router support.
- MMR is not provided by the planned LanceDB v1 backend; it needs explicit unsupported behavior.
- New helpers listed in dependency tasks are not pre-existing repository APIs. Use the gate/completion contracts, then verify their actual implementations.
- No guarantee of fully offline inference or concurrent-process correctness follows merely from opening a local LanceDB directory.

---

## Implementation Notes

### Pattern to Follow

Sequential backend writer after mutation task. Preserve SearchResult.distance as raw score; the tool's input threshold is minimum similarity, not an output-score reinterpretation.

Use the existing contracts above without changing unrelated shared behavior. Keep async public operations non-blocking, strict type hints, Pydantic structured records and black/isort formatting. Keep SDK access inside the embeddings backend, never in the origin adapter.

### Key Constraints

- Complete only this task's deliverable; do not implement later tasks opportunistically.
- Never remove or silently downgrade approved offline or concurrent-writer requirements.
- No schema overwrite, broad deletion, automatic version pruning, remote fallback or new storage server.
- Preserve caller documents and shared embedding ownership. Do not log document text, vectors, credentials or filter values.
- Respect optional dependency boundaries; follow approval policy before introducing unapproved packages.
- Capture test commands, dependency versions and outcomes under `artifacts/logs/TASK-3064-lancedb.log`; real-model/benchmark evidence must distinguish provisioning from execution.

### References in Codebase

The task-specific locations above and the spec's sections 2, 4, 5, 6 and 8 are authoritative. Read any additional implementation API before relying on it; do not guess builder methods from a class name.

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block below to its declared
> path nearly verbatim, then complete every `# FILL IN:` marker. Blocks were derived from
> the spec's §2 New Public Interfaces and re-verified against the Codebase Contract above
> when this task was written. This is NOT the full implementation: business-logic branches,
> edge cases and test bodies are `FILL IN` stubs by design. Never change a signature, class
> name, or file path the blueprint fixes.

### Steps (in order)
1. Validate parameters before generating any embedding — *why*: spec §2 says a blank query returns `[]` "after parameter validation, without embedding generation"; embedding first burns a model call for a request that was always invalid.
2. Return raw cosine distance as `score`, never a similarity — *why*: `SearchResult.distance` returns `score` unchanged (`packages/ai-parrot/src/parrot/models/stores.py:74`), so converting here would silently redefine `distance` for every existing consumer.
3. Translate thresholds into a distance predicate, do not rescale results — *why*: spec §2 requires `distance <= 1 - threshold` with scores still reported as distances.
4. Apply the shared prefilter before the candidate limit — *why*: excluded parents must not consume the requested budget (spec §4 I3).

### `packages/ai-parrot-embeddings/src/parrot/stores/lancedb.py` (MODIFY)
```python
# occurrences: 1 expected — verify after TASK-3062 lands:
#   grep -c 'TASK-3064 owns vector search' packages/ai-parrot-embeddings/src/parrot/stores/lancedb.py
# REPLACE the `similarity_search` stub TASK-3062 declared (keep the signature verbatim)

    async def similarity_search(
        self,
        query: str,
        collection: Union[str, None] = None,
        limit: int = 2,
        similarity_threshold: float = 0.0,
        search_strategy: str = "auto",
        metadata_filters: Union[dict, None] = None,
        include_parents: bool = False,
        **kwargs: Any,
    ) -> list:
        """Exact cosine search. Scores are RAW DISTANCES: lower is better.

        Raises:
            ValueError: non-positive/boolean/non-integer limit, out-of-range threshold,
                or an unsupported ``search_strategy``.
            LookupError: the collection does not exist.
        """
        # FILL IN, in this order:
        #   1. validate limit (positive int, bool rejected), search_strategy ("auto" only),
        #      and thresholds; blank query -> [] with NO embedding call
        #   2. compile combine(compile_metadata_filter(...), parent clause unless include_parents)
        #   3. await self._ensure_provider(); embed_query
        #   4. run the exact (FLAT) query with the single prefilter applied BEFORE the limit
        #   5. map rows to SearchResult with score = raw cosine distance, id = namespaced_id(...),
        #      and metadata['_lancedb'] = {collection, record_id, mode: 'vector',
        #      score_kind: 'cosine_distance', higher_is_better: False}
        # — bounded by spec §2 "Search and Score Contracts", §2 Filters, AC5
        raise NotImplementedError

    def _distance_ceiling(self, similarity_threshold: float, score_threshold: float | None) -> float | None:
        """Translate similarity thresholds into a maximum cosine distance."""
        # FILL IN: similarity_threshold == 0.0 disables thresholding (base compatibility);
        # nonzero must lie in (0, 1]; the tool's score_threshold means minimum cosine
        # similarity in [0, 1]; when both are supplied use the STRICTER enabled one;
        # return 1 - threshold — bounded by spec §2 threshold paragraph, AC5
        raise NotImplementedError
```
**Why this shape**: `_distance_ceiling` is a separate pure helper because the threshold rule is the subtlest paragraph in the spec — two differently-defined inputs, one disabled sentinel, and a "stricter wins" tie-break — and it is far cheaper to unit-test in isolation than through a live query. The `_lancedb` metadata block is written here rather than in the origin so that provenance survives even for callers that bypass the toolkit.

### `packages/ai-parrot-embeddings/tests/test_lancedb_vector_search.py` (CREATE)
```python
"""Vector contracts and tool-argument compatibility (FEAT-542, AC5)."""
from __future__ import annotations

import pytest

from parrot.stores.lancedb import LanceDBStore

pytestmark = pytest.mark.asyncio


class TestValidation:
    @pytest.mark.parametrize("limit", [0, -1, True, 1.5])
    async def test_invalid_limits_raise(self, tmp_path, limit):
        # FILL IN: bool must be rejected even though it is an int — bounded by spec §2
        raise NotImplementedError

    async def test_blank_query_returns_empty_without_embedding(self, tmp_path):
        # FILL IN: assert the provider call counter stayed at 0 — bounded by spec §2
        raise NotImplementedError

    async def test_unsupported_search_strategy_rejected(self, tmp_path):
        # FILL IN — bounded by spec §2 ("auto" uses exact search)
        raise NotImplementedError


class TestScores:
    async def test_score_is_raw_cosine_distance_lower_is_better(self, tmp_path):
        # FILL IN — bounded by spec §2 score contracts
        raise NotImplementedError

    async def test_distance_alias_is_unchanged(self, tmp_path):
        # FILL IN: SearchResult.distance == score — bounded by models/stores.py:74
        raise NotImplementedError


class TestThresholds:
    @pytest.mark.parametrize("similarity,score_threshold,expected_ceiling", [...])  # FILL IN
    def test_distance_ceiling_rules(self, similarity, score_threshold, expected_ceiling):
        # FILL IN: 0.0 disables; out-of-range raises; stricter wins — bounded by AC5
        raise NotImplementedError


class TestFilters:
    async def test_excluded_parents_do_not_consume_the_candidate_budget(self, tmp_path):
        # FILL IN: prefilter applied before limit — bounded by spec §4 I3, AC5
        raise NotImplementedError

    async def test_empty_collection_returns_empty_and_missing_raises(self, tmp_path):
        # FILL IN: [] vs LookupError — bounded by spec §2 Filters
        raise NotImplementedError


class TestUnsupported:
    async def test_mmr_search_raises_notimplementederror(self, tmp_path):
        # FILL IN: message explains v1 is exact-search only — bounded by spec §2
        raise NotImplementedError
```
**Why this shape**: `test_distance_alias_is_unchanged` guards the one cross-cutting invariant this task could break for every other backend's consumers; `test_excluded_parents_do_not_consume_the_candidate_budget` is the only way to tell a correct prefilter from a post-filter that silently returns fewer rows than asked.

### FILL IN checklist
- [ ] `lancedb.py::similarity_search` — the five ordered steps; bounded by AC5, spec §2 score contracts
- [ ] `lancedb.py::_distance_ceiling` — sentinel, range, stricter-wins; bounded by AC5
- [ ] `test_lancedb_vector_search.py` — all bodies and the threshold parametrize table; bounded by AC5
- [ ] Confirm the `similarity_search` signature matches `abstract.py:245` exactly before editing

---

## Acceptance Criteria

- [ ] Vector score and threshold contracts pass U5 and I3 vector cases.
- [ ] Metadata and parent scope are applied before candidate limits.
- [ ] The complete store can be instantiated without hacks or stubbed abstract methods.
- [ ] Vector operations fail explicitly without a usable configured embedder; no silent lexical fallback.
- [ ] Tests in this task's Test Specification pass; failures are not hidden by mocks, skips or relaxed assertions where real SDK/model execution is required.
- [ ] Scope-owned code passes formatting/type checks appropriate to the repository, and the completion note records actual commands and evidence.

---

## Test Specification

| Test | Required behavior |
|---|---|
| `test_cosine_neighbors_and_distance_alias` | Known vectors produce expected neighbor order and unchanged raw score/distance. |
| `test_threshold_boundaries_and_combination` | Base/tool thresholds including 0/1 and stricter combination behave exactly as documented. |
| `test_vector_prefilter_before_limit` | Excluded nearest parents/other-source rows do not consume result budget. |
| `test_search_validation_and_concrete_store` | Blank/empty/missing cases, aliases and explicit MMR error; no remaining abstract methods. |

Intended command after dependencies are implemented:

```bash
uv run pytest packages/ai-parrot-embeddings/tests/test_lancedb_vector_search.py packages/ai-parrot-embeddings/tests/test_lancedb_mutations.py -v
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
7. Move this task to `sdd/tasks/completed/TASK-3064-lancedb-cosine-vector-search.md`, update its per-spec entry to `done` with completion time and file path, and fill the completion note.
8. Commit only scoped implementation plus this task's SDD state. Follow the execution/review workflow before pushing.

---

## Completion Note

**Completed by**: not started
**Date**: not completed
**Notes**: Pending execution; no implementation or acceptance tests run during task decomposition.
**Deviations from spec**: The checked answers supersede stale prose; TASK-3057 reconciles that discrepancy before implementation.
