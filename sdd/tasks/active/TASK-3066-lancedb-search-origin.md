# TASK-3066: Add the LanceDB hybrid search origin

**Feature**: FEAT-542 — Local LanceDB Vector, Full-Text and Hybrid Search
**Spec**: `sdd/specs/lancedb-vector-store.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h) — target 3 hours
**Depends-on**: TASK-3059
**Assigned-to**: unassigned
**Parallel**: true
**Parallelism notes**: Can run alongside filter/coordinator/backend work after models. File ownership is disjoint from other eligible parallel tasks; dependencies still gate start.
**Acceptance coverage**: AC7

---

## Context

M4 can implement the frozen typed contract with fakes while store operations are developed independently.

The spec is marked approved. Its checked section 8 answers require fully offline agent operation after provisioning, concurrent independent writers, graph federation only, and whole-origin failure; they override older draft assumptions. TASK-3057 must reconcile the spec and prove the SDK/offline/concurrency contracts before dependent implementation begins. Do not reinstate single-writer-only or storage-only-offline behavior.

---

## Scope

- Implement LanceDBOrigin's documented constructor, vector/hybrid mode, fixed collection/filter scope, include_parents and optional timeout.
- Use kind VECTOR and supports_fts=True; search routes by configured mode, while fts_search always calls lexical search.
- Normalize IDs, content, unchanged scores, metadata and 1-based native ranks into OriginHit. Preserve RRF/BM25/distance score-kind annotations.
- Borrow rather than close the store; let errors and cancellation propagate to the toolkit. Keep SDK imports absent from origin import-time execution.
- Update only origin exports; do not modify toolkit ranking, graph adapter or existing VectorStoreOrigin.

**NOT in scope**: SDK queries, graph construction, backend lifecycle, global fallback and generic hybrid adapter design.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/multistoresearch/origins/lancedb.py` | CREATE | Explicit vector/hybrid origin and FTS route |
| `packages/ai-parrot-tools/src/parrot_tools/multistoresearch/origins/__init__.py` | MODIFY | Export LanceDBOrigin without SDK import |
| `packages/ai-parrot-tools/tests/multistoresearch/test_lancedb_origin.py` | CREATE | Contract and lifecycle unit tests |

Ownership is exclusive to this task for the listed responsibility. You are not alone in the codebase: preserve others' changes, do not revert unrelated edits, and accommodate completed dependency work. New files listed here are proposed outputs, not already-verified imports. Shared backend files are deliberately sequenced by dependencies.

---

## Codebase Contract (Anti-Hallucination)

Verified by source inspection on `dev` on 2026-09-10. This is not a claim of runtime SDK/import testing. Re-read relevant definitions before implementation; if paths/signatures changed, update the contract first. Symbols delivered by dependencies must be verified in their committed files before import.

### Verified Imports

```python
from parrot.models import OriginHit, SearchOriginKind  # packages/ai-parrot-tools/src/parrot_tools/multistoresearch/origins/vector.py:10
from parrot_tools.multistoresearch.origins.base import SearchOrigin  # packages/ai-parrot-tools/tests/multistoresearch/test_toolkit.py:6
from pydantic import BaseModel, Field  # packages/ai-parrot/src/parrot/stores/models.py:13
from parrot.models.stores import SearchResult  # packages/ai-parrot-tools/src/parrot_tools/multistoresearch/origins/vector.py:11
```

### Existing Signatures to Use

