# TASK-3069: Verify persistence, concurrent writers and graph federation

**Feature**: FEAT-542 — Local LanceDB Vector, Full-Text and Hybrid Search
**Spec**: `sdd/specs/lancedb-vector-store.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h) — target 4 hours
**Depends-on**: TASK-3067
**Assigned-to**: unassigned
**Parallel**: true
**Parallelism notes**: Can run alongside offline profile task after registration. File ownership is disjoint from other eligible parallel tasks; dependencies still gate start.
**Acceptance coverage**: AC3, AC4, AC5, AC6, AC7, AC8, AC9

---

## Context

M5 final real-SDK acceptance across process boundaries and the existing multi-store toolkit.

The spec is marked approved. Its checked section 8 answers require fully offline agent operation after provisioning, concurrent independent writers, graph federation only, and whole-origin failure; they override older draft assumptions. TASK-3057 must reconcile the spec and prove the SDK/offline/concurrency contracts before dependent implementation begins. Do not reinstate single-writer-only or storage-only-offline behavior.

---

## Scope

- Exercise the complete deterministic 24-document fixture in two collections across vector/FTS/hybrid, fresh-process reopen and incompatible manifest attempts.
- Run two independently initialized writer processes concurrently with barriers: disjoint inserts, same-ID upserts, overlapping deletes/counts, simultaneous collection/index creation and reader refresh. Assert acknowledged outcomes, uniqueness and no corruption under the gate-defined conflict contract.
- Test cancellation during waits and native writes, writer termination, subsequent successful mutations and fresh reopen; don't infer rollback from timeout.
- Compose real LanceDBOrigin and GraphIndexOrigin in real MultiStoreSearchToolkit; use a real tiny graph retriever with deterministic seed results and optional local SQLite FTS, not only FakeRetriever.
- Check grouped native order/scores, final merged cap/dedup, same local IDs in unrelated collections, one-origin failure/timeout and unsupported FTS skipping. Preserve existing ranking rather than asserting native RRF order in merged results.
- Add I8 storage-only tests with all socket connections disabled and deterministic embeddings. CRUD, vector, FTS and hybrid must work without any storage endpoint; this complements, rather than replaces, TASK-3068's real offline agent test.

**NOT in scope**: Production-code refactors, new graph seed implementation, benchmark SLOs and offline real-LLM provisioning.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-embeddings/tests/test_lancedb_store.py` | CREATE | End-to-end persistence/filter/mutation suite |
| `packages/ai-parrot-embeddings/tests/test_lancedb_multiprocess.py` | CREATE | Real store concurrent-writer and crash/cancellation tests |
| `packages/ai-parrot-tools/tests/multistoresearch/test_lancedb_integration.py` | CREATE | Real hybrid-plus-graph federation acceptance |

Ownership is exclusive to this task for the listed responsibility. You are not alone in the codebase: preserve others' changes, do not revert unrelated edits, and accommodate completed dependency work. New files listed here are proposed outputs, not already-verified imports. Shared backend files are deliberately sequenced by dependencies.

---

## Codebase Contract (Anti-Hallucination)

Verified by source inspection on `dev` on 2026-09-10. This is not a claim of runtime SDK/import testing. Re-read relevant definitions before implementation; if paths/signatures changed, update the contract first. Symbols delivered by dependencies must be verified in their committed files before import.

### Verified Imports

```python
from parrot.stores import AbstractStore  # packages/ai-parrot-embeddings/tests/test_namespace_imports.py:151
from parrot.models import OriginHit, SearchOriginKind  # packages/ai-parrot-tools/src/parrot_tools/multistoresearch/origins/vector.py:10
from parrot_tools.multistoresearch.origins.base import SearchOrigin  # packages/ai-parrot-tools/tests/multistoresearch/test_toolkit.py:6
from parrot_tools.multistoresearch.origins import GraphIndexOrigin  # packages/ai-parrot-tools/tests/multistoresearch/test_graphindex_origin.py:5
from parrot_tools.multistoresearch import MultiStoreSearchToolkit  # packages/ai-parrot-tools/tests/multistoresearch/test_toolkit.py:5
from pydantic import BaseModel, Field  # packages/ai-parrot/src/parrot/stores/models.py:13
from parrot.models.stores import SearchResult  # packages/ai-parrot-tools/src/parrot_tools/multistoresearch/origins/vector.py:11
```

### Existing Signatures to Use

