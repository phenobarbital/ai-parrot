# TASK-3059: Define LanceDB configuration, schema and identities

**Feature**: FEAT-542 — Local LanceDB Vector, Full-Text and Hybrid Search
**Spec**: `sdd/specs/lancedb-vector-store.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h) — target 4 hours
**Depends-on**: TASK-3057
**Assigned-to**: unassigned
**Parallel**: true
**Parallelism notes**: Independent of manifest packaging and coordinator implementation after the gate. File ownership is disjoint from other eligible parallel tasks; dependencies still gate start.
**Acceptance coverage**: AC3, AC4, AC5

---

## Context

M1 data contract shared by persistence, search and the origin. Must freeze names/types before those tasks.

The spec is marked approved. Its checked section 8 answers require fully offline agent operation after provisioning, concurrent independent writers, graph federation only, and whole-origin failure; they override older draft assumptions. TASK-3057 must reconcile the spec and prove the SDK/offline/concurrency contracts before dependent implementation begins. Do not reinstate single-writer-only or storage-only-offline behavior.

---

## Scope

- Implement LanceDBConfig, version-1 manifest and LanceDBHybridHit exactly as reconciled spec; distinguish explicitly supplied creation defaults from manifest-derived reopen settings.
- **Open question gating this contract — spec §8 Q6 (raised by design research S2, spec §9).** Whether `LanceDBHybridHit` must also carry the per-leg vector and lexical component scores/ranks alongside the fused RRF relevance is undecided by the user. This task freezes that model for every downstream module, so: implement the single fused score plus `score_kind`/`higher_is_better` as specified, and do **not** invent component fields on your own. If TASK-3057's gate recorded that the pinned SDK exposes pre-fusion `_distance`/`_score` columns on a hybrid query, say so in the completion note so the question can be decided cheaply; if Q6 has been answered "yes" by the time you start, add the fields then rather than retrofitting after M2–M4 consume the model.
- Build fixed Arrow row schema with original document, float32 vector, canonical JSON and nullable typed metadata projections. Validate reserved fields, finite numbers, dimensions and supported JSON types.
- Implement ID precedence/conflict checks, canonical SHA-256 fallback calculated before augmentation, and collection-UUID namespaced result IDs.
- Add deterministic provider and corpus fixtures including ZXQ731, semantic-only match, two sources, null/absent fields, parents, contradictory markers and cross-collection ID overlap. Freeze pure helper signatures in the completion note.

**NOT in scope**: SDK I/O, query execution, runtime locks, source document mutation and backend registration.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-embeddings/src/parrot/stores/lancedb_models.py` | CREATE | Pydantic configuration, manifest, hybrid hit, schema and pure identity helpers |
| `packages/ai-parrot-embeddings/tests/test_lancedb_models.py` | CREATE | Strict model/schema/identity tests |
| `packages/ai-parrot-embeddings/tests/lancedb_fixtures.py` | CREATE | Deterministic 8-D provider and 24-document corpus for store tests |

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

### Does NOT Exist

- LanceDBConfig, LanceDBHybridHit and lancedb_models.py are new task deliverables, not current core types.
- A shared HybridSearchResult or globally comparable origin score does not exist.
- New helpers listed in dependency tasks are not pre-existing repository APIs. Use the gate/completion contracts, then verify their actual implementations.
- No guarantee of fully offline inference or concurrent-process correctness follows merely from opening a local LanceDB directory.

---

## Implementation Notes

### Pattern to Follow

Independent of manifest packaging and coordinator implementation after the gate. Do not import the tools distribution or eagerly import lancedb.

Use the existing contracts above without changing unrelated shared behavior. Keep async public operations non-blocking, strict type hints, Pydantic structured records and black/isort formatting. Keep SDK access inside the embeddings backend, never in the origin adapter.

### Key Constraints

