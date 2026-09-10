# TASK-3060: Compile safe metadata and parent filters

**Feature**: FEAT-542 — Local LanceDB Vector, Full-Text and Hybrid Search
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

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block below to its declared
> path nearly verbatim, then complete every `# FILL IN:` marker. Blocks were derived from
> the spec's §2 New Public Interfaces and re-verified against the Codebase Contract above
> when this task was written. This is NOT the full implementation: business-logic branches,
> edge cases and test bodies are `FILL IN` stubs by design. Never change a signature, class
> name, or file path the blueprint fixes.

### Steps (in order)
1. Compile to ONE conjunctive predicate string, never a chain of query-builder calls — *why*: spec §2 "Filters" warns that a builder can overwrite an earlier `where`; a single predicate has no such failure mode and is what both hybrid legs receive.
2. Validate against the declared `metadata_fields` projection before emitting any SQL — *why*: filtering an undeclared field must raise, not silently match nothing (spec §2).
3. Emit the parent-visibility clause as a separate, composable fragment — *why*: `delete_documents_by_filter` uses the same compiler *without* the search-only parent predicate (spec §2 last paragraph), so the two must be separable.
4. Write the hostile-input tests in the same commit as the compiler — *why*: this module is the injection boundary; an untested escaper is the vulnerability.

### `packages/ai-parrot-embeddings/src/parrot/stores/lancedb_filters.py` (CREATE)
```python
"""Typed predicate compiler for declared LanceDB metadata fields.

Pure string construction over a validated projection. Never interpolates an
unchecked identifier and never accepts a caller-supplied ``where`` expression.
"""
from __future__ import annotations

from typing import Any

from parrot.stores.lancedb_models import LanceDBConfig  # new in TASK-3059

PARENT_DOCUMENT_TYPES = ("parent", "parent_chunk")


class FilterCompilationError(ValueError):
    """Raised for unknown fields, bad operators, mixed lists or unsafe literals."""


def compile_metadata_filter(
    filters: dict[str, Any] | None,
    config: LanceDBConfig,
) -> str | None:
    """Compile a conjunctive predicate, or return None for no metadata restriction.

    Raises:
        FilterCompilationError: unknown field, undeclared operator, raw SQL,
            mixed-type list, list containing null, or a non-finite value.
    """
    # FILL IN: per-key dispatch to equality / IN / IS NULL; AND-join; empty list compiles
    # to a never-matching predicate; no str->number or str->bool coercion, and bool is not
    # an int — bounded by spec §2 "Filters, Parent Visibility and Limits" and AC5
    raise NotImplementedError


def parent_exclusion_clause() -> str:
    """Predicate excluding parents unless ``include_parents=True``."""
    # FILL IN: exclude rows where is_full_document is true OR document_type is one of
    # PARENT_DOCUMENT_TYPES; rows with MISSING markers stay visible; an is_chunk=True
    # marker must NOT override an explicit parent marker
    # — bounded by spec §2 (base-class semantics, NOT PostgreSQL's stricter version)
    raise NotImplementedError


def combine(*clauses: str | None) -> str | None:
    """AND-join the non-empty clauses, or return None when all are empty."""
    # FILL IN — bounded by spec §2 (one predicate reaches the SDK)
    raise NotImplementedError


def _quote_literal(value: Any) -> str:
    """Escape a scalar for inclusion in a predicate."""
    # FILL IN: correct quote escaping; reject NUL and non-finite numbers rather than
    # stringifying them — bounded by spec §2 and the hostile-input tests
    raise NotImplementedError
```
**Why this shape**: `parent_exclusion_clause` is a free function rather than a branch inside `compile_metadata_filter` precisely because deletion reuses the metadata half without it — folding them together is the bug spec §2 calls out. `_quote_literal` is the single escaping choke point, so every hostile-input test targets one function instead of a scattered set of f-strings. The docstring names the exact exception type because callers in TASK-3062–3065 must distinguish a user filter error from an SDK failure.

