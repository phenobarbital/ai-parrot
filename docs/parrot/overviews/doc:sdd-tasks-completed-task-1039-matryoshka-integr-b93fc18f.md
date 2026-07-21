---
type: Wiki Overview
title: 'TASK-1039: Matryoshka end-to-end integration tests + documentation'
id: doc:sdd-tasks-completed-task-1039-matryoshka-integration-and-docs-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Final task for FEAT-150. Adds the heavy end-to-end test that loads
relates_to:
- concept: mod:parrot.embeddings
  rel: mentions
- concept: mod:parrot.embeddings.huggingface
  rel: mentions
- concept: mod:parrot.embeddings.matryoshka
  rel: mentions
- concept: mod:parrot.embeddings.registry
  rel: mentions
---

# TASK-1039: Matryoshka end-to-end integration tests + documentation

**Feature**: FEAT-150 — Matryoshka Embedding Truncation
**Spec**: `sdd/specs/matryoshka-embedding-truncation.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1034, TASK-1035, TASK-1036, TASK-1037, TASK-1038
**Assigned-to**: unassigned

---

## Context

Final task for FEAT-150. Adds the heavy end-to-end test that loads
real `nomic-embed-text-v1.5` weights, ingests a small fixture, and
retrieves with a 512-dim Matryoshka-truncated vector against a real
pgvector table. Also documents the feature for operators.

Implements spec §3 Module 6 (the integration / E2E slice that the
per-module unit tests in earlier tasks do NOT cover) and the
"Documentation updated" acceptance criterion.

---

## Scope

- Add an integration test that, given a running pgvector test
  database (skip with a clear marker when unavailable), exercises
  the full pipeline: bot configure → table create with `vector(512)`
  → ingest 5 short documents → query → top-1 has cosine ≥ 0.5.
  Use `nomic-ai/nomic-embed-text-v1.5` with
  `matryoshka={"enabled": True, "dimension": 512}`.
- Add a no-Matryoshka snapshot test: encoding `["hello world"]` with
  the catalog default (no `matryoshka` flag) must return a vector
  bit-equal to a small pre-recorded fixture (use a tiny stub model,
  not real weights, to avoid CI flakiness on weight changes).
- Add operator documentation. Pick whichever existing doc is most
  appropriate (likely a new short subsection in
  `docs/architecture/embeddings.md` or wherever embeddings are
  already documented; if none exists, add a short markdown file
  under `docs/`):
  - The flag shape inside `vector_store_config['embedding_model']`.
  - Which catalog models support it and their allowed dimensions.
  - The configure-time validation rules.
  - The operational caveat: changing `matryoshka.dimension` after
    ingestion requires drop/recreate of the pgvector table and full
    re-ingestion.
  - A worked example using `nomic-embed-text-v1.5` at 512 dims.
- Decide and implement the spec's open question §8 about whether
  `validate_against_catalog` is exported from `parrot.embeddings`.
  Recommendation: export it (alongside `get_model_recommendations`)
  for symmetry. Update `parrot/embeddings/__init__.py` and
  `__all__`.

**NOT in scope**: any further changes to the embedding model,
registry, store, or handler — those are locked by the prior tasks.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/integration/embeddings/test_matryoshka_e2e.py` | CREATE | Real-weights end-to-end test (skipped if no pgvector) |
| `packages/ai-parrot/tests/embeddings/test_matryoshka_snapshot.py` | CREATE | Bit-equal snapshot for the disabled path |
| `packages/ai-parrot/src/parrot/embeddings/__init__.py` | MODIFY | Export `MatryoshkaConfig`, `validate_against_catalog` |
| `docs/architecture/embeddings.md` (or new short file in `docs/`) | CREATE/MODIFY | Operator docs for the flag |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.embeddings.matryoshka import MatryoshkaConfig, validate_against_catalog
from parrot.embeddings.huggingface import SentenceTransformerModel
from parrot.embeddings.registry import EmbeddingRegistry
```

### Existing Signatures to Use

```python
# parrot/embeddings/__init__.py
from .registry import EmbeddingRegistry              # noqa: E402
from .catalog import (
    EMBEDDING_MODELS,
    USE_CASE_DESCRIPTIONS,
    get_embedding_models,
    get_model_recommendations,
    get_use_cases,
)

supported_embeddings = {
    'huggingface': 'SentenceTransformerModel',
    'google': 'GoogleEmbeddingModel',
    'openai': 'OpenAIEmbeddingModel',
}

