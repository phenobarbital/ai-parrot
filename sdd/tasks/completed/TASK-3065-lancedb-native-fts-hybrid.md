# TASK-3065: Implement model-free FTS and native hybrid search

**Feature**: FEAT-542 — Local LanceDB Vector, Full-Text and Hybrid Search
**Spec**: `sdd/specs/lancedb-vector-store.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h) — target 4 hours
**Depends-on**: TASK-3064
**Assigned-to**: unassigned
**Parallel**: false
**Parallelism notes**: Sequential/gated task. Last normal backend writer. Use exact APIs from the gate; an async function wrapping a synchronous SDK call without offloading is not sufficient.
**Acceptance coverage**: AC4, AC5, AC6

---

## Context

Complete M3 with lexical and native fusion retrieval over the same persisted table.

The spec is marked approved. Its checked section 8 answers require fully offline agent operation after provisioning, concurrent independent writers, graph federation only, and whole-origin failure; they override older draft assumptions. TASK-3057 must reconcile the spec and prove the SDK/offline/concurrency contracts before dependent implementation begins. Do not reinstate single-writer-only or storage-only-offline behavior.

---

## Scope

- Implement fulltext_search and hybrid_search with signatures fixed in spec section 2; retain explicit collection/filter/parent scope and validated limits.
- FTS must neither instantiate nor call the provider, including after reopening with stored embedding identity or with an unusable configured model.
- Use native FTS and explicit vector+query-text hybrid with the gate-proven SDK builders and one conjunctive prefilter across both legs.
- Map FTS to SearchResult carrying native BM25 metadata and its documented legacy alias; return LanceDBHybridHit for RRF with no distance alias.
- Consume `LanceDBHybridHit` exactly as TASK-3059 froze it. Spec §8 Q6 (design research S2, spec §9) leaves per-leg vector/lexical component scores undecided — do not add them here unilaterally. If the SDK's hybrid result carries pre-fusion score columns, record that fact in the completion note instead of surfacing it through the model.
- Any failed hybrid leg raises for that origin; no successful partial fallback. Confirm inserts after index creation, upserts and deletes are visible in all query modes without manual maintenance.

**NOT in scope**: Toolkit reranking changes, graph seed replacement, generic hybrid interfaces, silent fallback and destructive index maintenance.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-embeddings/src/parrot/stores/lancedb.py` | MODIFY | fulltext_search and hybrid_search |
| `packages/ai-parrot-embeddings/tests/test_lancedb_fts_hybrid.py` | CREATE | Real FTS/fusion/filter/freshness tests |

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
| `packages/ai-parrot/src/parrot/stores/abstract.py:326` | create_embedding(self, embedding_model: dict, **kwargs) uses registry.get_or_create_sync; arbitrary dict fields are not automatically forwarded (Matryoshka is explicitly forwarded). |
| `packages/ai-parrot/src/parrot/stores/abstract.py:383` | async generate_embedding(self, documents: List[Any]) -> List[Any] initializes a default provider if absent, then awaits embed_documents. |
| `packages/ai-parrot/src/parrot/stores/abstract.py:391` | _apply_contextual_augmentation(self, documents: list, _log: bool = True) -> list[str] mutates document.metadata['contextual_header']; use copies. |
| `packages/ai-parrot/src/parrot/embeddings/base.py:169` | async embed_documents(self, texts: List[str], batch_size: Optional[int] = None) -> List[List[float]]. |
| `packages/ai-parrot/src/parrot/embeddings/base.py:188` | async embed_query(self, text: str, as_nparray: bool = False) -> Union[List[float], List[np.ndarray]]; default is a single flat vector. |
| `packages/ai-parrot-embeddings/src/parrot/embeddings/huggingface.py:134` | SentenceTransformerModel.__init__(self, model_name: str, matryoshka: Optional[dict] = None, backend: Optional[str] = None, file_name: Optional[str] = None, **kwargs). |

### Does NOT Exist

