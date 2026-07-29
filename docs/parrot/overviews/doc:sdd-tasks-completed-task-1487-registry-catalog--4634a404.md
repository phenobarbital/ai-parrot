---
type: Wiki Overview
title: 'TASK-1487: Registry & Catalog Integration'
id: doc:sdd-tasks-completed-task-1487-registry-catalog-integration-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: This task wires `UFormEmbedding` into the existing embedding infrastructure
  so
relates_to:
- concept: mod:parrot.embeddings
  rel: mentions
- concept: mod:parrot.embeddings.catalog
  rel: mentions
- concept: mod:parrot.embeddings.multimodal
  rel: mentions
- concept: mod:parrot.embeddings.registry
  rel: mentions
---

# TASK-1487: Registry & Catalog Integration

**Feature**: FEAT-229 — Multimodal Embedding Provider
**Spec**: `sdd/specs/multimodal-embedding-provider.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1486
**Assigned-to**: unassigned

---

## Context

This task wires `UFormEmbedding` into the existing embedding infrastructure so
it can be discovered and instantiated through the standard `EmbeddingRegistry`
and `supported_embeddings` lookup. It also adds UForm model entries to the
`EMBEDDING_MODELS` catalog for operator discoverability.

Implements spec §3 (Module 4).

---

## Scope

- Modify `packages/ai-parrot/src/parrot/embeddings/__init__.py`:
  - Add `'multimodal': 'UFormEmbedding'` to `supported_embeddings` dict.
- Modify `packages/ai-parrot/src/parrot/embeddings/catalog.py`:
  - Extend `Provider` Literal to include `"multimodal"`.
  - Add UForm model entries to `EMBEDDING_MODELS`:
    - `unum-cloud/uform3-image-text-multilingual-base` (206M, 768 dims, multilingual)
    - `unum-cloud/uform3-image-text-english-large` (365M, 768 dims, English)
  - Ensure new entries pass `EmbeddingModelEntry` validation.
- Write a test verifying the registry round-trip: `EmbeddingRegistry.get_or_create(name, 'multimodal')` returns a `UFormEmbedding` instance.

**NOT in scope**: PgVector schema (TASK-1488), benchmark (TASK-1489).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/embeddings/__init__.py` | MODIFY | Add `'multimodal'` to `supported_embeddings` |
| `packages/ai-parrot/src/parrot/embeddings/catalog.py` | MODIFY | Extend `Provider`, add UForm catalog entries |
| `tests/embeddings/test_registry_multimodal.py` | CREATE | Registry integration test |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.embeddings import supported_embeddings  # verified: packages/ai-parrot/src/parrot/embeddings/__init__.py:17
from parrot.embeddings.registry import EmbeddingRegistry  # verified: packages/ai-parrot/src/parrot/embeddings/registry.py:51
from parrot.embeddings.catalog import EMBEDDING_MODELS, EmbeddingModelEntry  # verified: packages/ai-parrot/src/parrot/embeddings/catalog.py:36,171
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/embeddings/__init__.py
supported_embeddings = {                              # line 17
    'huggingface': 'SentenceTransformerModel',
    'google': 'GoogleEmbeddingModel',
    'openai': 'OpenAIEmbeddingModel',
}

# packages/ai-parrot/src/parrot/embeddings/catalog.py
Provider = Literal["huggingface", "openai", "google"]  # line 21 — MUST ADD "multimodal"
Metric = Literal["cosine", "dot", "l2"]                # line 20
UseCaseTag = Literal[                                  # line 22-33
    "similarity", "retrieval", "clustering", "multilingual",
    "code", "qa", "long-context", "instruct", "asymmetric", "symmetric",
]

class EmbeddingModelEntry(BaseModel):                  # line 36
    model: str
    provider: Provider
    name: str
    dimension: int = Field(gt=0)
    multilingual: bool
    language: str
    use_case: list[UseCaseTag]
    description: str
    metric_recommended: Metric
    requires_prefix: bool
    prefix_query: Optional[str] = None
    prefix_passage: Optional[str] = None
    normalized_output: bool
    max_seq_length: int = Field(gt=0)
    hnsw_compatible: bool
    license: str
    recommended_score_threshold: float = Field(ge=0.0, le=100.0)
    recommended_search_limit: int = Field(ge=1, le=100)
    matryoshka_dimensions: Optional[list[int]] = None

# packages/ai-parrot/src/parrot/embeddings/registry.py
class EmbeddingRegistry:                               # line 51
    def _build_model(self, model_name, model_type, **kwargs) -> Any:  # line 149
        # Resolves: supported_embeddings[model_type] -> class name
        # Imports: parrot.embeddings.{model_type}
        # Instantiates: class(model_name=model_name, **kwargs)
        module_path = f"parrot.embeddings.{model_type}"  # line 170
        ...
    async def get_or_create(self, model_name, model_type="huggingface", **kwargs) -> Any:  # line 218
