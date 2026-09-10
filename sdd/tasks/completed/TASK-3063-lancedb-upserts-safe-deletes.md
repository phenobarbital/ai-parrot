# TASK-3063: Implement contextual ingestion, upserts and safe deletion

**Feature**: FEAT-542 — Local LanceDB Vector, Full-Text and Hybrid Search
**Spec**: `sdd/specs/lancedb-vector-store.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h) — target 4 hours
**Depends-on**: TASK-3060, TASK-3062
**Assigned-to**: unassigned
**Parallel**: false
**Parallelism notes**: Sequential/gated task. Only this task edits backend mutations. Later query task verifies cross-mode visibility; test-only lifecycle harness may remain until similarity_search is implemented.
**Acceptance coverage**: AC3, AC4, AC8

---

## Context

M2 mutation delivery, using the schema/identity/compiler/coordinator contracts already completed.

The spec is marked approved. Its checked section 8 answers require fully offline agent operation after provisioning, concurrent independent writers, graph federation only, and whole-origin failure; they override older draft assumptions. TASK-3057 must reconcile the spec and prove the SDK/offline/concurrency contracts before dependent implementation begins. Do not reinstate single-writer-only or storage-only-offline behavior.

---

## Scope

- Implement from_documents as prepare/add/return store and add_documents against an existing prepared collection; empty ingestion is a no-op.
- Validate all input IDs/metadata before writes; copy documents for contextual augmentation, persist original text and derive stable IDs before augmentation.
- Validate every generated vector batch and merge-insert upserts under process-safe coordination with snapshot refresh. Report committed batch count on partial failure; stable-ID retry is idempotent.
- Implement explicit document/ID deletion and typed metadata deletion with safe selector validation, parents included when selected, and exact deletion counts under the same coordinated transaction.
- Exercise two writer processes on disjoint IDs and the same ID; acknowledged writes survive reopen without duplicate logical IDs. Follow gate-defined conflict semantics, not an invented last-writer rule.

**NOT in scope**: Search implementation, automatic schema migration, delete-all, distributed transactions and all-batch rollback promises.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-embeddings/src/parrot/stores/lancedb.py` | MODIFY | from_documents, add_documents and deletion methods |
| `packages/ai-parrot-embeddings/tests/test_lancedb_mutations.py` | CREATE | CRUD, contextual text and multi-process mutation tests |

Ownership is exclusive to this task for the listed responsibility. You are not alone in the codebase: preserve others' changes, do not revert unrelated edits, and accommodate completed dependency work. New files listed here are proposed outputs, not already-verified imports. Shared backend files are deliberately sequenced by dependencies.

---

## Codebase Contract (Anti-Hallucination)

Verified by source inspection on `dev` on 2026-09-10. This is not a claim of runtime SDK/import testing. Re-read relevant definitions before implementation; if paths/signatures changed, update the contract first. Symbols delivered by dependencies must be verified in their committed files before import.

### Verified Imports