- No backend-neutral hybrid_search contract is defined by AbstractStore.
- fulltext_search and typed LanceDB hybrid results are new backend contracts, not inherited query implementations.
- LanceDBConfig, LanceDBHybridHit and lancedb_models.py are new task deliverables, not current core types.
- A shared HybridSearchResult or globally comparable origin score does not exist.
- Calling base generate_embedding is not model-free lexical retrieval.
- Do not assume arbitrary offline/local_files_only fields in embedding_model reach the provider; verify forwarding before relying on them.
- New helpers listed in dependency tasks are not pre-existing repository APIs. Use the gate/completion contracts, then verify their actual implementations.
- No guarantee of fully offline inference or concurrent-process correctness follows merely from opening a local LanceDB directory.

---

## Implementation Notes

### Pattern to Follow

Last normal backend writer. Use exact APIs from the gate; an async function wrapping a synchronous SDK call without offloading is not sufficient.

Use the existing contracts above without changing unrelated shared behavior. Keep async public operations non-blocking, strict type hints, Pydantic structured records and black/isort formatting. Keep SDK access inside the embeddings backend, never in the origin adapter.

### Key Constraints

- Complete only this task's deliverable; do not implement later tasks opportunistically.
- Never remove or silently downgrade approved offline or concurrent-writer requirements.
- No schema overwrite, broad deletion, automatic version pruning, remote fallback or new storage server.
- Preserve caller documents and shared embedding ownership. Do not log document text, vectors, credentials or filter values.
- Respect optional dependency boundaries; follow approval policy before introducing unapproved packages.
- Capture test commands, dependency versions and outcomes under `artifacts/logs/TASK-3065-lancedb.log`; real-model/benchmark evidence must distinguish provisioning from execution.

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
1. Implement `fulltext_search` with no reference to the provider at all — *why*: AC6 requires FTS to neither construct nor invoke an embedding model, and the fixture's call counters will catch any touch.
2. Reuse the SAME compiled predicate object for both hybrid legs — *why*: spec §2 requires one conjunctive prefilter across vector, FTS and both hybrid components; building it twice invites drift.
3. Return `LanceDBHybridHit` from hybrid and `SearchResult` from FTS — *why*: spec §2 fixes both, and the asymmetry is deliberate: FTS keeps `SearchResult` only for existing adapter compatibility.
4. Raise on either failing leg; never fall back to the other — *why*: the §8 answer is whole-origin failure, and a silent single-leg fallback would return lexical-only results labelled as hybrid.

### `packages/ai-parrot-embeddings/src/parrot/stores/lancedb.py` (MODIFY)
```python
# occurrences: 1 expected each — verify after TASK-3062 lands:
#   grep -c 'TASK-3065 owns FTS' packages/ai-parrot-embeddings/src/parrot/stores/lancedb.py
#   grep -c 'TASK-3065 owns hybrid search' packages/ai-parrot-embeddings/src/parrot/stores/lancedb.py
# REPLACE both stubs TASK-3062 declared (keep the signatures verbatim)

    async def fulltext_search(
        self,
        query: str,
        collection: str | None = None,
        limit: int = 10,
        metadata_filters: dict[str, Any] | None = None,
        include_parents: bool = False,
        **kwargs: Any,
    ) -> list:
        """Native BM25 lexical search. Constructs no embedding model.

        Scores are native BM25 (higher is better). The inherited
        ``SearchResult.distance`` alias is therefore numerically BM25 and is NOT a
        distance — documented in spec §2 and in the user guide.
        """
        # FILL IN: validate params; compile the single prefilter; run native FTS; map to
        # SearchResult with metadata['_lancedb'] = {mode: 'fts', score_kind: 'bm25',
        # higher_is_better: True}. Do NOT reference self._ensure_provider anywhere in this
        # method — bounded by AC6, spec §2 score contracts
        raise NotImplementedError

    async def hybrid_search(
        self,
        query: str,
        collection: str | None = None,
        limit: int = 10,
        metadata_filters: dict[str, Any] | None = None,
        include_parents: bool = False,
        **kwargs: Any,
    ) -> list:
        """Native vector/FTS fusion. Returns ``LanceDBHybridHit``; no distance alias.

        Raises:
            Exception: whatever the SDK raises when either leg fails. There is no
                fallback to a single leg — a failed hybrid fails the whole call.
        """
        # FILL IN: validate params; compile the prefilter ONCE and pass the same predicate
        # to both legs; await self._ensure_provider() and embed_query for the vector leg;
        # supply the explicit query vector AND the original query text; retain the SDK's
        # RRF order; map to LanceDBHybridHit with score_kind='rrf', higher_is_better=True
        # and metadata['_lancedb'] = {mode: 'hybrid', score_kind: 'rrf'}.
        # Do NOT add per-leg component scores — spec §8 Q6 is undecided (spec §9 S2)
        # — bounded by spec §2 score contracts, AC5, AC7
        raise NotImplementedError
```
**Why this shape**: the "do not reference `_ensure_provider`" instruction is written into the FTS body because that single line is the difference between passing and failing AC6, and it is invisible from the signature. Compiling the predicate once and passing the same object to both legs is what makes "one prefilter" checkable in review rather than a claim. The Q6 note is repeated here because this is the method where an implementer would most naturally reach for component scores.