### `packages/ai-parrot-embeddings/tests/test_lancedb_filters.py` (CREATE)
```python
"""Filter and hostile-input matrix (FEAT-542, AC5). No SDK required."""
from __future__ import annotations

import pytest

from parrot.stores.lancedb_filters import (
    FilterCompilationError,
    compile_metadata_filter,
    parent_exclusion_clause,
)


class TestSupportedMappings:
    @pytest.mark.parametrize("value", [..., ...])  # FILL IN: scalar, list, None cases
    def test_typed_equality_membership_and_null(self, value):
        # FILL IN — bounded by spec §2 supported mapping values
        raise NotImplementedError

    def test_empty_membership_list_matches_nothing(self):
        # FILL IN — bounded by spec §2 (empty list is not "unrestricted")
        raise NotImplementedError


class TestRejections:
    @pytest.mark.parametrize("bad", [...])  # FILL IN: unknown field, raw SQL, mixed list,
    # nested filter object, list containing null, bool-as-int, str-as-number
    def test_rejected_before_any_sdk_call(self, bad):
        # FILL IN: assert FilterCompilationError — bounded by AC5
        raise NotImplementedError


class TestParentVisibility:
    def test_missing_markers_remain_visible(self):
        # FILL IN — bounded by spec §2 (legacy unmarked rows stay visible)
        raise NotImplementedError

    def test_is_chunk_cannot_override_explicit_parent_marker(self):
        # FILL IN — bounded by spec §2 contradictory-marker rule
        raise NotImplementedError


class TestHostileInput:
    @pytest.mark.parametrize("payload", [...])  # FILL IN: quotes, SQL-like payloads,
    # malicious identifiers, NUL bytes, non-finite numbers
    def test_no_injection_and_no_stringification(self, payload):
        # FILL IN — bounded by spec §2 "Compile only declared physical identifiers"
        raise NotImplementedError
```
**Why this shape**: every test class maps to one spec paragraph, so a failure names the rule that broke. These tests need no SDK and no `tmp_path` — keeping them pure is what makes this task parallelizable against the store work.

### FILL IN checklist
- [ ] `lancedb_filters.py::compile_metadata_filter` — dispatch, AND-join, no coercion; bounded by AC5
- [ ] `lancedb_filters.py::parent_exclusion_clause` — base-class semantics, not PostgreSQL's; bounded by AC5
- [ ] `lancedb_filters.py::_quote_literal` — escaping plus NUL/non-finite rejection; bounded by AC5
- [ ] `test_lancedb_filters.py` — all parametrize lists and bodies; bounded by AC5

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

**Completed by**: sdd-worker (Claude Sonnet 5)
**Date**: 2026-09-10
**Notes**: Implemented `lancedb_filters.py` per blueprint: `compile_metadata_filter` dispatches per-key to equality/membership/null with strict type checking against the field's declared type (`_declared_field_type` resolves standard reserved fields or `config.metadata_fields`), no string→number/bool coercion, `bool` explicitly excluded from `int` membership (checked via `type(item)` set, not `isinstance`, so `True`/`1` don't collapse into one "homogeneous" bucket). Empty IN-lists compile to `(1 = 0)` — a never-matching predicate distinct from "no restriction". `parent_exclusion_clause()` is a standalone function that never references `is_chunk`, so it cannot be overridden by it; missing markers (`IS NULL`) stay visible. `_quote_literal` is the single escaping choke point (doubled single-quotes, NUL-byte and non-finite-number rejection). `combine()` AND-joins into one parenthesized predicate string for reuse across vector/FTS/hybrid/delete callers.

`test_lancedb_filters.py`: 27 tests, all pass (`uv run pytest packages/ai-parrot-embeddings/tests/test_lancedb_filters.py -v`, log at `artifacts/logs/TASK-3060-lancedb.log`), covering the supported-mapping matrix, the full rejection list (unknown field, nested object, str-as-number, bool-as-int, mixed list, null-in-list), parent-visibility (missing markers visible, `is_chunk` cannot override), hostile input (quotes, SQL-like payloads, NUL bytes, non-finite floats, malicious identifiers), and delete-predicate reuse without the parent clause. `ruff check` clean.
**Deviations from spec**: None. No SDK query builder or delete execution touched (both explicitly out of scope) — this task ships only the pure string compiler.
