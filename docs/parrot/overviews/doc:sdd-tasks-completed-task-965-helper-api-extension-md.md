---
type: Wiki Overview
title: 'TASK-965: Extend get_embedding_models() with 4 new filter kwargs'
id: doc:sdd-tasks-completed-task-965-helper-api-extension-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Once the catalog carries `metric_recommended`, `requires_prefix`, `dimension`,
relates_to:
- concept: mod:parrot.embeddings
  rel: mentions
- concept: mod:parrot.embeddings.catalog
  rel: mentions
---

# TASK-965: Extend get_embedding_models() with 4 new filter kwargs

**Feature**: FEAT-140 — Embeddings Catalog Update
**Spec**: `sdd/specs/embeddings-catalog-update.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-962
**Assigned-to**: unassigned

---

## Context

Once the catalog carries `metric_recommended`, `requires_prefix`, `dimension`,
and `hnsw_compatible` (TASK-962), consumers should be able to filter on those
fields directly. Today `get_embedding_models()` accepts only `provider` and
`use_case`.

This task implements **Module 4 — Helper API Extension**: add four new optional
keyword arguments to `get_embedding_models()` while keeping the existing two
working unchanged. All filters compose with AND semantics.

---

## Scope

Extend the signature of `get_embedding_models()` at `catalog.py:504`:

```python
def get_embedding_models(
    provider: Optional[str] = None,
    use_case: Optional[str] = None,
    metric: Optional[str] = None,
    max_dims: Optional[int] = None,
    hnsw_compatible: Optional[bool] = None,
    requires_prefix: Optional[bool] = None,
) -> List[Dict[str, Any]]:
    """Filter the catalog. All filters compose with AND semantics."""
```

Filter semantics:

- `metric`: keep entries where `entry["metric_recommended"] == metric`.
- `max_dims`: keep entries where `entry["dimension"] <= max_dims`.
- `hnsw_compatible`: keep entries where `entry["hnsw_compatible"] == hnsw_compatible`.
- `requires_prefix`: keep entries where `entry["requires_prefix"] == requires_prefix`.

Each filter is one list-comprehension predicate, applied in sequence. Existing
`provider` and `use_case` filters keep their current behaviour.

Update the docstring to describe each new kwarg and the AND-composition contract.

**NOT in scope**:
- Adding the `EmbeddingModelEntry` schema (TASK-962).
- Adding new use-case tags (TASK-964).
- Cross-consistency pytest (TASK-966).
- Re-typing the existing `provider: str = None` to `Optional[str]` is OPTIONAL —
  do it for consistency if it doesn't break anything else, otherwise leave alone.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/embeddings/catalog.py` | MODIFY | Extend `get_embedding_models` signature and body |
| `packages/ai-parrot/tests/embeddings/test_get_embedding_models_filters.py` | CREATE | Unit tests for new filters and AND-composition |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.embeddings import get_embedding_models  # re-export
from parrot.embeddings.catalog import get_embedding_models  # source
from parrot.embeddings.catalog import EMBEDDING_MODELS
```

### Existing Signature (verified at catalog.py:504-525)

```python
def get_embedding_models(
    provider: str = None,
    use_case: str = None,
) -> List[Dict[str, Any]]:
    """Return the curated list of embedding models, optionally filtered.

    Args:
        provider: Filter by provider name (huggingface, openai, google).
                  If None, no provider filtering is applied.
        use_case: Filter by use case (similarity, retrieval, clustering,
                  multilingual, code). If None, no use-case filtering is
                  applied.

    Returns:
        List of embedding model descriptors.
    """
    models = EMBEDDING_MODELS
    if provider:
        models = [m for m in models if m["provider"] == provider]
    if use_case:
        models = [m for m in models if use_case in m.get("use_case", [])]
    return list(models)
```

### Does NOT Exist

- ~~Existing kwargs `metric`, `max_dims`, `hnsw_compatible`, `requires_prefix`~~ —
  current signature only accepts `provider` and `use_case` (verified above).
- ~~A registry of valid metrics that the function checks against~~ — we
  trust the caller; the catalog's Pydantic validator already enforces the
  Literal at entry-creation time.
- ~~Async version of `get_embedding_models`~~ — function is synchronous and
  stays synchronous (no I/O).

---

## Implementation Notes

### Pattern to Follow

Append predicate-style filters in the same style as the existing two. Use
`is not None` for boolean kwargs to distinguish "filter unset" from "filter to False":

```python
def get_embedding_models(
    provider: Optional[str] = None,
    use_case: Optional[str] = None,
    metric: Optional[str] = None,
    max_dims: Optional[int] = None,
    hnsw_compatible: Optional[bool] = None,
    requires_prefix: Optional[bool] = None,
) -> List[Dict[str, Any]]:
    models = EMBEDDING_MODELS
    if provider:
        models = [m for m in models if m["provider"] == provider]
    if use_case:
        models = [m for m in models if use_case in m.get("use_case", [])]
    if metric:
        models = [m for m in models if m["metric_recommended"] == metric]
    if max_dims is not None:
        models = [m for m in models if m["dimension"] <= max_dims]
    if hnsw_compatible is not None:
        models = [m for m in models if m["hnsw_compatible"] is hnsw_compatible]
    if requires_prefix is not None:
        models = [m for m in models if m["requires_prefix"] is requires_prefix]
    return list(models)