### `packages/ai-parrot-embeddings/tests/test_lancedb_fts_hybrid.py` (CREATE)
```python
"""Real FTS, fusion, filter and freshness tests (FEAT-542, AC5/AC6/AC7)."""
from __future__ import annotations

import pytest

from parrot.stores.lancedb import LanceDBStore
from parrot.stores.lancedb_models import LanceDBHybridHit

pytestmark = pytest.mark.asyncio


class TestModelFreeLexicalPath:
    async def test_fts_never_constructs_or_invokes_a_provider(self, tmp_path):
        # FILL IN: provider factory that raises if called + counters at 0 — bounded by AC6
        raise NotImplementedError

    async def test_fts_works_on_a_reopen_with_no_provider_configured(self, tmp_path):
        # FILL IN: reopen reads the stored identity without constructing the model
        # — bounded by spec §2 config paragraph, AC6
        raise NotImplementedError


class TestScores:
    async def test_fts_scores_are_bm25_higher_is_better(self, tmp_path):
        # FILL IN — bounded by spec §2 score contracts
        raise NotImplementedError

    async def test_hybrid_returns_hybrid_hits_without_a_distance_alias(self, tmp_path):
        # FILL IN: isinstance LanceDBHybridHit; no 'distance' attribute — bounded by spec §2
        raise NotImplementedError

    async def test_hybrid_retains_sdk_rrf_order(self, tmp_path):
        # FILL IN: native_rank order preserved, not re-sorted — bounded by AC7
        raise NotImplementedError


class TestRetrievalMatrix:
    async def test_lexical_only_identifier_and_semantic_only_neighbour_both_eligible(self, tmp_path):
        # FILL IN: ZXQ731 and the semantic neighbour from lancedb_fixtures.corpus()
        # — bounded by spec §4 I3
        raise NotImplementedError

    async def test_one_prefilter_applies_to_both_hybrid_legs(self, tmp_path):
        # FILL IN — bounded by spec §2 Filters
        raise NotImplementedError

    async def test_rows_added_after_index_creation_are_visible(self, tmp_path):
        # FILL IN — bounded by spec §7 "FTS index freshness after writes", AC5
        raise NotImplementedError


class TestFailure:
    async def test_failing_leg_raises_and_never_falls_back(self, tmp_path):
        # FILL IN: assert no partial/lexical-only result is returned — bounded by AC7
        raise NotImplementedError
```
**Why this shape**: `test_fts_works_on_a_reopen_with_no_provider_configured` is the acceptance-shaped version of AC6 — a counter-based test passes even when the model is constructed and simply unused, but a reopen with no provider configured cannot.

### FILL IN checklist
- [ ] `lancedb.py::fulltext_search` — no provider reference anywhere in the body; bounded by AC6
- [ ] `lancedb.py::hybrid_search` — one shared predicate, explicit vector + text, SDK order retained; bounded by AC5/AC7
- [ ] `test_lancedb_fts_hybrid.py` — all nine bodies; bounded by AC5/AC6/AC7
- [ ] Do NOT add per-leg component scores to `LanceDBHybridHit`; bounded by spec §8 Q6
- [ ] Record in the completion note whether the SDK exposed pre-fusion score columns; bounded by spec §9 S2

---

## Acceptance Criteria