- Complete only this task's deliverable; do not implement later tasks opportunistically.
- Never remove or silently downgrade approved offline or concurrent-writer requirements.
- No schema overwrite, broad deletion, automatic version pruning, remote fallback or new storage server.
- Preserve caller documents and shared embedding ownership. Do not log document text, vectors, credentials or filter values.
- Respect optional dependency boundaries; follow approval policy before introducing unapproved packages.
- Capture test commands, dependency versions and outcomes under `artifacts/logs/TASK-3059-lancedb.log`; real-model/benchmark evidence must distinguish provisioning from execution.

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
1. Write `LanceDBConfig` first and make every other symbol depend on it — *why*: spec §2 "Configuration and Compatibility" makes normalization a one-time step that happens before any SDK call, so the validated config is the input to the schema builder, not a parallel source of truth.
2. Build the Arrow schema from the config, never from the first row — *why*: spec §2 forbids first-row inference; inferred schemas silently change type when a nullable field is absent in row one.
3. Keep every identity helper pure (no I/O, no SDK) — *why*: TASK-3063 calls them before writes and TASK-3069 re-derives them in a second process; a helper that touches a connection cannot be used in either place.
4. Ship `lancedb_fixtures.py` in the same task as the models — *why*: five downstream test modules import the 24-document corpus, and a fixture written per-task drifts.

### `packages/ai-parrot-embeddings/src/parrot/stores/lancedb_models.py` (CREATE)
```python
"""Validated configuration, manifest, schema and identity for the LanceDB backend.

Pure module: no SDK import, no I/O. Everything here is consumed by
``lancedb.py`` (TASK-3062+) and re-derived independently by tests.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, Field  # verified: packages/ai-parrot/src/parrot/stores/models.py:13

SCHEMA_VERSION = 1
RESERVED_METADATA_KEY = "_lancedb"
STANDARD_STRING_FIELDS = ("source", "source_type", "parent_id", "document_type")
STANDARD_BOOL_FIELDS = ("is_full_document", "is_chunk")


class LanceDBConfig(BaseModel):
    """Backend-owned settings, validated once before any SDK operation."""

    uri: str
    collection_name: str = "my_collection"
    dimension: int = 768
    metric_type: Literal["COSINE"] = "COSINE"
    index_type: Literal["FLAT"] = "FLAT"
    embedding_id: str | None = None
    metadata_fields: dict[str, Literal["str", "bool", "int", "float"]] = Field(default_factory=dict)
    read_consistency_interval_seconds: float = 0.0
    batch_size: int = 128

    # FILL IN: validators for uri (local dir, canonicalized, no URI scheme), collection_name
    # (`[A-Za-z_][A-Za-z0-9_]{0,127}`), dimension (> 0), the two numeric bounds, and the
    # `table`/`collection_name` alias conflict raising ValueError
    # — bounded by spec §2 "Configuration and Compatibility" table and AC3


class CollectionManifest(BaseModel):
    """Versioned identity persisted in the Arrow schema metadata."""

    schema_version: int = SCHEMA_VERSION
    collection_uuid: str
    dimension: int
    metric_type: str
    embedding_fingerprint: str
    metadata_fields: dict[str, str]

    # FILL IN: compatibility check against a live LanceDBConfig, raising an actionable
    # error that never migrates or overwrites — bounded by spec §2 and AC3


class LanceDBHybridHit(BaseModel):
    """Backend-owned hybrid result. Deliberately has no ``distance`` alias."""

    id: str
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    score: float
    score_kind: Literal["rrf"] = "rrf"
    higher_is_better: Literal[True] = True
    # NOTE: spec §8 Q6 (design research S2) asks whether per-leg vector/lexical component
    # scores belong here. It is UNDECIDED. Do not add component fields on your own.


```
**Why this block**: `LanceDBHybridHit` carries the fused score plus its kind and direction and nothing else, because spec §2 fixes that contract and §8 Q6 has not been answered — adding component fields here would pre-empt a decision the user still owns and would ripple into M2–M4.

