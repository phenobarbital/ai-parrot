# TASK-3067: Register LanceDB and verify existing store consumers

**Feature**: FEAT-542 — Local LanceDB Vector, Full-Text and Hybrid Search
**Spec**: `sdd/specs/lancedb-vector-store.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h) — target 2 hours
**Depends-on**: TASK-3065, TASK-3066
**Assigned-to**: unassigned
**Parallel**: false
**Parallelism notes**: Sequential/gated task. Backend defects found here must be returned to the owning task or explicitly added to scope before editing its file. This task does not own lancedb.py.
**Acceptance coverage**: AC1, AC2, AC9

---

## Context

M5 public registration follows a complete backend. Both factory paths and namespace invariants need explicit regression coverage.

The spec is marked approved. Its checked section 8 answers require fully offline agent operation after provisioning, concurrent independent writers, graph federation only, and whole-origin failure; they override older draft assumptions. TASK-3057 must reconcile the spec and prove the SDK/offline/concurrency contracts before dependent implementation begins. Do not reinstate single-writer-only or storage-only-offline behavior.

---

## Scope

- Add only the new mapping; preserve all legacy keys and pre-existing class-name mismatches.
- Update both exact-map test expectations and satellite resolution tests without adding a satellite stores/__init__.py.
- Exercise VectorInterface and VectorStoreSearchTool with explicit FLAT configuration, table/schema/column aliases, scoped filters and score thresholds; assert successful tool results and clear unsupported-MMR errors.
- Test both the existing VectorStoreOrigin and new LanceDBOrigin against the concrete store.
- Verify backend class import without SDK and actionable failure upon opening/selection; run minimal installed/absent subprocess environments rather than assuming editable install pruning proves absence.

**NOT in scope**: Existing backend refactors, StoreType/adaptive router expansion, SDK implementation changes or weakened namespace tests.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/stores/__init__.py` | MODIFY | Add only lancedb/LanceDBStore mapping |
| `packages/ai-parrot-embeddings/tests/test_store_backends_present.py` | MODIFY | New satellite backend case and intentional map extension |
| `packages/ai-parrot-embeddings/tests/test_namespace_imports.py` | MODIFY | New backend import and unchanged legacy entries |
| `packages/ai-parrot-embeddings/tests/test_lancedb_factory.py` | CREATE | Existing factory/tool/origin integration and absence errors |

Ownership is exclusive to this task for the listed responsibility. You are not alone in the codebase: preserve others' changes, do not revert unrelated edits, and accommodate completed dependency work. New files listed here are proposed outputs, not already-verified imports. Shared backend files are deliberately sequenced by dependencies.

---

## Codebase Contract (Anti-Hallucination)

Verified by source inspection on `dev` on 2026-09-10. This is not a claim of runtime SDK/import testing. Re-read relevant definitions before implementation; if paths/signatures changed, update the contract first. Symbols delivered by dependencies must be verified in their committed files before import.

### Verified Imports

```python
import importlib  # packages/ai-parrot-embeddings/tests/test_store_backends_present.py:2
from parrot.stores import AbstractStore  # packages/ai-parrot-embeddings/tests/test_namespace_imports.py:151
from parrot.models import OriginHit, SearchOriginKind  # packages/ai-parrot-tools/src/parrot_tools/multistoresearch/origins/vector.py:10
from parrot_tools.multistoresearch.origins.base import SearchOrigin  # packages/ai-parrot-tools/tests/multistoresearch/test_toolkit.py:6
```

### Existing Signatures to Use