- [ ] Native FTS and hybrid pass real-SDK tests and preserve raw score direction/provenance.
- [ ] Model-free lexical reopening passes I5 with zero embedding construction/inference calls.
- [ ] All-mode visibility and filtering pass I3/I4; hybrid errors propagate.
- [ ] Full backend suite passes without modifying core result semantics.
- [ ] Tests in this task's Test Specification pass; failures are not hidden by mocks, skips or relaxed assertions where real SDK/model execution is required.
- [ ] Scope-owned code passes formatting/type checks appropriate to the repository, and the completion note records actual commands and evidence.

---

## Test Specification

| Test | Required behavior |
|---|---|
| `test_fts_no_model_construction_after_reopen` | Lexical identifier resolves with provider constructor/inference rigged to fail. |
| `test_hybrid_lexical_and_semantic_candidates` | Known lexical-only and semantic-only matches are eligible in native fusion. |
| `test_all_modes_share_prefilter_and_parent_rules` | All filter/parent combinations enforced before per-leg limits. |
| `test_all_modes_follow_upsert_delete_and_reopen` | Index freshness and mutation visibility using real SDK. |
| `test_failed_hybrid_leg_raises` | No empty success or vector-only fallback when FTS/model fails. |

Intended command after dependencies are implemented:

```bash
uv run pytest packages/ai-parrot-embeddings/tests/test_lancedb_fts_hybrid.py packages/ai-parrot-embeddings/tests/test_lancedb_vector_search.py -v
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
7. Move this task to `sdd/tasks/completed/TASK-3065-lancedb-native-fts-hybrid.md`, update its per-spec entry to `done` with completion time and file path, and fill the completion note.
8. Commit only scoped implementation plus this task's SDD state. Follow the execution/review workflow before pushing.

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet 5)
**Date**: 2026-09-10
**Notes**: Implemented `fulltext_search` with zero reference to `_ensure_provider`/`self._embedding_provider` anywhere in the method — verified with both a raising-provider fixture (would fail loudly if touched) and, more strongly per the blueprint's own note, a completely fresh `LanceDBStore` instance reopened with NO embedding configuration at all, which still resolves lexical queries. Maps rows to `SearchResult(score=row['_score'])` with `metadata['_lancedb']={mode:'fts', score_kind:'bm25', higher_is_better:True}`; `SearchResult.distance` stays the unchanged (BM25, not a distance) alias per spec.

Implemented `hybrid_search` compiling ONE `combine(compile_metadata_filter(...), parent_exclusion_clause())` predicate and applying it via a SINGLE `.where()` call on the chained `table.query().nearest_to(vector).distance_type("cosine").nearest_to_text(query)` builder. Verified directly against the real SDK before writing the store code that one trailing `.where()` filters BOTH legs (not just the vector leg) — confirmed empirically, not assumed from documentation alone. Maps rows to `LanceDBHybridHit(score=row['_relevance_score'], score_kind='rrf', higher_is_better=True)` in the SDK's native order (1-based `native_rank` recorded, never re-sorted). Neither leg's failure is caught — no fallback, per spec §8.

`test_lancedb_fts_hybrid.py`: 11 tests, all pass on first real run (`uv run pytest packages/ai-parrot-embeddings/tests/test_lancedb_fts_hybrid.py -v`, log at `artifacts/logs/TASK-3065-lancedb.log`), covering: model-free lexical path (both the raising-provider AND the no-provider-reopen cases), BM25/RRF score contracts, lexical-only (`ZXQ731`) + semantic-only candidates both eligible in fusion, one prefilter across both hybrid legs (verified for FTS too), parent exclusion in both FTS and hybrid, post-index-creation upsert/delete visibility with no manual maintenance, and failing-leg propagation with no partial success. Full lancedb-scoped suite (9 modules): 130/130 passing. `ruff check` clean.

**Spec §8 Q6 input (repeated from TASK-3057's gate, reconfirmed here at the call site)**: the pinned SDK's hybrid query result exposes ONLY the fused `_relevance_score` column — no pre-fusion `_distance`/`_score` component columns were present on any row returned by the real hybrid queries this task ran. `LanceDBHybridHit` was NOT widened; no per-leg component scores were added, per the blueprint's explicit instruction.
**Deviations from spec**: None.
