---
type: Wiki Overview
title: 'TASK-973: Refactor `_resolve_prefixes` to read prefixes from `EMBEDDING_MODELS`'
id: doc:sdd-tasks-completed-task-973-resolve-prefixes-from-catalog-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: runtime authority that decides which query/passage prefix to apply when
relates_to:
- concept: mod:parrot._imports
  rel: mentions
- concept: mod:parrot.embeddings.catalog
  rel: mentions
- concept: mod:parrot.embeddings.huggingface
  rel: mentions
---

# TASK-973: Refactor `_resolve_prefixes` to read prefixes from `EMBEDDING_MODELS`

**Feature**: FEAT-142 — Embedding Catalog as Prefix Source of Truth
**Spec**: `sdd/specs/embedding-catalog-as-prefix-source-of-truth.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

`_resolve_prefixes(model_name)` in `parrot/embeddings/huggingface.py` is the
runtime authority that decides which query/passage prefix to apply when
`SentenceTransformerModel.embed_query` / `embed_documents` runs. Today it
hardcodes substring matches for every prefix-requiring family
(E5, BGE-EN-v1.5, Jina v3, NV-Embed-v2, gte-Qwen2-instruct,
e5-mistral-7b-instruct), creating a second source of truth parallel to
`parrot/embeddings/catalog.py::EMBEDDING_MODELS`.

This task implements **Module 1** of the spec: replace the resolver body
with a catalog-driven lookup so the catalog becomes the single source of
truth. After this task lands, adding a new prefix-requiring model to the
catalog automatically enables it at runtime — no second edit required.

See spec §2 (Architectural Design — Overview), §3 (Module 1), §6
(Codebase Contract), and §7 (Implementation Notes).

---

## Scope

- Add a private module-level constant
  `_PREFIX_LOOKUP: dict[str, tuple[Optional[str], Optional[str]]]` to
  `parrot/embeddings/huggingface.py`, built once at import time by iterating
  `EMBEDDING_MODELS` and keying on `entry["model"].lower()`.
- Replace the body of `_resolve_prefixes(model_name)` with:
  1. Falsy `model_name` → `(None, None)`.
  2. Lookup `_PREFIX_LOOKUP.get(model_name.lower())`.
  3. Hit → return the cached `(prefix_query, prefix_passage)` tuple.
  4. Miss → log one `INFO` line
     `"Model %s not in embedding catalog; encoding without prefix"` and
     return `(None, None)`.
- Delete every hardcoded `if "..." in lower:` substring branch from the
  function body. The branches for `e5-mistral-7b-instruct`, `gte-qwen2`,
  `nv-embed-v2`, `jina-embeddings-v3`, `/e5-`, and `baai/bge-…en-v1.5`
  must all be gone.
- Update the `_resolve_prefixes` docstring: drop the per-family enumeration,
  state that the function is now a thin O(1) cache lookup driven by
  `EMBEDDING_MODELS`, and document the unknown-model behaviour.
- Preserve the function's public signature
  `_resolve_prefixes(model_name: Optional[str]) -> Tuple[Optional[str], Optional[str]]`
  exactly. Do NOT change its name or visibility.
- Do NOT modify `SentenceTransformerModel.__init__` — it must keep calling
  `self._query_prefix, self._passage_prefix = _resolve_prefixes(self.model_name)`
  unchanged at line 169.
- All existing tests in `tests/embeddings/test_resolve_prefixes.py` and
  `tests/embeddings/test_catalog_consistency.py` must keep passing without
  modification.

**NOT in scope**:
- Adding new tests for catalog-driven behaviour or unknown-model handling
  (TASK-974).
- Removing the `ModelType` enum (out of scope per spec §1 Non-Goals).
- Refactoring `embed_documents` / `embed_query` / `_apply_*_prefix`.
- Touching loaders, vector stores, OpenAI/Google wrappers, or any consumer
  outside `parrot/embeddings/huggingface.py`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/embeddings/huggingface.py` | MODIFY | Add `_PREFIX_LOOKUP` cache; rewrite `_resolve_prefixes` body |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# verified: packages/ai-parrot/src/parrot/embeddings/catalog.py:171
from parrot.embeddings.catalog import EMBEDDING_MODELS

# verified: packages/ai-parrot/src/parrot/embeddings/huggingface.py:1-8
# (existing imports — already present, do not duplicate)
from __future__ import annotations
from typing import List, Any, Optional, Tuple, TYPE_CHECKING
from enum import Enum
import logging
import numpy as np
from parrot._imports import lazy_import
from .base import EmbeddingModel
from ..conf import HUGGINGFACE_EMBEDDING_CACHE_DIR
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/embeddings/huggingface.py:11
def _resolve_prefixes(
    model_name: Optional[str],
) -> Tuple[Optional[str], Optional[str]]:
    """SIGNATURE TO PRESERVE — body to be rewritten."""