| Verified source | Existing contract |
|---|---|
| `packages/ai-parrot-embeddings/pyproject.toml:10` | requires-python >=3.11; optional dependencies at :32; backend extras at :62; all aggregator at :97. No LanceDB declaration. |
| `packages/ai-parrot/pyproject.toml:157` | Core pyarrow>=25.0; existing faiss-cpu at :163, rustworkx at :169 and aiosqlite at :172. |
| `uv.lock:1` | uv-generated workspace lockfile; requires-python >=3.11 and Linux supported markers. Regenerate with the resolver, not manual package entries. |
| `.github/workflows/ci.yml:1` | Existing monorepo CI uses checkout/setup-python/setup-uv and explicit workspace/test commands; a dedicated new workflow must not silently skip SDK-present tests. |
| `packages/ai-parrot/src/parrot/stores/__init__.py:6` | supported_stores currently maps postgres, milvus, kb, faiss_store, arango and bigquery; preserve values including existing mismatches. |
| `packages/ai-parrot/src/parrot/interfaces/vector.py:42` | _get_database_store(self, store: dict) -> AbstractStore dynamically imports parrot.stores.{name}; passes store dict and embedding fields through. |
| `packages/ai-parrot/src/parrot/tools/vectorstoresearch.py:131` | _create_store(self) -> AbstractStore passes embedding_model/dimension/metric_type/index_type, table/schema/dsn and overlays StoreConfig.extra. |
| `packages/ai-parrot/src/parrot/tools/vectorstoresearch.py:184` | async _execute(self, query: str, limit: int = 10, score_threshold: Optional[float] = None, metadata_filters: Optional[Dict[str, Any]] = None, use_mmr: bool = False, lambda_mult: float = 0.5, **kwargs) -> Union[List[Dict[str, Any]], ToolResult]. |
| `packages/ai-parrot/src/parrot/tools/vectorstoresearch.py:211` | Search kwargs include table/schema, content_column='document', embedding_column='embedding', metadata_column='cmetadata', id_column='id'; similarity_search at :242, opt-in mmr_search at :239. |
| `packages/ai-parrot-embeddings/tests/test_store_backends_present.py:27` | Exact supported_stores assertion; satellite namespace initializer is forbidden at :49. |
| `packages/ai-parrot-embeddings/tests/test_namespace_imports.py:126` | Second exact supported_stores assertion; extend only the intentional key. |
| `packages/ai-parrot-tools/src/parrot_tools/multistoresearch/origins/base.py:42` | async search(self, query: str, k: int) -> List[OriginHit]; optional async fts_search(self, query: str, k: int) -> List[OriginHit] at :54; adapters raise errors. |
| `packages/ai-parrot-tools/src/parrot_tools/multistoresearch/origins/vector.py:50` | VectorStoreOrigin.search calls self.store.similarity_search(query, limit=k); fts_search at :66 calls self.store.fulltext_search; _normalize at :90 preserves score/metadata and 1-based rank. |
| `packages/ai-parrot-tools/src/parrot_tools/multistoresearch/origins/__init__.py:7` | Current exports: SearchOrigin, VectorStoreOrigin, PageIndexOrigin, GraphIndexOrigin and ParrotWikiOrigin. |
| `packages/ai-parrot-tools/src/parrot_tools/multistoresearch/toolkit.py:65` | MultiStoreSearchToolkit.__init__(self, origins: List[SearchOrigin], k: int = 10, k_per_origin: int = 20, default_timeout: float = 30.0, bm25_weights: Optional[Dict[str, float]] = None, **kwargs: Any) -> None. |
| `packages/ai-parrot-tools/src/parrot_tools/multistoresearch/toolkit.py:85` | async store_search(self, query: str, k: Optional[int] = None) -> MultiSearchResponse; _run_origins at :268 isolates origin timeouts/errors. |
| `packages/ai-parrot-tools/src/parrot_tools/multistoresearch/toolkit.py:246` | _build_response reranks then deduplicates; BM25 at :359 leaves scores untouched; dedup at :390 uses ID then content hash. |

### Does NOT Exist

- No existing lancedb optional extra or resolved SDK contract; TASK-3057 supplies version/API evidence.
- No satellite parrot/stores/__init__.py may be created; core owns namespace extension.
- Adding a dispatch key does not add StoreType/adaptive-router support.
- MMR is not provided by the planned LanceDB v1 backend; it needs explicit unsupported behavior.
- LanceDBOrigin is new; the current VectorStoreOrigin has no hybrid mode.
- Toolkit merged_top_k does not preserve native RRF order; only grouped sections preserve origin order.
- New helpers listed in dependency tasks are not pre-existing repository APIs. Use the gate/completion contracts, then verify their actual implementations.
- No guarantee of fully offline inference or concurrent-process correctness follows merely from opening a local LanceDB directory.

---

## Implementation Notes

### Pattern to Follow

Backend defects found here must be returned to the owning task or explicitly added to scope before editing its file. This task does not own lancedb.py.

Use the existing contracts above without changing unrelated shared behavior. Keep async public operations non-blocking, strict type hints, Pydantic structured records and black/isort formatting. Keep SDK access inside the embeddings backend, never in the origin adapter.