| Verified source | Existing contract |
|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/multistoresearch/origins/base.py:42` | async search(self, query: str, k: int) -> List[OriginHit]; optional async fts_search(self, query: str, k: int) -> List[OriginHit] at :54; adapters raise errors. |
| `packages/ai-parrot-tools/src/parrot_tools/multistoresearch/origins/vector.py:50` | VectorStoreOrigin.search calls self.store.similarity_search(query, limit=k); fts_search at :66 calls self.store.fulltext_search; _normalize at :90 preserves score/metadata and 1-based rank. |
| `packages/ai-parrot-tools/src/parrot_tools/multistoresearch/origins/__init__.py:7` | Current exports: SearchOrigin, VectorStoreOrigin, PageIndexOrigin, GraphIndexOrigin and ParrotWikiOrigin. |
| `packages/ai-parrot-tools/src/parrot_tools/multistoresearch/toolkit.py:65` | MultiStoreSearchToolkit.__init__(self, origins: List[SearchOrigin], k: int = 10, k_per_origin: int = 20, default_timeout: float = 30.0, bm25_weights: Optional[Dict[str, float]] = None, **kwargs: Any) -> None. |
| `packages/ai-parrot-tools/src/parrot_tools/multistoresearch/toolkit.py:85` | async store_search(self, query: str, k: Optional[int] = None) -> MultiSearchResponse; _run_origins at :268 isolates origin timeouts/errors. |
| `packages/ai-parrot-tools/src/parrot_tools/multistoresearch/toolkit.py:246` | _build_response reranks then deduplicates; BM25 at :359 leaves scores untouched; dedup at :390 uses ID then content hash. |
| `packages/ai-parrot/src/parrot/stores/models.py:19` | Document(page_content: str, metadata: Dict[str, Any]); metadata defaults to an empty mapping. |
| `packages/ai-parrot/src/parrot/models/stores.py:46` | SearchResult requires id: str, content: str, score: float; distance at :74 returns score unchanged. |
| `packages/ai-parrot/src/parrot/models/stores.py:79` | OriginHit has optional id/score, content/metadata, origin, origin_kind and native_rank >= 1. |
| `packages/ai-parrot/src/parrot/models/stores.py:162` | StoreConfig has embedding_model, dimension=768, metric_type='COSINE', index_type='IVF_FLAT', table/schema/dsn and extra. |

### Does NOT Exist

- LanceDBOrigin is new; the current VectorStoreOrigin has no hybrid mode.
- Toolkit merged_top_k does not preserve native RRF order; only grouped sections preserve origin order.
- LanceDBConfig, LanceDBHybridHit and lancedb_models.py are new task deliverables, not current core types.
- A shared HybridSearchResult or globally comparable origin score does not exist.
- New helpers listed in dependency tasks are not pre-existing repository APIs. Use the gate/completion contracts, then verify their actual implementations.
- No guarantee of fully offline inference or concurrent-process correctness follows merely from opening a local LanceDB directory.

---

## Implementation Notes

### Pattern to Follow

Can run alongside filter/coordinator/backend work after models. TYPE_CHECKING imports or a narrow typed duck contract must not require the SDK at runtime.

Use the existing contracts above without changing unrelated shared behavior. Keep async public operations non-blocking, strict type hints, Pydantic structured records and black/isort formatting. Keep SDK access inside the embeddings backend, never in the origin adapter.

### Key Constraints

- Complete only this task's deliverable; do not implement later tasks opportunistically.
- Never remove or silently downgrade approved offline or concurrent-writer requirements.
- No schema overwrite, broad deletion, automatic version pruning, remote fallback or new storage server.
- Preserve caller documents and shared embedding ownership. Do not log document text, vectors, credentials or filter values.
- Respect optional dependency boundaries; follow approval policy before introducing unapproved packages.
- Capture test commands, dependency versions and outcomes under `artifacts/logs/TASK-3066-lancedb.log`; real-model/benchmark evidence must distinguish provisioning from execution.

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
1. Follow `VectorStoreOrigin`'s normalization shape rather than inventing one — *why*: `origins/vector.py:90` is the verified provenance pattern the toolkit already expects, and a divergent shape breaks grouped ordering.
2. Borrow the store; never open or close it — *why*: spec §2 says the caller owns connection lifetime, and an origin that closes a shared store breaks every other origin using it.
3. Set `supports_fts = True` unconditionally — *why*: unlike `VectorStoreOrigin`, which computes it from a callable attribute (`origins/vector.py:48`), this backend always provides native FTS.
4. Export from `origins/__init__.py` WITHOUT importing the SDK — *why*: importing `parrot_tools.multistoresearch.origins` must not require `ai-parrot-embeddings[lancedb]` (AC1).
5. Let errors and cancellation propagate — *why*: the toolkit isolates per-origin failures itself; returning `[]` on failure would report a broken origin as an empty success (AC7).

### `packages/ai-parrot-tools/src/parrot_tools/multistoresearch/origins/lancedb.py` (CREATE)
```python
"""LanceDB search origin: vector or native hybrid, plus an explicit FTS route.

Borrows an already-configured ``LanceDBStore``. Never opens or closes it.
"""
from __future__ import annotations

from typing import Any, Literal

from parrot.models import OriginHit, SearchOriginKind  # verified: packages/ai-parrot-tools/src/parrot_tools/multistoresearch/origins/vector.py:10
from parrot.models.stores import SearchResult  # verified: .../origins/vector.py:11