__all__ = [
    "supported_embeddings",
    "EmbeddingRegistry",
    "EMBEDDING_MODELS",
    "USE_CASE_DESCRIPTIONS",
    "get_embedding_models",
    "get_model_recommendations",
    "get_use_cases",
]
```

### Does NOT Exist

- ~~A pre-existing `docs/architecture/embeddings.md`~~ — verify with
  `ls docs/architecture/` before deciding whether to extend or
  create. The task allows either.
- ~~A pgvector test fixture for matryoshka~~ — must be added in this
  task. Skip cleanly with `pytest.skip(...)` when the test database
  URL env var is missing.

---

## Implementation Notes

### Pattern to Follow

For the end-to-end test, mirror the existing real-weights integration
tests under `packages/ai-parrot/tests/integration/` (e.g. parent-child
pgvector tests at `tests/integration/stores/test_parent_child_pgvector.py`).
Reuse the same test database fixture and skip pattern.

For the snapshot test, store the expected vector as a Python list
literal inside the test file (so it survives version control diffs
clearly). Stub `_create_embedding` to return a deterministic numpy
array so the snapshot is stable across machines.

### Documentation outline

Title: "Matryoshka embedding truncation"

Sections:
1. What and why — one paragraph summarising MRL.
2. Configuration — JSON example inside `vector_store_config`.
3. Supported models (table) — read from
   `EMBEDDING_MODELS` entries with `matryoshka_dimensions`.
4. Validation rules — what raises `ConfigError` and when.
5. Operational caveat — pgvector column shape is fixed; dim changes
   require drop/recreate.
6. Performance hint — smaller dims = smaller HNSW index; useful on
   CPU-only deployments.

Keep it short — one page max.

### Key Constraints

- The integration test MUST be marked `@pytest.mark.integration` (or
  whatever marker the project uses) and skipped automatically when
  the DB env var is missing.
- The snapshot test MUST be deterministic and CPU-friendly (stub
  model, no torch random ops in the path).

---

## Acceptance Criteria

- [ ] `pytest packages/ai-parrot/tests/integration/embeddings/test_matryoshka_e2e.py -v -m integration` passes when the test pgvector DB is configured; skips cleanly otherwise.
- [ ] `pytest packages/ai-parrot/tests/embeddings/test_matryoshka_snapshot.py -v` passes deterministically.
- [ ] Full embedding suite passes: `pytest packages/ai-parrot/tests/embeddings/ -v`.
- [ ] Full handler suite passes: `pytest packages/ai-parrot/tests/handlers/ -v`.
- [ ] `from parrot.embeddings import MatryoshkaConfig, validate_against_catalog` works (added to `__all__`).
- [ ] Documentation page exists, lists the four catalog models with their allowed dims, and includes a worked example.
- [ ] All FEAT-150 acceptance criteria from the spec §5 are satisfied.

---

## Test Specification

```python
# packages/ai-parrot/tests/integration/embeddings/test_matryoshka_e2e.py
import os
import pytest

pytestmark = pytest.mark.integration


@pytest.fixture
def pgvector_dsn():
    dsn = os.environ.get("PARROT_TEST_PG_DSN")
    if not dsn:
        pytest.skip("PARROT_TEST_PG_DSN not set")
    return dsn


@pytest.mark.asyncio
async def test_end_to_end_matryoshka_search(pgvector_dsn):
    """Configure a bot with nomic@512, ingest 5 docs, query, expect cosine ≥ 0.5."""
    # 1. Build bot with vector_store_config containing matryoshka 512
    # 2. Provision the pgvector table — must be vector(512)
    # 3. Ingest 5 short HR-policy-like docs
    # 4. Query with a phrase that closely matches doc[2]
    # 5. Assert top-1 has score ≥ 0.5 and is doc[2]
    ...
```

```python
# packages/ai-parrot/tests/embeddings/test_matryoshka_snapshot.py
import numpy as np
import pytest

# A pre-recorded reference vector produced by the stub model. Re-record
# only if the stub itself changes — never if the real model changes.
_EXPECTED_DISABLED_VEC = [...]  # 768 floats

@pytest.mark.asyncio
async def test_disabled_path_bit_equal(monkeypatch):
    ...
```

---

## Agent Instructions

1. Verify TASK-1034..1038 are all completed.
2. Re-read spec §5 Acceptance Criteria — every item there must be
   true after this task lands.
3. Implement integration test, snapshot test, and docs.
4. Run the full test suite to confirm nothing regressed.

---

## Completion Note

**Completed by**: Claude Sonnet 4.6 (sdd-worker)
**Date**: 2026-05-06
**Notes**: Implemented all deliverables: integration E2E test (skips without PG_VECTOR_DSN),
snapshot test (4 tests, all pass), `__init__.py` exports for `MatryoshkaConfig` and
`validate_against_catalog`, and `docs/matryoshka-embeddings.md` operator documentation
covering all 4 catalog models with their allowed dims, validation rules, operational
caveat, performance hints, and a worked example. 247/247 embedding tests pass. Lint clean.
**Deviations from spec**: Documentation placed at `docs/matryoshka-embeddings.md` (not
`docs/architecture/embeddings.md`) because the `docs/architecture/` directory does not
exist in the codebase; existing convention is flat files in `docs/` (e.g.
`docs/contextual-embedding.md`).