```python
from parrot.stores import AbstractStore  # packages/ai-parrot-embeddings/tests/test_namespace_imports.py:151
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
| `packages/ai-parrot/src/parrot/stores/abstract.py:326` | create_embedding(self, embedding_model: dict, **kwargs) uses registry.get_or_create_sync; arbitrary dict fields are not automatically forwarded (Matryoshka is explicitly forwarded). |
| `packages/ai-parrot/src/parrot/stores/abstract.py:383` | async generate_embedding(self, documents: List[Any]) -> List[Any] initializes a default provider if absent, then awaits embed_documents. |
| `packages/ai-parrot/src/parrot/stores/abstract.py:391` | _apply_contextual_augmentation(self, documents: list, _log: bool = True) -> list[str] mutates document.metadata['contextual_header']; use copies. |
| `packages/ai-parrot/src/parrot/embeddings/base.py:169` | async embed_documents(self, texts: List[str], batch_size: Optional[int] = None) -> List[List[float]]. |
| `packages/ai-parrot/src/parrot/embeddings/base.py:188` | async embed_query(self, text: str, as_nparray: bool = False) -> Union[List[float], List[np.ndarray]]; default is a single flat vector. |
| `packages/ai-parrot-embeddings/src/parrot/embeddings/huggingface.py:134` | SentenceTransformerModel.__init__(self, model_name: str, matryoshka: Optional[dict] = None, backend: Optional[str] = None, file_name: Optional[str] = None, **kwargs). |
| `packages/ai-parrot/src/parrot/stores/models.py:19` | Document(page_content: str, metadata: Dict[str, Any]); metadata defaults to an empty mapping. |
| `packages/ai-parrot/src/parrot/models/stores.py:46` | SearchResult requires id: str, content: str, score: float; distance at :74 returns score unchanged. |
| `packages/ai-parrot/src/parrot/models/stores.py:79` | OriginHit has optional id/score, content/metadata, origin, origin_kind and native_rank >= 1. |
| `packages/ai-parrot/src/parrot/models/stores.py:162` | StoreConfig has embedding_model, dimension=768, metric_type='COSINE', index_type='IVF_FLAT', table/schema/dsn and extra. |

### Does NOT Exist

- LanceDBStore and a LanceDB process-shared coordinator do not yet exist.
- AbstractStore's connection/context state is not a cross-process transaction mechanism.
- Calling base generate_embedding is not model-free lexical retrieval.
- Do not assume arbitrary offline/local_files_only fields in embedding_model reach the provider; verify forwarding before relying on them.
- LanceDBConfig, LanceDBHybridHit and lancedb_models.py are new task deliverables, not current core types.
- A shared HybridSearchResult or globally comparable origin score does not exist.
- New helpers listed in dependency tasks are not pre-existing repository APIs. Use the gate/completion contracts, then verify their actual implementations.
- No guarantee of fully offline inference or concurrent-process correctness follows merely from opening a local LanceDB directory.

---

## Implementation Notes

### Pattern to Follow

Only this task edits backend mutations. Later query task verifies cross-mode visibility; test-only lifecycle harness may remain until similarity_search is implemented.

Use the existing contracts above without changing unrelated shared behavior. Keep async public operations non-blocking, strict type hints, Pydantic structured records and black/isort formatting. Keep SDK access inside the embeddings backend, never in the origin adapter.

### Key Constraints

- Complete only this task's deliverable; do not implement later tasks opportunistically.
- Never remove or silently downgrade approved offline or concurrent-writer requirements.
- No schema overwrite, broad deletion, automatic version pruning, remote fallback or new storage server.
- Preserve caller documents and shared embedding ownership. Do not log document text, vectors, credentials or filter values.
- Respect optional dependency boundaries; follow approval policy before introducing unapproved packages.
- Capture test commands, dependency versions and outcomes under `artifacts/logs/TASK-3063-lancedb.log`; real-model/benchmark evidence must distinguish provisioning from execution.

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
1. Validate IDs and metadata for the WHOLE input before writing any batch — *why*: spec §2 item 4 requires it, and a half-ingested corpus with a validation error at document 400 is unrecoverable without stable IDs.
2. Compute fallback IDs BEFORE contextual augmentation — *why*: spec §2 "Data Models" is explicit; hashing the augmented text makes the same document hash differently on reingest and breaks upsert.
3. Deep-copy caller documents before augmenting — *why*: spec §2 item 5 forbids mutating caller objects; the caller may reuse them for another store.
4. Route every write through the TASK-3061 coordinator — *why*: this is where the §8 concurrent-writer answer becomes real behavior rather than a document.
5. Report completed batch count on failure and never claim rollback — *why*: spec §2 item 6 says each committed batch is durable; claiming an all-or-nothing rollback would be false.

### `packages/ai-parrot-embeddings/src/parrot/stores/lancedb.py` (MODIFY)
```python
# occurrences: 1 expected — verify after TASK-3062 lands:
#   grep -c 'async def similarity_search' packages/ai-parrot-embeddings/src/parrot/stores/lancedb.py
# BEFORE — insert above `    async def similarity_search(self, query: str, collection=None, limit: int = 2, **kwargs: Any) -> list:`
#   (anchor created by TASK-3062's blueprint; if TASK-3062 renamed it, re-anchor before editing)

    async def from_documents(self, documents: List[Any], collection=None, **kwargs: Any) -> Callable:
        """Prepare the collection, add the documents and return this store."""
        # FILL IN: create_collection then add_documents; empty input is a no-op
        # — bounded by spec §2 item 4, AC4
        raise NotImplementedError

    async def add_documents(self, documents: List[Any], collection=None, **kwargs: Any) -> None:
        """Upsert documents into an existing prepared collection.

        Raises:
            LookupError: the collection does not exist.
            ValueError: conflicting or duplicate IDs in one call.
        """
        # FILL IN, in this order — the order is the contract, not a preference:
        #   1. resolve IDs (explicit ids -> metadata['id'] -> record_id_for(ORIGINAL text))
        #   2. validate every ID and metadata value for the FULL input; raise before writing
        #   3. deep-copy documents, apply the existing contextual augmentation hook to copies
        #   4. per batch: embed via the provider, validate dimension/finite/non-zero-norm,
        #      then merge-insert under self._coordinator.run_mutation
        #   5. on batch failure raise identifying the completed batch count, WITHOUT logging
        #      document text, vectors or filter values
        # — bounded by spec §2 items 4-6, AC4, AC8, and §7 "Avoid logging document text"
        raise NotImplementedError

    async def delete_documents(self, documents=None, pk: str = 'source_type', values=None,
                               table=None, schema=None, collection=None, **kwargs: Any) -> int:
        """Delete by document identity or by ``pk`` + ``values``. Returns rows removed.

        Raises:
            ValueError: empty filter, missing selector, or conflicting selectors.
        """
        # FILL IN: count and delete under ONE coordinator section so the returned count
        # matches what was removed; pk='id' targets raw logical IDs, any other key must be
        # a declared metadata field; no implicit delete-all; deletion reaches matching
        # parents regardless of search visibility — bounded by spec §2 item 7, AC4
        raise NotImplementedError

    async def delete_documents_by_filter(self, search_filter: dict, table=None, schema=None,
                                         collection=None, **kwargs: Any) -> int:
        """Delete by compiled metadata predicate. Returns rows removed."""
        # FILL IN: use compile_metadata_filter WITHOUT parent_exclusion_clause — deletion is
        # not a search — and reject an empty filter — bounded by spec §2 item 7 and §2 Filters
        raise NotImplementedError