from .base import SearchOrigin  # verified: .../origins/vector.py:13


class LanceDBOrigin(SearchOrigin):
    """Federates LanceDB vector or native hybrid results into the toolkit."""

    def __init__(
        self,
        store: Any,
        *,
        name: str = "lancedb",
        description: str = "",
        mode: Literal["vector", "hybrid"] = "hybrid",
        collection: str | None = None,
        metadata_filters: dict[str, Any] | None = None,
        include_parents: bool = False,
        timeout: float | None = None,
    ) -> None:
        # FILL IN: call super().__init__ per base.py's contract, then store the fixed scope.
        # kind = SearchOriginKind.VECTOR; supports_fts = True unconditionally (unlike
        # VectorStoreOrigin, which computes it at origins/vector.py:48)
        # — bounded by spec §2 New Public Interfaces
        raise NotImplementedError

    async def search(self, query: str, k: int) -> list[OriginHit]:
        """Run the configured mode with ``limit=k`` and this origin's fixed scope."""
        # FILL IN: dispatch to store.hybrid_search or store.similarity_search per self.mode,
        # passing collection/metadata_filters/include_parents; normalize; propagate errors
        # and cancellation — bounded by AC7
        raise NotImplementedError

    async def fts_search(self, query: str, k: int) -> list[OriginHit]:
        """Always route to lexical search, regardless of the configured mode."""
        # FILL IN: always store.fulltext_search — bounded by spec §2 New Public Interfaces
        raise NotImplementedError

    def _to_hits(self, results: list[Any]) -> list[OriginHit]:
        """Normalize backend results into ``OriginHit`` with native score and rank."""
        # FILL IN: preserve the native score and SDK order unchanged; native_rank is
        # 1-based (models/stores.py:101); carry the namespaced id and ALL metadata
        # including the '_lancedb' provenance block; set origin/origin_kind
        # — bounded by AC7 and the pattern at origins/vector.py:90
        raise NotImplementedError
```
**Why this shape**: `_to_hits` is one helper for both modes so vector and hybrid provenance cannot drift apart — the toolkit reranks the merged list with BM25 afterwards (`toolkit.py:359`), and the only thing preserving native meaning is the per-origin section plus the `_lancedb` block. `supports_fts` is a plain `True` rather than a computed property specifically because copying `VectorStoreOrigin`'s duck-typing check here would silently disable FTS if the store class is ever wrapped.

### `packages/ai-parrot-tools/src/parrot_tools/multistoresearch/origins/__init__.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'from .wiki import ParrotWikiOrigin' packages/ai-parrot-tools/src/parrot_tools/multistoresearch/origins/__init__.py)
# AFTER — insert below `from .wiki import ParrotWikiOrigin` (verified: packages/ai-parrot-tools/src/parrot_tools/multistoresearch/origins/__init__.py:11)
from .lancedb import LanceDBOrigin
```
**Why**: this import must stay SDK-free — `origins/lancedb.py` imports only `parrot.models` and `.base`, never `lancedb` or `parrot.stores.lancedb`, so importing the package works with no optional extra installed (AC1). If you find yourself needing a store import here, the type belongs in a `TYPE_CHECKING` block instead.

### `packages/ai-parrot-tools/src/parrot_tools/multistoresearch/origins/__init__.py` (MODIFY — `__all__`)
```python
# occurrences: 1 (verified: grep -c '    "ParrotWikiOrigin",' packages/ai-parrot-tools/src/parrot_tools/multistoresearch/origins/__init__.py)
# AFTER — insert below `    "ParrotWikiOrigin",` (verified: packages/ai-parrot-tools/src/parrot_tools/multistoresearch/origins/__init__.py:18)
    "LanceDBOrigin",
```
**Why**: `__all__` is a tuple here, not a list — keep the trailing comma and the existing order; do not re-sort the tuple, since other modules and tests read it positionally in no way but its contents are asserted elsewhere.

### `packages/ai-parrot-tools/tests/multistoresearch/test_lancedb_origin.py` (CREATE)
```python
"""LanceDBOrigin contract and lifecycle tests (FEAT-542, AC7). No SDK required."""
from __future__ import annotations

import pytest

from parrot_tools.multistoresearch.origins import LanceDBOrigin

pytestmark = pytest.mark.asyncio


class FakeStore:
    """Records calls; returns canned results. No SDK, no I/O."""
    # FILL IN: similarity_search / fulltext_search / hybrid_search recording their kwargs
    # — bounded by AC7