### Key Constraints

- Complete only this task's deliverable; do not implement later tasks opportunistically.
- Never remove or silently downgrade approved offline or concurrent-writer requirements.
- No schema overwrite, broad deletion, automatic version pruning, remote fallback or new storage server.
- Preserve caller documents and shared embedding ownership. Do not log document text, vectors, credentials or filter values.
- Respect optional dependency boundaries; follow approval policy before introducing unapproved packages.
- Capture test commands, dependency versions and outcomes under `artifacts/logs/TASK-3067-lancedb.log`; real-model/benchmark evidence must distinguish provisioning from execution.

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
1. Add exactly one key to `supported_stores` and change nothing else — *why*: two tests assert the map by exact equality, and the `faiss_store`/`arango` entries are deliberate pre-existing mismatches marked "do NOT fix".
2. Update BOTH exact-equality assertions — *why*: there are two, in different files (`test_store_backends_present.py:27` and `test_namespace_imports.py:126`); fixing one leaves a red suite.
3. Extend `STORE_BACKENDS` so the parametrized resolution test covers the new backend — *why*: otherwise nothing proves `parrot.stores.lancedb` resolves inside the satellite.
4. Assert the missing-extra error names the install target — *why*: spec §7 requires "selecting/opening LanceDB reports the exact install extra when missing"; a bare `ImportError` is a support ticket.

### `packages/ai-parrot/src/parrot/stores/__init__.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c "    'bigquery': 'BigQueryStore'," packages/ai-parrot/src/parrot/stores/__init__.py)
# AFTER — insert below `    'bigquery': 'BigQueryStore',` (verified: packages/ai-parrot/src/parrot/stores/__init__.py:12)
    'lancedb': 'LanceDBStore',
```
**Why**: this file must gain one line and nothing else. It has no eager backend imports — `from .postgres import PgVectorStore` is commented out at line 5 on purpose — and `VectorInterface._get_database_store` (`parrot/interfaces/vector.py:42`) resolves `parrot.stores.<name>` dynamically, so adding an import here would defeat the optional-extra design.

### `packages/ai-parrot-embeddings/tests/test_store_backends_present.py` (MODIFY — backend list)
```python
# occurrences: 1 (verified: grep -c 'STORE_BACKENDS = \["postgres", "milvus", "arango", "bigquery", "faiss_store"\]' packages/ai-parrot-embeddings/tests/test_store_backends_present.py)
# REPLACE line 7
STORE_BACKENDS = ["postgres", "milvus", "arango", "bigquery", "faiss_store", "lancedb"]
```
**Why**: appended rather than inserted so the parametrize ids of the existing five cases do not shift in CI history.

### `packages/ai-parrot-embeddings/tests/test_store_backends_present.py` (MODIFY — exact map)
```python
# occurrences: 1 (verified: grep -c "        'bigquery': 'BigQueryStore'," packages/ai-parrot-embeddings/tests/test_store_backends_present.py)
# AFTER — insert below `        'bigquery': 'BigQueryStore',` (verified: packages/ai-parrot-embeddings/tests/test_store_backends_present.py:36)
        'lancedb': 'LanceDBStore',
```
**Why**: extend the assertion, do NOT weaken it to a subset check — the exactness is the point of `test_supported_stores_unchanged`, and relaxing it would let a future accidental entry through unnoticed.

### `packages/ai-parrot-embeddings/tests/test_namespace_imports.py` (MODIFY — second exact map)
```python
# occurrences: 1 (verified: grep -c "            'bigquery': 'BigQueryStore'," packages/ai-parrot-embeddings/tests/test_namespace_imports.py)
# AFTER — insert below `            'bigquery': 'BigQueryStore',` (verified: packages/ai-parrot-embeddings/tests/test_namespace_imports.py:135)
            'lancedb': 'LanceDBStore',
```
**Why**: this is the second, easily-missed copy of the same assertion — note the deeper indentation (it sits inside a test class). Leave the `# pre-existing mismatch; do NOT fix` comments on `faiss_store` and `arango` exactly as they are.