```

### Does NOT Exist
- ~~`Provider` includes `"multimodal"`~~ — NOT YET; this task adds it
- ~~UForm entries in `EMBEDDING_MODELS`~~ — NOT YET; this task adds them
- ~~`supported_embeddings['multimodal']`~~ — NOT YET; this task adds it

---

## Implementation Notes

### Key Constraints
- **Registry resolution path**: `_build_model()` (line 149-178) imports
  `parrot.embeddings.{model_type}` and gets the class by name. For
  `model_type='multimodal'`, it imports `parrot.embeddings.multimodal` and
  gets `UFormEmbedding`. Ensure `multimodal/__init__.py` exports `UFormEmbedding`.
- **Catalog entries**: verify UForm model specs (dimension, max_seq_length, etc.)
  against the UForm documentation. The brainstorm says 768 dims for multilingual-base.
  Confirm `matryoshka_dimensions` list from UForm docs (likely `[768, 512, 256, 128, 64]`).
- **Provider Literal**: extending it is a one-line change but affects validation
  of ALL existing entries at import time. Run `python -c "from parrot.embeddings.catalog import EMBEDDING_MODELS"` to verify no regression.
- UForm entries should have:
  - `requires_prefix: False` (CLIP-style models don't use prefixes)
  - `normalized_output: True` (we L2-normalize in `_postprocess`)
  - `metric_recommended: "cosine"`
  - `hnsw_compatible: True` (768 <= 2000)

### References in Codebase
- `packages/ai-parrot/src/parrot/embeddings/__init__.py` — `supported_embeddings` dict
- `packages/ai-parrot/src/parrot/embeddings/catalog.py:21` — `Provider` Literal
- `packages/ai-parrot/src/parrot/embeddings/registry.py:149-178` — `_build_model()` resolution

---

## Acceptance Criteria

- [ ] `supported_embeddings['multimodal']` == `'UFormEmbedding'`
- [ ] `Provider` Literal includes `"multimodal"`
- [ ] Two UForm entries in `EMBEDDING_MODELS` (multilingual-base, english-large)
- [ ] All existing catalog entries still pass `EmbeddingModelEntry` validation (no regression)
- [ ] `EmbeddingRegistry.instance().get_or_create(name, 'multimodal')` returns `UFormEmbedding`
- [ ] All tests pass: `pytest tests/embeddings/test_registry_multimodal.py -v`
- [ ] Catalog import works: `python -c "from parrot.embeddings.catalog import EMBEDDING_MODELS"`
- [ ] No linting errors

---

## Test Specification

```python
# tests/embeddings/test_registry_multimodal.py
import pytest
from parrot.embeddings import supported_embeddings
from parrot.embeddings.catalog import EMBEDDING_MODELS


class TestRegistryEntry:
    def test_multimodal_in_supported(self):
        assert 'multimodal' in supported_embeddings
        assert supported_embeddings['multimodal'] == 'UFormEmbedding'

    def test_catalog_has_uform_entries(self):
        uform_entries = [e for e in EMBEDDING_MODELS if e.get('provider') == 'multimodal']
        assert len(uform_entries) >= 2
        models = {e['model'] for e in uform_entries}
        assert 'unum-cloud/uform3-image-text-multilingual-base' in models


class TestRegistryResolution:
    @pytest.mark.asyncio
    async def test_get_or_create_multimodal(self):
        uform = pytest.importorskip("uform")
        from parrot.embeddings.registry import EmbeddingRegistry
        registry = EmbeddingRegistry.instance()
        model = await registry.get_or_create(
            "unum-cloud/uform3-image-text-multilingual-base",
            "multimodal"
        )
        from parrot.embeddings.multimodal import UFormEmbedding
        assert isinstance(model, UFormEmbedding)
        await registry.unload(
            "unum-cloud/uform3-image-text-multilingual-base", "multimodal"
        )
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify TASK-1486 is in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — confirm `supported_embeddings`, `Provider`, and `EMBEDDING_MODELS` are still at the listed locations
4. **Update status** in `sdd/tasks/index/multimodal-embedding-provider.json` → `"in-progress"` with your session ID
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met — especially the catalog import regression check
7. **Move this file** to `sdd/tasks/completed/TASK-1487-registry-catalog-integration.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: claude-sonnet-4-6 (sdd-worker)
**Date**: 2026-06-08
**Notes**: Added 'multimodal': 'UFormEmbedding' to supported_embeddings. Extended Provider
Literal to include 'multimodal'. Added 2 UForm model entries to EMBEDDING_MODELS (multilingual-base
206M and english-large 365M). All 10 registry tests pass including catalog regression check.
Registry.get_or_create() and _build_model() successfully resolve 'multimodal' to UFormEmbedding.

**Deviations from spec**: none | describe if any