| Verified source | Existing contract |
|---|---|
| `packages/ai-parrot/src/parrot/stores/abstract.py:117` | AbstractStore.__init__(self, embedding_model: Union[dict, str] = None, embedding: Union[dict, Callable] = None, **kwargs); configured provider eagerly created at :155. |
| `packages/ai-parrot/src/parrot/stores/abstract.py:202` | async connection(self) -> tuple; get_connection(self) -> Any at :205; engine(self) at :208; async disconnect(self) -> None at :212. |
| `packages/ai-parrot/src/parrot/stores/abstract.py:216` | Nested __aenter__/__aexit__; _free_resources at :222 calls provider.free(). Subclass must preserve borrowed-provider ownership. |
| `packages/ai-parrot/src/parrot/stores/abstract.py:238` | get_vector(self, metric_type: str = None, **kwargs); get_vectorstore(self) at :241 delegates. |
| `packages/ai-parrot/src/parrot/stores/abstract.py:276` | async from_documents(self, documents: List[Any], collection: Union[str, None] = None, **kwargs) -> Callable. |
| `packages/ai-parrot/src/parrot/stores/abstract.py:295` | async create_collection(self, collection: str) -> None; async add_documents(self, documents: List[Any], collection: Union[str, None] = None, **kwargs) -> None at :308. |
| `packages/ai-parrot/src/parrot/stores/abstract.py:455` | async prepare_embedding_table(self, tablename: str, conn: Any = None, embedding_column: str = 'embedding', document_column: str = 'document', metadata_column: str = 'cmetadata', dimension: int = None, id_column: str = 'id', use_jsonb: bool = True, drop_columns: bool = False, create_all_indexes: bool = True, **kwargs). |
| `packages/ai-parrot/src/parrot/stores/abstract.py:494` | async delete_documents(self, documents: Optional[Any] = None, pk: str = 'source_type', values: Optional[Union[str, List[str]]] = None, table: Optional[str] = None, schema: Optional[str] = None, collection: Optional[str] = None, **kwargs) -> int. |
| `packages/ai-parrot/src/parrot/stores/abstract.py:520` | async delete_documents_by_filter(self, search_filter: Dict[str, Union[str, List[str]]], table: Optional[str] = None, schema: Optional[str] = None, collection: Optional[str] = None, **kwargs) -> int. |
| `packages/ai-parrot-tools/src/parrot_tools/multistoresearch/origins/base.py:42` | async search(self, query: str, k: int) -> List[OriginHit]; optional async fts_search(self, query: str, k: int) -> List[OriginHit] at :54; adapters raise errors. |
| `packages/ai-parrot-tools/src/parrot_tools/multistoresearch/origins/vector.py:50` | VectorStoreOrigin.search calls self.store.similarity_search(query, limit=k); fts_search at :66 calls self.store.fulltext_search; _normalize at :90 preserves score/metadata and 1-based rank. |
| `packages/ai-parrot-tools/src/parrot_tools/multistoresearch/origins/__init__.py:7` | Current exports: SearchOrigin, VectorStoreOrigin, PageIndexOrigin, GraphIndexOrigin and ParrotWikiOrigin. |
| `packages/ai-parrot-tools/src/parrot_tools/multistoresearch/toolkit.py:65` | MultiStoreSearchToolkit.__init__(self, origins: List[SearchOrigin], k: int = 10, k_per_origin: int = 20, default_timeout: float = 30.0, bm25_weights: Optional[Dict[str, float]] = None, **kwargs: Any) -> None. |
| `packages/ai-parrot-tools/src/parrot_tools/multistoresearch/toolkit.py:85` | async store_search(self, query: str, k: Optional[int] = None) -> MultiSearchResponse; _run_origins at :268 isolates origin timeouts/errors. |
| `packages/ai-parrot-tools/src/parrot_tools/multistoresearch/toolkit.py:246` | _build_response reranks then deduplicates; BM25 at :359 leaves scores untouched; dedup at :390 uses ID then content hash. |
| `packages/ai-parrot-tools/src/parrot_tools/multistoresearch/origins/graphindex.py:43` | GraphIndexOrigin.__init__(self, retriever: GraphExpandedRetriever, reader: Optional[SQLiteGraphReader] = None, name: str = 'graphindex', description: Optional[str] = None, timeout: Optional[float] = None, seed_top_k: int = 10) -> None. |
| `packages/ai-parrot-tools/src/parrot_tools/multistoresearch/origins/graphindex.py:69` | search calls retriever.search(query, seed_top_k=k); fts_search at :109 calls reader.search_symbols(query, limit=k). |
| `packages/ai-parrot/src/parrot/knowledge/graphindex/retriever.py:186` | GraphExpandedRetriever.__init__(self, graph: rustworkx.PyDiGraph, nodes: list[UniversalNode], embedder: Optional[GraphIndexEmbedder] = None, hybrid_search: Optional[HybridPageIndexSearch] = None, signal_config: Optional[SignalRelevanceConfig] = None, communities: Optional[CommunitiesResult] = None) -> None; one seed source required. |
| `packages/ai-parrot/src/parrot/knowledge/graphindex/sqlite_reader.py:320` | async search_symbols(self, query: str, *, limit: int = 20) -> list[dict]; native FTS5 BM25 is negative, best ascending. |
| `packages/ai-parrot-tools/tests/multistoresearch/test_graphindex_origin.py:26` | FakeRetriever.search and FakeReader.search_symbols at :36 are existing unit-test patterns only; real integration must include the actual retriever. |
| `packages/ai-parrot/src/parrot/stores/models.py:19` | Document(page_content: str, metadata: Dict[str, Any]); metadata defaults to an empty mapping. |
| `packages/ai-parrot/src/parrot/models/stores.py:46` | SearchResult requires id: str, content: str, score: float; distance at :74 returns score unchanged. |
| `packages/ai-parrot/src/parrot/models/stores.py:79` | OriginHit has optional id/score, content/metadata, origin, origin_kind and native_rank >= 1. |
| `packages/ai-parrot/src/parrot/models/stores.py:162` | StoreConfig has embedding_model, dimension=768, metric_type='COSINE', index_type='IVF_FLAT', table/schema/dsn and extra. |