```
**Why this shape**: the numbered order inside `add_documents` is the specification, not style — validating after the first batch has committed makes a partial write unavoidable, and augmenting before computing IDs breaks upsert idempotency on reingest. `delete_documents_by_filter` deliberately omits the parent clause because a caller deleting `source='x'` expects the parents to go too; reusing the search predicate would silently strand them.

### `packages/ai-parrot-embeddings/tests/test_lancedb_mutations.py` (CREATE)
```python
"""CRUD, contextual text and multi-process mutation tests (FEAT-542, AC4/AC8)."""
from __future__ import annotations

import pytest

from parrot.stores.lancedb import LanceDBStore

pytestmark = pytest.mark.asyncio


class TestIdentity:
    async def test_explicit_ids_beat_metadata_id_beats_content_hash(self, tmp_path):
        # FILL IN — bounded by spec §2 "Data Models" precedence
        raise NotImplementedError

    async def test_conflicting_or_duplicate_ids_raise_before_any_write(self, tmp_path):
        # FILL IN: assert the table is untouched afterwards — bounded by AC4
        raise NotImplementedError

    async def test_fallback_id_uses_original_text_not_augmented(self, tmp_path):
        # FILL IN: reingest with contextual augmentation on; assert upsert, not duplicate
        # — bounded by spec §2 "Calculate fallback IDs before contextual augmentation"
        raise NotImplementedError


class TestIngestion:
    async def test_caller_documents_are_not_mutated(self, tmp_path):
        # FILL IN: snapshot inputs, compare after — bounded by AC4
        raise NotImplementedError

    @pytest.mark.parametrize("bad_vector", [...])  # FILL IN: wrong dim, NaN/inf, zero-norm
    async def test_invalid_vectors_rejected(self, tmp_path, bad_vector):
        # FILL IN — bounded by spec §2 row table
        raise NotImplementedError

    async def test_partial_batch_failure_reports_count_and_retry_is_idempotent(self, tmp_path):
        # FILL IN: assert no rollback is claimed and a retry with stable IDs converges
        # — bounded by spec §2 item 6, AC4
        raise NotImplementedError

    async def test_missing_collection_raises_lookuperror(self, tmp_path):
        # FILL IN — bounded by spec §2 item 4
        raise NotImplementedError


class TestDeletion:
    async def test_counts_are_exact_including_zero(self, tmp_path):
        # FILL IN — bounded by AC4
        raise NotImplementedError

    async def test_empty_or_conflicting_selectors_raise(self, tmp_path):
        # FILL IN: assert no rows removed — bounded by spec §2 item 7
        raise NotImplementedError

    async def test_deletion_reaches_parents_hidden_from_search(self, tmp_path):
        # FILL IN — bounded by spec §2 item 7
        raise NotImplementedError


class TestConcurrentMutations:
    def test_two_processes_upserting_the_same_ids_converge(self, tmp_path):
        # FILL IN: real multiprocessing; every acknowledged write present after reopen,
        # no duplicate logical document — bounded by AC8. Threads do NOT count.
        raise NotImplementedError