### `packages/ai-parrot-embeddings/src/parrot/stores/lancedb_models.py` (CREATE — part 2, same file)
```python
def embedding_fingerprint(settings: dict[str, Any]) -> str:
    """Stable identity for an embedding configuration, excluding credentials."""
    # FILL IN: drop credential-shaped keys, canonicalize, sha256 the JSON; contextual
    # settings are part of the fingerprint — bounded by spec §2 and AC3
    raise NotImplementedError


def record_id_for(text: str, metadata: dict[str, Any]) -> str:
    """Fallback identity: sha256 of ORIGINAL text plus canonical original metadata."""
    # FILL IN: compute before contextual augmentation — bounded by spec §2 "Data Models"
    raise NotImplementedError


def namespaced_id(collection_uuid: str, record_id: str) -> str:
    """``lancedb:<collection_uuid>:<percent-encoded record_id>``."""
    # FILL IN: percent-encode the record id — bounded by AC3 (no cross-collection collision)
    raise NotImplementedError


def build_arrow_schema(config: LanceDBConfig, manifest: CollectionManifest):
    """Explicit Arrow schema carrying the manifest in schema metadata."""
    # FILL IN: import pyarrow lazily inside this function so the module stays importable
    # without the extra; fields per spec §2 row table (record_id, document, embedding,
    # metadata_json, meta_<field>) — bounded by AC3
    raise NotImplementedError
```
**Why this shape**: `LanceDBHybridHit` carries the fused score plus its kind and direction and nothing else, because spec §2 fixes that contract and §8 Q6 has not been answered — adding component fields here would pre-empt a decision the user still owns and would ripple into M2–M4. `build_arrow_schema` imports pyarrow inside the function so this module can be imported (and unit-tested) with no optional extra installed, which is what lets TASK-3058's import guard pass. Signatures here are frozen for every downstream task; renaming one is not a local choice.

### `packages/ai-parrot-embeddings/tests/lancedb_fixtures.py` (CREATE)
```python
"""Deterministic fixtures shared by every LanceDB test module (FEAT-542).

Not a test module. Imported by test_lancedb_models/filters/lifecycle/mutations/
vector_search/fts_hybrid/store/multiprocess.
"""
from __future__ import annotations

from typing import Any

EMBEDDING_DIMENSION = 8
EMBEDDING_IDENTITY = "lancedb-test-embedding-v1"


class DeterministicEmbedding:
    """8-D provider with call counters and no downloads."""

    def __init__(self) -> None:
        self.embed_documents_calls = 0
        self.embed_query_calls = 0

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        # FILL IN: deterministic nonzero vectors derived from the text; increment counter
        # — bounded by spec §4 "Test Data / Fixtures"
        raise NotImplementedError

    async def embed_query(self, text: str) -> list[float]:
        # FILL IN: same mapping as embed_documents; increment counter
        raise NotImplementedError


def corpus() -> list[dict[str, Any]]:
    """The 24 fixed documents the spec's acceptance matrix is written against."""
    # FILL IN: child chunks across two sources; the lexical identifier ZXQ731; a
    # semantic-only neighbour with non-overlapping query text; explicit parents;
    # contradictory parent/chunk markers; legacy unmarked rows; null/absent fields;
    # quoted filter values — bounded by spec §4 "Test Data / Fixtures"
    raise NotImplementedError
```
**Why this shape**: the counters on the provider are what let TASK-3062/3065 prove FTS never constructs or invokes a model (AC6) — without them that assertion is untestable. Dimension 8 keeps vectors readable in failure output; it is not a performance choice. Two collections with overlapping logical IDs come from the same corpus helper so the identity-isolation test in TASK-3069 cannot drift from the ingest tests.