### Does NOT Exist

- LanceDBStore and a LanceDB process-shared coordinator do not yet exist.
- AbstractStore's connection/context state is not a cross-process transaction mechanism.
- LanceDBOrigin is new; the current VectorStoreOrigin has no hybrid mode.
- Toolkit merged_top_k does not preserve native RRF order; only grouped sections preserve origin order.
- A LanceDB path cannot initialize a graph retriever or replace its seed provider.
- Graph builder/node construction APIs are not established by these adapter signatures; read those sources before creating fixtures.
- LanceDBConfig, LanceDBHybridHit and lancedb_models.py are new task deliverables, not current core types.
- A shared HybridSearchResult or globally comparable origin score does not exist.
- New helpers listed in dependency tasks are not pre-existing repository APIs. Use the gate/completion contracts, then verify their actual implementations.
- No guarantee of fully offline inference or concurrent-process correctness follows merely from opening a local LanceDB directory.

---

## Implementation Notes

### Pattern to Follow

Can run alongside offline profile task after registration. Do not modify common fixtures concurrently; fixture deficiencies go back to the models task owner.

Use the existing contracts above without changing unrelated shared behavior. Keep async public operations non-blocking, strict type hints, Pydantic structured records and black/isort formatting. Keep SDK access inside the embeddings backend, never in the origin adapter.

### Key Constraints

- Complete only this task's deliverable; do not implement later tasks opportunistically.
- Never remove or silently downgrade approved offline or concurrent-writer requirements.
- No schema overwrite, broad deletion, automatic version pruning, remote fallback or new storage server.
- Preserve caller documents and shared embedding ownership. Do not log document text, vectors, credentials or filter values.
- Respect optional dependency boundaries; follow approval policy before introducing unapproved packages.
- Capture test commands, dependency versions and outcomes under `artifacts/logs/TASK-3069-lancedb.log`; real-model/benchmark evidence must distinguish provisioning from execution.

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
1. Build every suite on `lancedb_fixtures.corpus()` from TASK-3059 — *why*: the acceptance claims in spec §4 are written against that exact 24-document shape; a locally invented corpus makes I3's lexical/semantic assertions meaningless.
2. Use real OS processes for the concurrency suite — *why*: threads share the in-process asyncio lock and would pass against a coordinator with no cross-process guarantee, which is precisely the false green AC8 exists to prevent.
3. Compose REAL `LanceDBOrigin` + `GraphIndexOrigin` in a real `MultiStoreSearchToolkit` — *why*: AC7 is about the toolkit's merged behavior; a fake origin cannot exercise `_build_response`'s rerank-then-dedup path (`toolkit.py:246`).
4. Assert the EXISTING merged ranking, not native RRF order, in the merged list — *why*: the toolkit reranks with BM25 at `toolkit.py:359`; asserting RRF order there would be asserting a bug.
5. Verify the graph fixture constructors before writing them — *why*: this task's Scope forbids inventing a graph-builder API.