### `packages/ai-parrot-embeddings/tests/test_lancedb_factory.py` (CREATE)
```python
"""Factory, tool and origin integration plus absence errors (FEAT-542, AC2)."""
from __future__ import annotations

import importlib  # verified: packages/ai-parrot-embeddings/tests/test_store_backends_present.py:2

import pytest


class TestDispatch:
    def test_supported_stores_resolves_lancedb_to_the_satellite(self):
        # FILL IN: import parrot.stores.lancedb, assert 'ai-parrot-embeddings' in __file__
        # — bounded by AC2
        raise NotImplementedError

    def test_no_other_mapping_changed(self):
        # FILL IN: the six pre-existing entries, values included — bounded by AC2
        raise NotImplementedError


class TestFactoryConfig:
    def test_storeconfig_requires_explicit_flat_index_type(self):
        # FILL IN: StoreConfig defaults index_type='IVF_FLAT' (models/stores.py:162), so a
        # factory user must override it; assert the actionable rejection message
        # — bounded by spec §2 config table, AC2
        raise NotImplementedError

    def test_default_tool_column_aliases_accepted(self):
        # FILL IN: table/collection, document/embedding/cmetadata/id — bounded by AC2
        raise NotImplementedError

    def test_non_null_dsn_rejected_in_favour_of_uri(self):
        # FILL IN — bounded by spec §2 last paragraph
        raise NotImplementedError


class TestMissingExtra:
    def test_selecting_lancedb_without_the_sdk_names_the_install_extra(self):
        # FILL IN: block lancedb from sys.modules in a subprocess; assert the error text
        # contains 'ai-parrot-embeddings[lancedb]' — bounded by spec §7, AC1
        raise NotImplementedError
```
**Why this shape**: `test_storeconfig_requires_explicit_flat_index_type` exists because `StoreConfig.index_type` defaults to `'IVF_FLAT'` (`packages/ai-parrot/src/parrot/models/stores.py:162`) while this backend supports `FLAT` only — that mismatch is listed in spec §7 as a known gotcha and will bite the first factory user otherwise. The missing-extra test runs in a subprocess because once `lancedb` is imported in-process you cannot un-import it reliably.

### FILL IN checklist
- [ ] `parrot/stores/__init__.py` — the single `lancedb` line, no imports added; bounded by AC2
- [ ] `test_store_backends_present.py` — `STORE_BACKENDS` plus the exact-map entry; bounded by AC2
- [ ] `test_namespace_imports.py` — the second exact-map entry; bounded by AC2
- [ ] `test_lancedb_factory.py` — all six bodies; bounded by AC1/AC2
- [ ] Preserve the `faiss_store`/`arango` "do NOT fix" comments verbatim in both test files

---

## Acceptance Criteria

- [ ] AC2 dispatch/factory paths pass with existing tool/origin consumers.
- [ ] Both exact-map tests add only the intended key and preserve namespace ownership.
- [ ] Real absence and presence subprocess tests prove optional-import behavior.
- [ ] Existing embeddings backend/namespace and origin suites pass.
- [ ] Tests in this task's Test Specification pass; failures are not hidden by mocks, skips or relaxed assertions where real SDK/model execution is required.
- [ ] Scope-owned code passes formatting/type checks appropriate to the repository, and the completion note records actual commands and evidence.

---

## Test Specification

| Test | Required behavior |
|---|---|
| `test_lancedb_dispatch_and_satellite_resolution` | Factory resolves concrete class in embeddings satellite. |
| `test_vector_tool_legacy_arguments` | Documented StoreConfig and default columns execute correctly. |
| `test_absent_sdk_actionable_and_other_imports_healthy` | Optional missing dependency doesn't break unrelated origins/stores. |

Intended command after dependencies are implemented:

```bash
uv run pytest packages/ai-parrot-embeddings/tests/test_lancedb_factory.py packages/ai-parrot-embeddings/tests/test_store_backends_present.py packages/ai-parrot-embeddings/tests/test_namespace_imports.py -v
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
7. Move this task to `sdd/tasks/completed/TASK-3067-lancedb-dispatch-compatibility.md`, update its per-spec entry to `done` with completion time and file path, and fill the completion note.
8. Commit only scoped implementation plus this task's SDD state. Follow the execution/review workflow before pushing.

---

## Completion Note

**Completed by**: not started
**Date**: not completed
**Notes**: Pending execution; no implementation or acceptance tests run during task decomposition.
**Deviations from spec**: The checked answers supersede stale prose; TASK-3057 reconciles that discrepancy before implementation.