class TestDispatch:
    @pytest.mark.parametrize("mode,expected_call", [("vector", "similarity_search"),
                                                    ("hybrid", "hybrid_search")])
    async def test_search_dispatches_by_mode(self, mode, expected_call):
        # FILL IN — bounded by spec §2 New Public Interfaces
        raise NotImplementedError

    async def test_fts_search_always_routes_to_fulltext(self):
        # FILL IN: even when mode='vector' — bounded by spec §2
        raise NotImplementedError

    async def test_fixed_scope_is_forwarded(self):
        # FILL IN: collection, metadata_filters, include_parents reach the store
        raise NotImplementedError


class TestNormalization:
    async def test_native_score_and_order_unchanged_and_rank_is_one_based(self):
        # FILL IN — bounded by AC7, models/stores.py:101
        raise NotImplementedError

    async def test_provenance_metadata_survives(self):
        # FILL IN: the '_lancedb' block reaches OriginHit.metadata — bounded by AC7
        raise NotImplementedError


class TestLifecycleAndErrors:
    async def test_origin_never_closes_the_borrowed_store(self):
        # FILL IN: FakeStore.disconnect fails the test if called — bounded by spec §2
        raise NotImplementedError

    async def test_errors_and_cancellation_propagate(self):
        # FILL IN: assert no empty-success on backend failure — bounded by AC7
        raise NotImplementedError


def test_importing_origins_package_requires_no_sdk():
    # FILL IN: subprocess import with lancedb blocked — bounded by AC1
    raise NotImplementedError
```
**Why this shape**: `FakeStore` keeps this whole module SDK-free, which is what lets the task run in parallel with the backend work; `test_errors_and_cancellation_propagate` guards the failure mode that would otherwise look like a healthy empty result set in production.

### FILL IN checklist
- [ ] `origins/lancedb.py::__init__` — base wiring, `kind`, unconditional `supports_fts`; bounded by spec §2
- [ ] `origins/lancedb.py::search` / `fts_search` — mode dispatch and the always-FTS route; bounded by spec §2
- [ ] `origins/lancedb.py::_to_hits` — native score/order, 1-based rank, full metadata; bounded by AC7
- [ ] `test_lancedb_origin.py` — `FakeStore` plus all eight bodies; bounded by AC7/AC1
- [ ] Verify `SearchOrigin.__init__`'s real signature at `origins/base.py` before calling `super()`

---

## Acceptance Criteria

- [ ] U6 normal mode, FTS mode, provenance, ownership and failure cases pass.
- [ ] Existing origin exports stay available and no SDK dependency leaks into tools imports.
- [ ] Adapter consumes the frozen hybrid contract rather than guessing a shared HybridSearchResult.
- [ ] All existing origin unit tests remain passing.
- [ ] Tests in this task's Test Specification pass; failures are not hidden by mocks, skips or relaxed assertions where real SDK/model execution is required.
- [ ] Scope-owned code passes formatting/type checks appropriate to the repository, and the completion note records actual commands and evidence.

---

## Test Specification

| Test | Required behavior |
|---|---|
| `test_origin_mode_and_fixed_scope` | Fake store sees expected method, query, limit and scope. |
| `test_origin_native_score_rank_provenance` | Vector/FTS/hybrid outputs preserve metadata and rank conventions. |
| `test_origin_errors_cancellation_and_borrowed_lifetime` | Errors propagate and adapter never closes or frees borrowed resources. |
| `test_origin_import_without_sdk` | Isolated import works without lancedb installed. |

Intended command after dependencies are implemented:

```bash
uv run pytest packages/ai-parrot-tools/tests/multistoresearch/test_lancedb_origin.py packages/ai-parrot-tools/tests/multistoresearch/test_vector_origin.py packages/ai-parrot-tools/tests/multistoresearch/test_graphindex_origin.py -v
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
7. Move this task to `sdd/tasks/completed/TASK-3066-lancedb-search-origin.md`, update its per-spec entry to `done` with completion time and file path, and fill the completion note.
8. Commit only scoped implementation plus this task's SDD state. Follow the execution/review workflow before pushing.

---

## Completion Note

**Completed by**: not started
**Date**: not completed
**Notes**: Pending execution; no implementation or acceptance tests run during task decomposition.
**Deviations from spec**: The checked answers supersede stale prose; TASK-3057 reconciles that discrepancy before implementation.