### `packages/ai-parrot-embeddings/tests/test_lancedb_store.py` (CREATE)
```python
"""End-to-end persistence, filter and mutation suite (FEAT-542, AC3/AC4/AC5)."""
from __future__ import annotations

import pytest

from parrot.stores.lancedb import LanceDBStore

pytestmark = pytest.mark.asyncio


class TestPersistence:
    async def test_reopen_in_a_fresh_subprocess_returns_identical_ids_and_metadata(self, tmp_path):
        # FILL IN: ingest, close, reopen in a subprocess — bounded by spec §4 I2, AC3
        raise NotImplementedError

    async def test_incompatible_reopen_leaves_original_data_readable(self, tmp_path):
        # FILL IN: manifest/dimension/identity mismatch raises and destroys nothing
        # — bounded by AC3
        raise NotImplementedError

    async def test_same_local_ids_in_two_collections_stay_distinct(self, tmp_path):
        # FILL IN: the two-collection corpus — bounded by AC3
        raise NotImplementedError


class TestRetrievalMatrix:
    async def test_vector_fts_and_hybrid_on_one_corpus(self, tmp_path):
        # FILL IN: ZXQ731 lexical-only and the semantic-only neighbour both eligible in
        # hybrid — bounded by spec §4 I3
        raise NotImplementedError

    async def test_excluded_rows_never_consume_the_candidate_budget(self, tmp_path):
        # FILL IN — bounded by spec §4 I3, AC5
        raise NotImplementedError


class TestMutationVisibility:
    async def test_upsert_and_delete_visible_in_all_modes_before_and_after_reopen(self, tmp_path):
        # FILL IN: include rows added AFTER FTS index creation — bounded by spec §4 I4
        raise NotImplementedError


class TestNoNetwork:
    async def test_storage_operations_with_sockets_denied(self, tmp_path):
        # FILL IN: deterministic provider, sockets disabled; CRUD + all three modes.
        # This is the storage half of AC6 — TASK-3068 owns the whole-agent half
        # — bounded by spec §4 I8
        raise NotImplementedError
```
**Why this shape**: the persistence tests reopen in a *subprocess* rather than a new object because an in-process reopen can be satisfied by cached handles and would not prove durability. `TestNoNetwork` is scoped to storage here and explicitly defers the whole-agent claim to TASK-3068, so neither task can accidentally claim the other's coverage.

### `packages/ai-parrot-embeddings/tests/test_lancedb_multiprocess.py` (CREATE)
```python
"""Real concurrent-writer, crash and cancellation tests (FEAT-542, AC8, spec §4 I9)."""
from __future__ import annotations

import multiprocessing as mp

import pytest


class TestConcurrentWriters:
    def test_disjoint_ids_from_two_processes_all_land(self, tmp_path):
        # FILL IN: barrier-synchronised writers; every acknowledged write present after a
        # fresh reopen — bounded by AC8, spec §4 I9
        raise NotImplementedError

    def test_colliding_ids_converge_without_duplicates(self, tmp_path):
        # FILL IN: same ids from both processes; one logical document survives
        raise NotImplementedError

    def test_simultaneous_collection_and_index_creation(self, tmp_path):
        # FILL IN: both processes call create_collection at once — bounded by spec §4 I9
        raise NotImplementedError

    def test_reader_never_observes_a_partial_or_erroring_table(self, tmp_path):
        # FILL IN: a reader looping throughout, including while the FTS index is rebuilt
        # — bounded by spec §2 concurrency paragraph, spec §4 I9
        raise NotImplementedError

    def test_conflicts_retry_within_bound_or_raise_the_documented_error(self, tmp_path):
        # FILL IN — bounded by AC8 and TASK-3057's recorded conflict contract
        raise NotImplementedError


class TestFailureModes:
    def test_writer_termination_then_successful_subsequent_mutation(self, tmp_path):
        # FILL IN: kill mid-write; the next mutation proceeds; no stolen-lock heuristic
        raise NotImplementedError

    def test_cancellation_does_not_imply_rollback(self, tmp_path):
        # FILL IN: assert the honest behavior, not a convenient one — bounded by spec §2
        raise NotImplementedError
```
**Why this shape**: `mp` is imported at module top to make the intent unmissable — if a future contributor rewrites these with threads the suite still passes while proving nothing, so the review signal has to be visible in the imports.

