---
type: Wiki Overview
title: 'TASK-1034: MatryoshkaConfig Pydantic model + catalog validator'
id: doc:sdd-tasks-completed-task-1034-matryoshka-config-and-validation-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: First module of FEAT-150 (spec §3 Module 1). Defines the operator-facing
relates_to:
- concept: mod:parrot.embeddings
  rel: mentions
- concept: mod:parrot.embeddings.catalog
  rel: mentions
- concept: mod:parrot.embeddings.matryoshka
  rel: mentions
- concept: mod:parrot.exceptions
  rel: mentions
---

# TASK-1034: MatryoshkaConfig Pydantic model + catalog validator

**Feature**: FEAT-150 — Matryoshka Embedding Truncation
**Spec**: `sdd/specs/matryoshka-embedding-truncation.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

First module of FEAT-150 (spec §3 Module 1). Defines the operator-facing
data shape for Matryoshka truncation (`{"enabled": bool, "dimension": int}`)
and the configure-time validator that rejects unsupported truncation
dimensions before any embedding work is done.

This task produces the building block all later tasks reuse: TASK-1035
will call `validate_against_catalog` from `SentenceTransformerModel.__init__`,
and TASK-1038 will call it from `_provision_vector_store`.

---

## Scope

- Implement the `MatryoshkaConfig` Pydantic v2 model with fields
  `enabled: bool = False` and `dimension: Optional[int] = Field(default=None, gt=0)`.
- Add a model_validator that raises `ValueError` when `enabled=True` and
  `dimension` is `None`.
- Implement `validate_against_catalog(cfg: MatryoshkaConfig, model_name: str) -> None`
  that:
  - Looks up the model in `EMBEDDING_MODELS`.
  - Raises `ConfigError` if the model is not in the catalog.
  - Raises `ConfigError` if the model entry has no
    `matryoshka_dimensions` or it is empty.
  - Raises `ConfigError` if `cfg.dimension` is not in
    `matryoshka_dimensions`.
  - Returns `None` (passes silently) when `cfg.enabled` is `False`
    regardless of `dimension`.
- Write unit tests covering all four error paths and the happy path.

**NOT in scope**: changes to `SentenceTransformerModel`, registry, store
layer, handlers, or end-to-end integration tests. Those belong to later
tasks in this feature.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/embeddings/matryoshka.py` | CREATE | `MatryoshkaConfig` + `validate_against_catalog` |
| `packages/ai-parrot/tests/embeddings/test_matryoshka_config.py` | CREATE | Unit tests for the config and validator |

Do NOT modify `parrot/embeddings/__init__.py` to export the new symbols
in this task — that decision is part of TASK-1039 docs work (open
question §8 in the spec).

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from typing import Optional
from pydantic import BaseModel, Field, model_validator