```
**Why this shape**: `test_fallback_id_uses_original_text_not_augmented` is the test that catches the single most likely implementation slip in this task, and it is cheap; `test_partial_batch_failure_reports_count_and_retry_is_idempotent` exists because the spec explicitly refuses to promise rollback, so the test must assert the honest behavior rather than the comfortable one.

### FILL IN checklist
- [ ] `lancedb.py::from_documents` / `add_documents` — the five numbered steps in order; bounded by spec §2 items 4-6, AC4
- [ ] `lancedb.py::delete_documents` — count+delete in one section, selector rules; bounded by AC4
- [ ] `lancedb.py::delete_documents_by_filter` — no parent clause, no empty filter; bounded by spec §2 item 7
- [ ] `test_lancedb_mutations.py` — all eleven bodies, real processes for the concurrent case; bounded by AC4/AC8
- [ ] Re-verify the `similarity_search` anchor after TASK-3062 lands before applying the MODIFY block

---

## Acceptance Criteria

- [ ] U4 mutation cases pass with stable IDs and correct metadata/text preservation.
- [ ] All required abstract ingestion/deletion operations are implemented, not no-ops.
- [ ] Exact counts, conflict handling and cancellation match the reconciled spec.
- [ ] CRUD state survives fresh-process reopen and never silently deletes an unrestricted collection.
- [ ] Tests in this task's Test Specification pass; failures are not hidden by mocks, skips or relaxed assertions where real SDK/model execution is required.
- [ ] Scope-owned code passes formatting/type checks appropriate to the repository, and the completion note records actual commands and evidence.

---

## Test Specification

| Test | Required behavior |
|---|---|
| `test_reingestion_upserts_and_preserves_original_text` | Identity and contextual metadata stable; caller inputs unchanged. |
| `test_invalid_batch_never_writes_invalid_rows` | Dimensions, finite values, duplicate IDs and zero vectors validated. |
| `test_partial_failure_retry_is_idempotent` | Only successful batches durable and error reports completed count. |
| `test_delete_selectors_and_exact_counts` | Empty/conflicting/unknown selectors fail; actual deleted count correct. |
| `test_two_process_crud_no_lost_acknowledged_writes` | Separate processes and fresh-process reopen prove the approved write contract. |

Intended command after dependencies are implemented:

```bash
uv run pytest packages/ai-parrot-embeddings/tests/test_lancedb_mutations.py packages/ai-parrot-embeddings/tests/test_lancedb_lifecycle.py -v
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
7. Move this task to `sdd/tasks/completed/TASK-3063-lancedb-upserts-safe-deletes.md`, update its per-spec entry to `done` with completion time and file path, and fill the completion note.
8. Commit only scoped implementation plus this task's SDD state. Follow the execution/review workflow before pushing.

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet 5)
**Date**: 2026-09-10
**Notes**: Implemented `from_documents`/`add_documents` in the exact five-step order the blueprint fixed: `_resolve_ids` (explicit > `metadata['id']` > `record_id_for(original text)`, conflicting/duplicate raise before any write) → `_validate_metadata` for the full input → deep-copy + `_apply_contextual_augmentation` on copies only → per-batch `provider.embed_documents` + `_validate_vector` (dimension/finite/non-zero-norm) → merge-insert under `self._coordinator.run_mutation` with a freshly reopened table handle. Batch failures (embedding OR mutation) raise `RuntimeError` naming completed-batch count, never claiming rollback; a retry with the same stable IDs converges (tested). `delete_documents` accepts `documents` (Document objects or raw IDs, hashed via the same identity algorithm) XOR `pk`+`values` (`pk="id"` → raw IDs, else a declared metadata field), rejects empty/missing/conflicting selectors, and returns the SDK's own `DeleteResult.num_deleted_rows` — count and delete are the same atomic call, so there's no separate count-then-delete race. `delete_documents_by_filter` reuses `compile_metadata_filter` WITHOUT `parent_exclusion_clause` (deletion is not search) and rejects an empty filter.

Found and fixed a real staleness bug during integration testing (not anticipated by the blueprint): `self._default_table`, once mutated through a freshly-reopened handle inside a coordinator closure, must be reassigned to that exact handle — otherwise `get_vector()`/future search callers would read a pre-write snapshot. This reproduces TASK-3057's gate finding (fresh-handle-before-mutate) as an in-process staleness issue between two independently opened `AsyncTable` objects, not just a cross-process one.

`test_lancedb_mutations.py`: 16 tests, all pass (`uv run pytest packages/ai-parrot-embeddings/tests/test_lancedb_mutations.py -v`, log at `artifacts/logs/TASK-3063-lancedb.log`), including a real two-process (`multiprocessing`, spawn) concurrent upsert of 3 colliding IDs converging to exactly 3 rows (no loss, no duplication). Full lancedb-scoped suite (7 modules): 96/96 passing. `ruff check` clean.
**Deviations from spec**: None from scope. Reused `lancedb_filters._quote_literal` (a leading-underscore helper) for `record_id IN (...)` clause escaping rather than duplicating the escaping logic — `record_id` is a physical primary-key column, not a `meta_<field>` metadata projection, so `compile_metadata_filter` itself doesn't apply here; this is an import, not a modification, of TASK-3060's file.