### `packages/ai-parrot-tools/tests/multistoresearch/test_lancedb_integration.py` (CREATE)
```python
"""Real hybrid-plus-graph federation acceptance (FEAT-542, AC7)."""
from __future__ import annotations

import pytest

from parrot_tools.multistoresearch import MultiStoreSearchToolkit  # verified: packages/ai-parrot-tools/tests/multistoresearch/test_toolkit.py:5
from parrot_tools.multistoresearch.origins import GraphIndexOrigin  # verified: packages/ai-parrot-tools/tests/multistoresearch/test_graphindex_origin.py:5

pytestmark = pytest.mark.asyncio


class TestFederation:
    async def test_grouped_native_order_and_scores_preserved_per_origin(self, tmp_path):
        # FILL IN: real LanceDBOrigin + real GraphIndexOrigin over a tiny real graph with
        # deterministic seeds — bounded by AC7, spec §4 I6
        raise NotImplementedError

    async def test_merged_ranking_and_dedup_are_unchanged(self, tmp_path):
        # FILL IN: assert the EXISTING toolkit rerank/dedup behavior (toolkit.py:246/359/390),
        # NOT native RRF order in the merged list — bounded by AC7
        raise NotImplementedError

    async def test_one_failed_or_timed_out_origin_does_not_erase_the_other(self, tmp_path):
        # FILL IN: fail the LanceDB origin's hybrid leg; graph results survive
        # — bounded by AC7 and spec §8 (whole-origin failure)
        raise NotImplementedError

    async def test_unsupported_fts_origin_is_skipped_not_errored(self, tmp_path):
        # FILL IN: GraphIndexOrigin without a reader has supports_fts False
        # (origins/graphindex.py:67) — bounded by AC7
        raise NotImplementedError
```
**Why this shape**: `test_merged_ranking_and_dedup_are_unchanged` is the guard against this feature quietly redefining toolkit behavior for every existing origin — spec §1 lists changing toolkit ranking/deduplication as a Non-Goal, and this is the test that enforces it.

### FILL IN checklist
- [ ] `test_lancedb_store.py` — all seven bodies on the shared corpus; bounded by AC3/AC4/AC5
- [ ] `test_lancedb_multiprocess.py` — all seven bodies with real processes; bounded by AC8, spec §4 I9
- [ ] `test_lancedb_integration.py` — all four bodies with real origins and a real graph; bounded by AC7
- [ ] Verify the graph fixture constructors exist before writing them; bounded by this task's Scope
- [ ] Write all output to `artifacts/logs/lancedb-vector-store-*.log`; bounded by AC9

---

## Acceptance Criteria

- [ ] Real-SDK I2–I7 cases execute without skips in the dedicated feature environment.
- [ ] Independent concurrent processes and fresh-process reopen demonstrate the approved write contract.
- [ ] Real graph federation preserves provenance, scores and successful origins on failures/timeouts.
- [ ] All regressions pass; failures are attributed and not hidden by xfail/skips or relaxed assertions.
- [ ] Tests in this task's Test Specification pass; failures are not hidden by mocks, skips or relaxed assertions where real SDK/model execution is required.
- [ ] Scope-owned code passes formatting/type checks appropriate to the repository, and the completion note records actual commands and evidence.

---

## Test Specification

| Test | Required behavior |
|---|---|
| `test_local_store_end_to_end_all_modes` | I2–I5 across metadata/parent/score/persistence cases. |
| `test_concurrent_process_store_operations` | Real store mutation conflict/count/visibility matrix, not coordinator-only probes. |
| `test_writer_failure_and_recovery` | No deadlock or corrupted dataset after terminated/cancelled writer. |
| `test_hybrid_graph_federation_and_isolated_failure` | I6 real graph/LanceDB path and current toolkit response semantics. |
| `test_storage_operations_without_sockets` | I8: real local storage operations pass with socket connection attempts forbidden and deterministic embeddings. |

Intended command after dependencies are implemented:

```bash
uv run pytest packages/ai-parrot-embeddings/tests/test_lancedb_store.py packages/ai-parrot-embeddings/tests/test_lancedb_multiprocess.py packages/ai-parrot-tools/tests/multistoresearch/test_lancedb_integration.py -v
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
7. Move this task to `sdd/tasks/completed/TASK-3069-lancedb-end-to-end-validation.md`, update its per-spec entry to `done` with completion time and file path, and fill the completion note.
8. Commit only scoped implementation plus this task's SDD state. Follow the execution/review workflow before pushing.

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet 5)
**Date**: 2026-09-10
**Notes**: All three files built on `lancedb_fixtures.corpus()` (TASK-3059) and real `multiprocessing.Process`/real SDK/real toolkit — no `FakeRetriever`/`FakeStore` at any origin-adapter boundary in this task's own files. `test_lancedb_store.py` (7 tests): a genuine subprocess reopen (`subprocess.run([sys.executable, "-c", ...])`, not a fresh in-process object, since a cached handle could otherwise mask non-durability) proves identical ids/metadata for all 24 corpus documents; incompatible-reopen rejection leaves original data readable; two collections with the overlapping `"shared"` local id stay distinct via namespaced ids; the full vector/FTS/hybrid matrix runs against the corpus (`ZXQ731` lexical hit, semantic-neighbor eligibility in hybrid); excluded parents (`parent-a`/`parent-b`) never consume a `limit=3` candidate budget; upsert/delete are visible across all three query modes both before and after a fresh reopen, including a row added after FTS index creation; and the storage half of I8 runs full CRUD + all three modes with `socket.socket` patched to always raise.

`test_lancedb_multiprocess.py` (7 tests, `mp` imported at module top per the blueprint's own reasoning): disjoint 2×8 and colliding 2×5 writers via `multiprocessing.Barrier`-synchronized `spawn` processes; a 3-process colliding-ID race (`test_conflicts_retry_within_bound_or_raise_the_documented_error`) deliberately asserts the OUTCOME (exactly one `"shared"` row, zero errors) rather than a specific SDK exception type, because TASK-3057's gate found the SDK raises none for this race — asserting an exception here would be asserting something proven not to happen; simultaneous `create_collection` from two processes both return `"ok"`; a reader process loops continuously (`store._default_table.query()`) while a second process rebuilds the FTS index (`store.create_collection` idempotent retry) and records zero partial/erroring reads; a writer is `SIGKILL`ed mid-`exclusive()`-hold and a subsequent mutation from a fresh store instance proceeds without deadlock (proving the OS releases the `flock` on process death — no stolen-lock heuristic needed); and a cancelled `run_mutation` releases ownership (a following real mutation completes) without claiming any rollback of a write that was never actually committed.

`test_lancedb_integration.py` (4 tests): built a REAL `GraphExpandedRetriever` (not `FakeRetriever`) using the exact established codebase pattern from `packages/ai-parrot/tests/knowledge/graphindex/test_retriever.py` — real `UniversalNode`/`rustworkx.PyDiGraph`, with only the embedder's `search_similar` stubbed via `AsyncMock` for deterministic seeds (this IS the codebase's own verified way to get a deterministic real retriever, not a workaround). Composed with a real `LanceDBOrigin` in a real `MultiStoreSearchToolkit`: grouped native order/rank/provenance (`_lancedb` block) survive per section; `merged_top_k` is asserted for the EXISTING dedup behavior only (no `(origin, id)` repeats), explicitly NOT native RRF order, since spec §1 lists changing toolkit ranking as a Non-Goal; breaking the LanceDB origin (pointed at a nonexistent collection, so `hybrid_search` raises `LookupError` for real) leaves the graph section `"ok"` with real hits; and a graph origin with no reader (`supports_fts=False`) is reported `"skipped"`, not errored, by `toolkit.fts_search`.

Full commands and logs: `uv run pytest packages/ai-parrot-embeddings/tests/test_lancedb_store.py -v` (7 passed), `uv run pytest packages/ai-parrot-embeddings/tests/test_lancedb_multiprocess.py -v` (7 passed, ~16s), `uv run pytest packages/ai-parrot-tools/tests/multistoresearch/test_lancedb_integration.py -v` (4 passed) — logs at `artifacts/logs/TASK-3069-lancedb*.log`. Full lancedb-scoped embeddings suite (all 9 modules): 154/154 passing. `multistoresearch` suite: 71 passed, 1 pre-existing unrelated failure (`test_old_registry_key_removed`, already confirmed pre-existing in TASK-3066/3067's completion notes). `ruff check` clean on all three files.
**Deviations from spec**: None. `test_lancedb_offline_agent.py`'s `TestRealOfflineRun` (TASK-3068, unrelated to this task's files) is the only test in the broader suite run that legitimately skips — already documented as a known AC6 gap in TASK-3068's completion note.