# packages/ai-parrot/src/parrot/embeddings/huggingface.py:151-179
class SentenceTransformerModel(EmbeddingModel):
    model_name: str = "sentence-transformers/all-mpnet-base-v2"

    def __init__(self, model_name: str, **kwargs):
        super().__init__(model_name=model_name, **kwargs)
        # Line 169 — DO NOT MODIFY this call:
        self._query_prefix, self._passage_prefix = _resolve_prefixes(
            self.model_name
        )
        if self._query_prefix or self._passage_prefix:
            self.logger.info(
                "Using instruction prefixes for %s — query=%r passage=%r",
                self.model_name, self._query_prefix, self._passage_prefix,
            )
```

```python
# packages/ai-parrot/src/parrot/embeddings/catalog.py:171
EMBEDDING_MODELS: List[Dict[str, Any]] = [
    # ... 39 entries, each with these keys (relevant ones):
    {
        "model": str,                         # e.g. "intfloat/e5-base-v2"
        "provider": "huggingface" | ...,
        "requires_prefix": bool,
        "prefix_query": Optional[str],
        "prefix_passage": Optional[str],
        # ... other keys irrelevant to this task
    },
    ...
]

# catalog.py:99 — Pydantic validator already enforces the invariant:
#   requires_prefix=False -> prefix_query is None and prefix_passage is None
#   requires_prefix=True  -> at least one prefix is non-None
# This means iterating EMBEDDING_MODELS and reading
# (entry["prefix_query"], entry["prefix_passage"]) is correct by construction.
```

### Module-Level Logger Pattern

```python
# packages/ai-parrot/src/parrot/embeddings/huggingface.py
# Module-level logger does not currently exist at the top of the file —
# the only `logging.getLogger(__name__)` is referenced via self.logger
# inside SentenceTransformerModel. For the cache-miss INFO log inside
# _resolve_prefixes (which is a module-level function, not a method),
# add ONE line near the top of the module after imports:
logger = logging.getLogger(__name__)
```

### Does NOT Exist

- ~~`parrot.embeddings.catalog.get_prefix_for_model()`~~ — does not exist
- ~~`parrot.embeddings.catalog.PREFIX_LOOKUP`~~ — does not exist; the catalog
  exposes only `EMBEDDING_MODELS`, `USE_CASE_DESCRIPTIONS`,
  `EmbeddingModelEntry`, `get_embedding_models()`, `get_use_cases()`,
  `get_model_recommendations()`
- ~~`EmbeddingModelEntry.resolve_prefixes()`~~ — not a method
- ~~`SentenceTransformerModel.set_prefixes()`~~ — does not exist
- ~~`parrot.embeddings.huggingface.PREFIX_REGISTRY`~~ — no public constant;
  the new cache MUST be private (`_PREFIX_LOOKUP`)
- ~~A `parrot/embeddings/registry.py` module for prefixes~~ — `registry.py`
  exists but is unrelated (it is the model class registry)

---

## Implementation Notes

### Sketch (do not copy verbatim — adapt to your style)

```python
# Near the top of huggingface.py, after imports:
logger = logging.getLogger(__name__)

# Built once at import time, after EMBEDDING_MODELS is fully validated.
_PREFIX_LOOKUP: dict[str, Tuple[Optional[str], Optional[str]]] = {
    entry["model"].lower(): (entry["prefix_query"], entry["prefix_passage"])
    for entry in EMBEDDING_MODELS
}


def _resolve_prefixes(
    model_name: Optional[str],
) -> Tuple[Optional[str], Optional[str]]:
    """Return the (query_prefix, passage_prefix) pair for a model.

    Catalog-driven: looks up ``model_name`` (case-insensitive) in
    ``EMBEDDING_MODELS`` and returns the per-model prefix pair declared
    there. The catalog's Pydantic validator guarantees the pair is
    consistent with ``requires_prefix``, so the result here is correct
    by construction.

    Out-of-catalog models return ``(None, None)`` and emit one INFO log,
    preserving the silent-passthrough behaviour required for backward
    compatibility with operators using third-party models.

    Args:
        model_name: HuggingFace model identifier.

    Returns:
        Tuple ``(query_prefix, passage_prefix)``. Either entry may be
        ``None`` when no prefix is required on that side.
    """
    if not model_name:
        return (None, None)
    pair = _PREFIX_LOOKUP.get(model_name.lower())
    if pair is None:
        logger.info(
            "Model %s not in embedding catalog; encoding without prefix",
            model_name,
        )
        return (None, None)
    return pair