from parrot.embeddings.catalog import EMBEDDING_MODELS  # verified: catalog.py:171
from parrot.exceptions import ConfigError                # verified: parrot/exceptions.py:45
```

### Existing Signatures to Use

```python
# parrot/embeddings/catalog.py
EMBEDDING_MODELS: List[Dict[str, Any]] = [...]  # line 171
# Each entry is a plain dict (not the Pydantic schema). Relevant keys for
# this task:
#   "model": str                          # the canonical model id
#   "matryoshka_dimensions": Optional[list[int]]   # may be absent or None
```

Catalog entries that DECLARE `matryoshka_dimensions` (verified):

| Model | Allowed dims |
|---|---|
| `nomic-ai/nomic-embed-text-v1.5` (line 779) | `[64, 128, 256, 512, 768]` |
| `mixedbread-ai/mxbai-embed-large-v1` (line 804) | `[128, 256, 512, 768, 1024]` |
| `google/embeddinggemma-300m` (line 831) | `[128, 256, 512, 768]` |
| `Snowflake/snowflake-arctic-embed-m-v1.5` (line 882) | `[128, 256, 384, 512, 768]` |

### Does NOT Exist

- ~~`EmbeddingModelEntry` exported from `parrot.embeddings`~~ — it is
  validation-only and intentionally NOT exported (`embeddings/__init__.py:11-13`).
  Read `EMBEDDING_MODELS` (the list of dicts) directly.
- ~~`get_model_recommendations()` returns matryoshka dims~~ — it returns
  ONLY `recommended_score_threshold` and `recommended_search_limit`
  (`catalog.py:1248-1275`).
- ~~`parrot.exceptions.MatryoshkaError`~~ — no such class. Use
  `ConfigError` for all validation failures in this feature.

---

## Implementation Notes

### Pattern to Follow

`MatryoshkaConfig` mirrors the Pydantic style already used by
`EmbeddingModelEntry` in `catalog.py:36-168` — Pydantic v2,
`@model_validator(mode="after")`, raise `ValueError` inside the
validator (Pydantic re-wraps as `ValidationError`).

`validate_against_catalog` is plain function, not a Pydantic validator —
it depends on `model_name` which is external to the config object.

### Key Constraints

- Pydantic v2 syntax (`model_validator(mode="after")`, `Field(gt=0)`).
- Raise `ConfigError` (not `ValueError`) from `validate_against_catalog`
  so callers can distinguish operator-config errors from model
  internal errors.
- Module-level code only — no imports from `huggingface.py` (would
  cause circular imports during catalog load).

### References in Codebase

- `parrot/embeddings/catalog.py:36-168` — Pydantic validation pattern.
- `parrot/exceptions.py:45` — `ConfigError(ParrotError)` definition.

---

## Acceptance Criteria

- [ ] `parrot/embeddings/matryoshka.py` exists with `MatryoshkaConfig`
      and `validate_against_catalog`.
- [ ] All unit tests pass: `pytest packages/ai-parrot/tests/embeddings/test_matryoshka_config.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/embeddings/matryoshka.py`
- [ ] Imports work: `from parrot.embeddings.matryoshka import MatryoshkaConfig, validate_against_catalog`
- [ ] `MatryoshkaConfig(enabled=True)` (no `dimension`) raises `ValueError`.
- [ ] `MatryoshkaConfig(enabled=False, dimension=None)` builds cleanly.
- [ ] `validate_against_catalog(MatryoshkaConfig(enabled=True, dimension=512), "nomic-ai/nomic-embed-text-v1.5")` returns `None`.
- [ ] Same call with `dimension=300` raises `ConfigError`.
- [ ] Same call with `model_name="BAAI/bge-base-en-v1.5"` (no `matryoshka_dimensions` field) raises `ConfigError`.
- [ ] Same call with `model_name="does-not-exist/foo"` raises `ConfigError`.
- [ ] When `cfg.enabled=False`, the validator returns `None` even if `model_name` is unknown.

---

## Test Specification

```python
# packages/ai-parrot/tests/embeddings/test_matryoshka_config.py
import pytest
from pydantic import ValidationError

from parrot.embeddings.matryoshka import MatryoshkaConfig, validate_against_catalog
from parrot.exceptions import ConfigError


class TestMatryoshkaConfig:
    def test_default_disabled(self):
        cfg = MatryoshkaConfig()
        assert cfg.enabled is False
        assert cfg.dimension is None

    def test_enabled_requires_dimension(self):
        with pytest.raises(ValidationError):
            MatryoshkaConfig(enabled=True)

    def test_dimension_must_be_positive(self):
        with pytest.raises(ValidationError):
            MatryoshkaConfig(enabled=True, dimension=0)

    def test_disabled_with_dimension_ok(self):
        cfg = MatryoshkaConfig(enabled=False, dimension=512)
        assert cfg.enabled is False


class TestValidateAgainstCatalog:
    def test_disabled_skips_validation(self):
        cfg = MatryoshkaConfig(enabled=False)
        assert validate_against_catalog(cfg, "anything-goes") is None

    def test_supported_model_and_dim(self):
        cfg = MatryoshkaConfig(enabled=True, dimension=512)
        assert validate_against_catalog(cfg, "nomic-ai/nomic-embed-text-v1.5") is None

    def test_unsupported_dim(self):
        cfg = MatryoshkaConfig(enabled=True, dimension=300)
        with pytest.raises(ConfigError, match="matryoshka_dimensions"):
            validate_against_catalog(cfg, "nomic-ai/nomic-embed-text-v1.5")

    def test_model_without_matryoshka_metadata(self):
        cfg = MatryoshkaConfig(enabled=True, dimension=512)
        with pytest.raises(ConfigError):
            validate_against_catalog(cfg, "BAAI/bge-base-en-v1.5")

    def test_unknown_model(self):
        cfg = MatryoshkaConfig(enabled=True, dimension=512)
        with pytest.raises(ConfigError):
            validate_against_catalog(cfg, "does-not-exist/foo")
```

---

## Agent Instructions

When you pick up this task:

1. Read the spec at `sdd/specs/matryoshka-embedding-truncation.spec.md`,
   focusing on §2 Data Models and §3 Module 1.
2. Verify the catalog entries listed in the contract still declare
   `matryoshka_dimensions` (`grep -n matryoshka_dimensions packages/ai-parrot/src/parrot/embeddings/catalog.py`).
3. Implement and test.
4. Move this file to `tasks/completed/` and update the per-spec index.

---

## Completion Note

**Completed by**: Claude Sonnet 4.6 (sdd-worker)
**Date**: 2026-05-06
**Notes**: Implemented MatryoshkaConfig (Pydantic v2 with model_validator) and validate_against_catalog. All 16 unit tests pass. No deviations from spec.
**Deviations from spec**: None