```

### Key Constraints

- Pure function; do not introduce caching, async, or side-effects.
- Backward compatibility: positional and keyword call patterns that pass only
  `provider` / `use_case` must keep returning identical results.
- Filters compose with AND; do NOT short-circuit on empty results
  (an empty list at any stage just feeds an empty list forward — this is
  correct AND-composition).

### References in Codebase

- `packages/ai-parrot/src/parrot/embeddings/catalog.py:504-525` — current helper
- Search call sites with `grep -rn "get_embedding_models(" --include="*.py"`
  to ensure none break.

---

## Acceptance Criteria

- [ ] Signature accepts the 4 new optional kwargs in addition to the 2 existing.
- [ ] `get_embedding_models(metric="cosine")` returns only entries with
      `metric_recommended == "cosine"`.
- [ ] `get_embedding_models(max_dims=1024)` excludes models with
      `dimension > 1024`.
- [ ] `get_embedding_models(hnsw_compatible=True)` excludes
      `e5-mistral-7b-instruct` and `nvidia/NV-Embed-v2`.
- [ ] `get_embedding_models(requires_prefix=False)` excludes E5 family,
      BGE-EN-v1.5 family, Jina v3, all instruct models.
- [ ] `get_embedding_models(metric="cosine", hnsw_compatible=True, requires_prefix=False)`
      returns a non-empty list, every member satisfies all three predicates.
- [ ] `get_embedding_models(provider="huggingface")` keeps returning the
      same set as before (modulo new entries added in TASK-963).
- [ ] `get_embedding_models(use_case="retrieval")` keeps returning all
      entries that had `"retrieval"` before this change.
- [ ] Docstring describes the four new kwargs and the AND-composition contract.
- [ ] All tests pass: `pytest packages/ai-parrot/tests/embeddings/ -v`.

---

## Test Specification

```python
# packages/ai-parrot/tests/embeddings/test_get_embedding_models_filters.py
import pytest
from parrot.embeddings import get_embedding_models, EMBEDDING_MODELS


class TestNewFilters:
    def test_filter_by_metric_cosine(self):
        result = get_embedding_models(metric="cosine")
        assert all(m["metric_recommended"] == "cosine" for m in result)
        assert len(result) > 0

    def test_filter_by_metric_dot(self):
        result = get_embedding_models(metric="dot")
        assert all(m["metric_recommended"] == "dot" for m in result)
        # multi-qa-mpnet-base-dot-v1 must be in this set
        assert any(
            m["model"] == "sentence-transformers/multi-qa-mpnet-base-dot-v1"
            for m in result
        )

    def test_filter_by_max_dims_excludes_high_dim(self):
        result = get_embedding_models(max_dims=1024)
        assert all(m["dimension"] <= 1024 for m in result)
        # e5-mistral (4096d) MUST be excluded
        assert not any(
            m["model"] == "intfloat/e5-mistral-7b-instruct" for m in result
        )

    def test_filter_hnsw_compatible_true(self):
        result = get_embedding_models(hnsw_compatible=True)
        assert all(m["hnsw_compatible"] is True for m in result)
        # NV-Embed-v2 (4096d) MUST be excluded
        assert not any(m["model"] == "nvidia/NV-Embed-v2" for m in result)

    def test_filter_hnsw_compatible_false(self):
        result = get_embedding_models(hnsw_compatible=False)
        assert all(m["hnsw_compatible"] is False for m in result)
        assert any(m["model"] == "nvidia/NV-Embed-v2" for m in result)

    def test_filter_requires_prefix_false(self):
        result = get_embedding_models(requires_prefix=False)
        assert all(m["requires_prefix"] is False for m in result)
        # E5 / BGE-EN-v1.5 / Jina v3 / instruct models all excluded
        assert not any(
            "e5-base" in m["model"] or "bge-base-en-v1.5" in m["model"]
            or "jina-embeddings-v3" in m["model"] or "instruct" in m["model"]
            for m in result
        )


class TestAndComposition:
    def test_three_filter_combo_returns_nonempty(self):
        result = get_embedding_models(
            metric="cosine", hnsw_compatible=True, requires_prefix=False,
        )
        assert len(result) > 0
        for m in result:
            assert m["metric_recommended"] == "cosine"
            assert m["hnsw_compatible"] is True
            assert m["requires_prefix"] is False


class TestExistingFiltersUnchanged:
    def test_provider_filter_unchanged(self):
        result = get_embedding_models(provider="huggingface")
        assert all(m["provider"] == "huggingface" for m in result)
        assert len(result) > 0

    def test_use_case_retrieval_unchanged(self):
        result = get_embedding_models(use_case="retrieval")
        assert all("retrieval" in m["use_case"] for m in result)

    def test_no_filters_returns_full_catalog(self):
        result = get_embedding_models()
        assert len(result) == len(EMBEDDING_MODELS)
```

---

## Agent Instructions

1. Verify TASK-962 is in `sdd/tasks/completed/` (the new fields must exist).
2. Update status in `sdd/tasks/.index.json` → `"in-progress"`.
3. Extend the signature and body of `get_embedding_models()` exactly per spec.
4. Update the docstring.
5. Run `pytest packages/ai-parrot/tests/embeddings/ -v`.
6. Search call sites: `grep -rn "get_embedding_models(" --include="*.py"` —
   confirm no caller breaks.
7. Move this file to `sdd/tasks/completed/` and update the index.

---

## Completion Note

**Completed by**: Claude Sonnet 4.6 (sdd-worker)
**Date**: 2026-05-04
**Notes**: get_embedding_models() extended with 4 new optional kwargs
(metric, max_dims, hnsw_compatible, requires_prefix). All compose with
AND semantics. Existing provider/use_case filters unchanged. Docstring
updated. All existing call sites remain compatible (verified: only
the handler API and test files use this function).

**Deviations from spec**: None.