### `packages/ai-parrot-embeddings/tests/test_lancedb_models.py` (CREATE)
```python
"""Strict model, schema and identity tests (FEAT-542, AC3)."""
from __future__ import annotations

import pytest

from parrot.stores.lancedb_models import (  # new in this task
    CollectionManifest,
    LanceDBConfig,
    LanceDBHybridHit,
    embedding_fingerprint,
    namespaced_id,
    record_id_for,
)


class TestLanceDBConfig:
    def test_rejects_uri_schemes_and_canonicalizes_local_path(self, tmp_path):
        # FILL IN — bounded by spec §2 config table (reject schemes, no directory fallback)
        raise NotImplementedError

    def test_conflicting_table_and_collection_name_raise(self):
        # FILL IN — bounded by spec §2 (alias conflict is ValueError, not last-wins)
        raise NotImplementedError


class TestIdentity:
    def test_fingerprint_excludes_credentials_and_includes_contextual_settings(self):
        # FILL IN — bounded by AC3
        raise NotImplementedError

    def test_namespaced_ids_do_not_collide_across_collections(self):
        # FILL IN: same record_id, two collection UUIDs — bounded by AC3
        raise NotImplementedError


class TestHybridHit:
    def test_has_no_distance_alias(self):
        # FILL IN: assert 'distance' is not an attribute — bounded by spec §2 score contracts
        raise NotImplementedError
```
**Why this shape**: `test_has_no_distance_alias` is a negative test on purpose — `SearchResult.distance` returns `score` unchanged (`packages/ai-parrot/src/parrot/models/stores.py:74`), and the whole reason for a separate hybrid type is that an RRF relevance must never be readable as a distance.

### FILL IN checklist
- [ ] `lancedb_models.py::LanceDBConfig` — all field validators; bounded by spec §2 config table, AC3
- [ ] `lancedb_models.py::CollectionManifest` — non-destructive compatibility check; bounded by AC3
- [ ] `lancedb_models.py::embedding_fingerprint` / `record_id_for` / `namespaced_id` — pure implementations; bounded by AC3/AC4
- [ ] `lancedb_models.py::build_arrow_schema` — lazy pyarrow import, field list; bounded by AC3
- [ ] `lancedb_fixtures.py::DeterministicEmbedding` / `corpus` — 8-D vectors and the 24 documents; bounded by spec §4
- [ ] `test_lancedb_models.py` — all six test bodies; bounded by AC3
- [ ] Do NOT add component-score fields to `LanceDBHybridHit`; bounded by spec §8 Q6

---

## Acceptance Criteria

- [ ] U1 configuration/schema matrix passes with strict typing, no silent coercion or inferred first-row schema.
- [ ] Canonical IDs are reproducible and unrelated collections cannot collide on local ID alone.
- [ ] Hybrid payload remains backend-owned with explicit RRF direction and no distance alias.
- [ ] Fixtures require no network/downloads and helper contracts are documented for dependent tasks.
- [ ] Tests in this task's Test Specification pass; failures are not hidden by mocks, skips or relaxed assertions where real SDK/model execution is required.
- [ ] Scope-owned code passes formatting/type checks appropriate to the repository, and the completion note records actual commands and evidence.

---

## Test Specification

| Test | Required behavior |
|---|---|
| `test_config_explicit_and_manifest_defaults` | Reopen doesn't accidentally overwrite persisted dimension/projection/settings. |
| `test_json_projection_and_hybrid_score_model` | Roundtrip nested JSON; reject invalid fields; hybrid has no distance alias. |
| `test_stable_identity_and_collection_namespace` | Deterministic IDs, aligned explicit IDs, conflict/duplicate validation and collection isolation. |

Intended command after dependencies are implemented:

```bash
uv run pytest packages/ai-parrot-embeddings/tests/test_lancedb_models.py -v
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
7. Move this task to `sdd/tasks/completed/TASK-3059-lancedb-models-schema-identity.md`, update its per-spec entry to `done` with completion time and file path, and fill the completion note.
8. Commit only scoped implementation plus this task's SDD state. Follow the execution/review workflow before pushing.

---

## Completion Note

**Completed by**: not started
**Date**: not completed
**Notes**: Pending execution; no implementation or acceptance tests run during task decomposition.
**Deviations from spec**: The checked answers supersede stale prose; TASK-3057 reconciles that discrepancy before implementation.