```

### Key Constraints

- **Cache is private**. Name it `_PREFIX_LOOKUP` (underscore prefix). Do
  NOT export it in `__all__` or any public symbol.
- **Lookup must be case-insensitive**. Lowercase both the cache keys
  (build time) and the lookup argument (call time). The existing tests
  use canonical-cased identifiers like `"intfloat/e5-base-v2"`, so they
  will hit the lowercased cache identically.
- **Build the cache at import time, not lazily**. The 39 catalog entries
  are tiny — a one-shot dict comprehension at module import is the
  cheapest possible approach and matches the import-time validation
  pattern already used in `catalog.py:1218`.
- **One INFO log per call**, not per cache miss. The pattern above logs
  on every lookup miss. That is intentional — operators see one line in
  logs the first time the unknown model is constructed, which is rare.
- **Do not raise** on unknown models. Spec §8 explicitly resolved this:
  return `(None, None)` and stay silent (beyond the one INFO log).
- **Keep the function private**. Do not promote `_resolve_prefixes` to a
  public symbol or rename it.

### References in Codebase

- `packages/ai-parrot/src/parrot/embeddings/catalog.py:1218` — pattern for
  doing one-shot work at module import time (the existing Pydantic
  validation loop).
- `packages/ai-parrot/src/parrot/embeddings/huggingface.py:151-235` —
  callers of `_resolve_prefixes` (`SentenceTransformerModel.__init__` and
  the prefix-application helpers).

---

## Acceptance Criteria

- [ ] `_PREFIX_LOOKUP` constant exists at module scope in
      `parrot/embeddings/huggingface.py`, built from `EMBEDDING_MODELS`.
- [ ] `_resolve_prefixes` body contains no `if "..." in lower:` substring
      branches. All family-specific knowledge is removed from this file.
- [ ] `_resolve_prefixes` signature is unchanged:
      `(Optional[str]) -> Tuple[Optional[str], Optional[str]]`.
- [ ] `SentenceTransformerModel.__init__` still calls
      `_resolve_prefixes(self.model_name)` at the same call site (no
      changes required to that class).
- [ ] Module-level `logger = logging.getLogger(__name__)` is added if not
      already present, and used inside `_resolve_prefixes` for the cache
      miss log.
- [ ] All existing tests pass without modification:
      `pytest packages/ai-parrot/tests/embeddings/test_resolve_prefixes.py packages/ai-parrot/tests/embeddings/test_catalog_consistency.py -v`
- [ ] Catalog-consistency tests pass trivially (resolver IS the catalog now).
- [ ] No lint regressions: `ruff check packages/ai-parrot/src/parrot/embeddings/huggingface.py`
- [ ] No changes outside `packages/ai-parrot/src/parrot/embeddings/huggingface.py`.

---

## Test Specification

This task adds NO new tests — it relies entirely on the existing
24-test suite in `test_resolve_prefixes.py` and `test_catalog_consistency.py`
to validate that the refactor preserves behaviour. Confirm zero regressions:

```bash
source .venv/bin/activate
pytest packages/ai-parrot/tests/embeddings/test_resolve_prefixes.py \
       packages/ai-parrot/tests/embeddings/test_catalog_consistency.py \
       -v --tb=short
# Expected: every test passes; no new failures introduced.
```

If any existing test fails, the catalog data and the resolver disagree
about a model — fix the catalog entry, never the test, never the
resolver implementation.

New tests for catalog-driven behaviour and unknown-model logging are
TASK-974's responsibility.

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context.
2. **Check dependencies**: none — this is the first task of FEAT-142.
3. **Verify the Codebase Contract** before writing any code:
   - Confirm `EMBEDDING_MODELS` still exposes `model`, `prefix_query`,
     `prefix_passage` keys via `read` of `catalog.py` lines 76-96.
   - Confirm `SentenceTransformerModel.__init__` line 169 still calls
     `_resolve_prefixes(self.model_name)`.
4. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`.
5. **Implement** following the sketch above; remove old branches entirely.
6. **Run the existing test suite** to verify zero regressions.
7. **Move this file** to `sdd/tasks/completed/TASK-973-resolve-prefixes-from-catalog.md`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

**Completed by**: Claude Sonnet 4.6 (sdd-worker)
**Date**: 2026-05-04
**Notes**: Added `_PREFIX_LOOKUP` dict built at import time from `EMBEDDING_MODELS`,
module-level `logger`, and rewrote `_resolve_prefixes` body as a catalog-driven O(1)
lookup. All 40 existing tests pass with zero regressions. The pre-existing
`TYPE_CHECKING` unused-import lint warning was present before this change and is
not a regression introduced by this task.

**Deviations from spec**: none
