---
type: Wiki Overview
title: 'Feature Specification: Embeddings Catalog Update'
id: doc:sdd-specs-embeddings-catalog-update-spec-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: The curated embedding catalog at `parrot/embeddings/catalog.py` is consumed
  by an
relates_to:
- concept: mod:parrot.embeddings
  rel: mentions
- concept: mod:parrot.embeddings.base
  rel: mentions
- concept: mod:parrot.embeddings.catalog
  rel: mentions
- concept: mod:parrot.embeddings.huggingface
  rel: mentions
---

# Feature Specification: Embeddings Catalog Update

**Feature ID**: FEAT-140
**Date**: 2026-05-04
**Author**: Jesus Lara
**Status**: approved
**Target version**: next minor

---

## 1. Motivation & Business Requirements

### Problem Statement

The curated embedding catalog at `parrot/embeddings/catalog.py` is consumed by an
external API that lists every embedding model available to operators when
configuring vector stores or RAG pipelines. Today the catalog has three blind
spots that surface as silent retrieval-quality regressions in production:

1. **No metric metadata**. `multi-qa-mpnet-base-cos-v1` requires cosine
   similarity, while its sibling `multi-qa-mpnet-base-dot-v1` requires dot
   product. The catalog exposes neither, so an operator can pair a model with
   the wrong metric — ranking degrades silently, no error is raised.
2. **No prefix metadata**. Several model families (E5, BGE-EN-v1.5, Jina v3,
   instruct-tuned models, NV-Embed) require asymmetric `query: ` / `passage: `
   instructions or task-specific prompts. The loader handles some of these
   internally via `_resolve_prefixes()`, but the catalog never tells the
   consumer which models are prefix-sensitive — making the surface untrustworthy.
3. **No HNSW compatibility flag**. pgvector's HNSW index caps at 2000
   dimensions. Models like `text-embedding-3-large` (3072d) or
   `e5-mistral-7b-instruct` (4096d) cannot be indexed with HNSW, but the
   catalog never warns the operator.

Additionally, several state-of-the-art free models that are now standard in
the open-source RAG community are missing — most notably
`multi-qa-mpnet-base-cos-v1`, which `examples/chatbots/att/bot.py` already
uses in production despite not being listed.

### Goals

- Extend each `EMBEDDING_MODELS` entry with eight new metadata fields
  (`metric_recommended`, `requires_prefix`, `prefix_query`, `prefix_passage`,
  `normalized_output`, `max_seq_length`, `hnsw_compatible`, `license`).
- Add five free / open models to the catalog, including `multi-qa-mpnet-base-cos-v1`.
- Wire every prefix-requiring new model through `_resolve_prefixes()` in
  `parrot/embeddings/huggingface.py` so the loader supports what the API
  exposes.
- Extend the use-case taxonomy with five new tags (`qa`, `long-context`,
  `instruct`, `asymmetric`, `symmetric`) and reassign existing entries.
- Extend the `get_embedding_models()` helper with four new filter kwargs
  (`metric`, `max_dims`, `hnsw_compatible`, `requires_prefix`).
- Enforce catalog ↔ resolver consistency via a CI pytest that breaks if a
  prefix-requiring model is added on either side without the matching
  counterpart.

### Non-Goals (explicitly out of scope)

- Adding **paid** providers (Cohere, Voyage). Existing OpenAI and Google
  entries remain untouched.
- Adding `cost_per_million_tokens` or any pricing metadata — it goes stale
  fast and is operator-visible information that belongs elsewhere.
- Modifying the actual encoding / embedding pipeline of `EmbeddingModel`
  subclasses beyond extending `_resolve_prefixes()`.
- Modifying or rebuilding the catalog consumer API endpoints — they pick up
  the new fields automatically once the schema is extended.
- Replacing the in-code list with a database-backed registry. The single
  `EMBEDDING_MODELS` list in `catalog.py` remains the source of truth.

---

## 2. Architectural Design

### Overview

A single Python module (`parrot/embeddings/catalog.py`) holds the catalog as a
list of dicts. The change is purely additive: extend each dict with new
metadata fields, add new entries, and add new keyword filters to the existing
helper. No behaviour changes, no API breaks.

The only side change is in `parrot/embeddings/huggingface.py::_resolve_prefixes`,
which gains branches for the new prefix-requiring models. The
catalog and the resolver are kept in sync through a cross-consistency pytest
that runs in CI: every catalog entry where `requires_prefix=True` must yield a
matching `(prefix_query, prefix_passage)` tuple from the resolver, and vice
versa.

The use-case taxonomy moves from five tags to ten, expanding categorisation
without removing any existing tag — frontends already consuming the original
five keep working.

### Component Diagram

```
┌─────────────────────────────────────────────────────────┐
│                  parrot/embeddings/                     │
│                                                         │
│  ┌────────────────┐       ┌──────────────────────┐      │
│  │  catalog.py    │       │  huggingface.py      │      │
│  │                │       │                      │      │
│  │ EMBEDDING_     │       │ _resolve_prefixes(   │      │
│  │   MODELS  ─────┼──────▶│   model_name) →      │      │
│  │                │       │   (q_pre, p_pre)     │      │
│  │ get_embedding_ │       │                      │      │
│  │   models(...)  │       │ SentenceTransformer  │      │
│  │                │       │   Model              │      │
│  └────────┬───────┘       └──────────┬───────────┘      │
│           │                          │                  │
└───────────┼──────────────────────────┼──────────────────┘
            │                          │
            ▼                          ▼
   ┌──────────────────┐      ┌────────────────────┐
   │ Catalog API      │      │ Embedding loader   │
   │ (operator UI)    │      │ runtime            │
   └──────────────────┘      └────────────────────┘

         ▲                          ▲
         │                          │
         └─── CI pytest ────────────┘
              (catalog ↔ resolver consistency)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `parrot.embeddings.catalog.EMBEDDING_MODELS` | extends each entry | additive metadata fields, no removals |
| `parrot.embeddings.catalog.USE_CASE_DESCRIPTIONS` | extends dict | adds 5 new keys |
| `parrot.embeddings.catalog.get_embedding_models()` | extends signature | adds 4 new optional kwargs, preserves existing ones |
| `parrot.embeddings.huggingface._resolve_prefixes()` | extends function body | adds branches for Jina v3, gte-Qwen2-instruct, e5-mistral-instruct, NV-Embed-v2 |
| Catalog consumer API (out of repo / handler layer) | passive consumer | sees richer dicts; no changes required on its side |

### Data Models

The catalog stays as `List[Dict[str, Any]]` for backward compatibility with
existing JSON serialisation in the consumer API. A Pydantic model is
introduced **only for validation** (loaded once at module import); the runtime
exposed object is still the dict list. This keeps the JSON contract stable
while preventing malformed entries from entering the catalog.

```python
# parrot/embeddings/catalog.py — new
from typing import Literal, Optional
from pydantic import BaseModel, Field, model_validator


Metric = Literal["cosine", "dot", "l2"]
Provider = Literal["huggingface", "openai", "google"]


class EmbeddingModelEntry(BaseModel):
    """Validation schema for a single catalog entry.

    Used at module import time to guarantee every entry in
    EMBEDDING_MODELS is well-formed. The runtime exposed object remains
    a plain dict for JSON-serialisation compatibility with the consumer API.
    """
    model: str
    provider: Provider
    name: str
    dimension: int = Field(gt=0)
    multilingual: bool
    language: str
    use_case: list[str]
    description: str
    # New required fields
    metric_recommended: Metric
    requires_prefix: bool
    prefix_query: Optional[str] = None
    prefix_passage: Optional[str] = None
    normalized_output: bool
    max_seq_length: int = Field(gt=0)
    hnsw_compatible: bool
    license: str
    # Existing optional field
    matryoshka_dimensions: Optional[list[int]] = None

    @model_validator(mode="after")
    def _prefix_consistency(self) -> "EmbeddingModelEntry":
        """If requires_prefix=True, at least one of prefix_query /
        prefix_passage must be non-empty. If False, both must be None."""
        if self.requires_prefix:
            if not (self.prefix_query or self.prefix_passage):
                raise ValueError(
                    f"{self.model}: requires_prefix=True but both prefixes are None"
                )
        else:
            if self.prefix_query or self.prefix_passage:
                raise ValueError(
                    f"{self.model}: requires_prefix=False but a prefix is set"
                )
        return self

    @model_validator(mode="after")
    def _hnsw_dimension_consistency(self) -> "EmbeddingModelEntry":
        """hnsw_compatible must reflect the pgvector 2000-dim HNSW limit."""
        expected = self.dimension <= 2000
        if self.hnsw_compatible != expected:
            raise ValueError(
                f"{self.model}: hnsw_compatible={self.hnsw_compatible} but "
                f"dimension={self.dimension} (pgvector HNSW cap is 2000)"
            )
        return self
```

### New Public Interfaces

```python
# parrot/embeddings/catalog.py — extended helper signature
def get_embedding_models(
    provider: Optional[str] = None,
    use_case: Optional[str] = None,
    metric: Optional[str] = None,
    max_dims: Optional[int] = None,
    hnsw_compatible: Optional[bool] = None,
    requires_prefix: Optional[bool] = None,
) -> list[dict]:
    """Filter the catalog. All filters compose with AND semantics."""
```

No new classes are exported. `EmbeddingModelEntry` stays internal to the
module; consumers continue to receive plain dicts via `get_embedding_models()`.

---

## 3. Module Breakdown

### Module 1: Catalog Schema Extension
- **Path**: `packages/ai-parrot/src/parrot/embeddings/catalog.py`
- **Responsibility**: Add the 8 new metadata fields to every existing
  `EMBEDDING_MODELS` entry. Introduce the internal `EmbeddingModelEntry`
  Pydantic model and call it at module import time to validate the catalog.
- **Depends on**: nothing (purely additive)

### Module 2: New Catalog Entries + Resolver Wiring
- **Path**: `packages/ai-parrot/src/parrot/embeddings/catalog.py` (entries)
  + `packages/ai-parrot/src/parrot/embeddings/huggingface.py` (resolver branches)
- **Responsibility**: Add the five new model entries with full metadata.
  For each entry where `requires_prefix=True`, add the corresponding branch
  to `_resolve_prefixes()`. Also add the new models to the `ModelType` enum
  (lines 60-97 of `huggingface.py`) where applicable, for consistency.
- **Depends on**: Module 1 (the schema must accept the new fields first)

### Module 3: Use-Case Taxonomy Extension
- **Path**: `packages/ai-parrot/src/parrot/embeddings/catalog.py`
- **Responsibility**: Add five entries to `USE_CASE_DESCRIPTIONS`
  (`qa`, `long-context`, `instruct`, `asymmetric`, `symmetric`).
  Walk every existing entry's `use_case` list and add the new tags where
  applicable (e.g. all `multi-qa-*` get `qa`; all `e5-*`, `multi-qa-*`,
  `bge-*-en-v1.5` get `asymmetric`; all `paraphrase-*` get `symmetric`;
  every model with `max_seq_length >= 4096` gets `long-context`).
- **Depends on**: Module 1

### Module 4: Helper API Extension
- **Path**: `packages/ai-parrot/src/parrot/embeddings/catalog.py`
- **Responsibility**: Add four new keyword arguments to
  `get_embedding_models()`: `metric`, `max_dims`, `hnsw_compatible`,
  `requires_prefix`. Existing `provider` and `use_case` keep working
  unchanged. Filters compose with AND semantics. Each filter is a single
  list-comprehension predicate.
- **Depends on**: Module 1

### Module 5: Cross-Consistency Pytest
- **Path**: `packages/ai-parrot/tests/embeddings/test_catalog_consistency.py` (new)
- **Responsibility**: Two assertions:
  1. For every catalog entry with `provider == "huggingface"`,
     `_resolve_prefixes(entry["model"]) == (entry["prefix_query"], entry["prefix_passage"])`.
  2. For every model_name returned by walking `_resolve_prefixes()` with the
     known prefix-requiring slugs (E5, BGE-EN-v1.5, Jina v3, gte-Qwen2-instruct,
     e5-mistral-instruct, NV-Embed-v2), assert there is a catalog entry with
     `requires_prefix=True` and matching prefixes.
- **Depends on**: Modules 1-4

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_catalog_validates_at_import` | M1 | Importing `parrot.embeddings.catalog` runs Pydantic validation on every entry without raising |
| `test_catalog_entry_invalid_prefix_combo_rejected` | M1 | Constructing an `EmbeddingModelEntry` with `requires_prefix=False` and a non-None prefix raises `ValidationError` |
| `test_catalog_entry_invalid_hnsw_flag_rejected` | M1 | Entry with `dimension=4096` and `hnsw_compatible=True` raises `ValidationError` |
| `test_new_models_present` | M2 | All 5 new models appear in `EMBEDDING_MODELS`: `multi-qa-mpnet-base-cos-v1`, `jina-embeddings-v3`, `gte-Qwen2-1.5B-instruct`, `e5-mistral-7b-instruct`, `NV-Embed-v2` |
| `test_resolve_prefixes_jina_v3` | M2 | `_resolve_prefixes("jinaai/jina-embeddings-v3")` returns the documented Jina v3 retrieval prefix pair |
| `test_resolve_prefixes_gte_qwen2_instruct` | M2 | `_resolve_prefixes("Alibaba-NLP/gte-Qwen2-1.5B-instruct")` returns the instruct-style prefix |
| `test_resolve_prefixes_e5_mistral_instruct` | M2 | `_resolve_prefixes("intfloat/e5-mistral-7b-instruct")` returns the instruct-style prefix |
| `test_resolve_prefixes_nvembed_v2` | M2 | `_resolve_prefixes("nvidia/NV-Embed-v2")` returns the documented task-instruction prefix |
| `test_resolve_prefixes_unchanged_for_existing` | M2 | E5 family still returns `("query: ", "passage: ")`; BGE-EN-v1.5 unchanged; MPNet/MiniLM/GTE/BGE-M3 still return `(None, None)` |
| `test_use_case_descriptions_extended` | M3 | `USE_CASE_DESCRIPTIONS` now contains keys `qa`, `long-context`, `instruct`, `asymmetric`, `symmetric` and keeps the original five |
| `test_existing_use_cases_preserved` | M3 | Every model retains every use_case it had in the prior version (no regressions in tags) |
| `test_filter_by_metric` | M4 | `get_embedding_models(metric="cosine")` returns only entries where `metric_recommended == "cosine"` |
| `test_filter_by_max_dims` | M4 | `get_embedding_models(max_dims=1024)` excludes the 4096d models |
| `test_filter_by_hnsw_compatible` | M4 | `get_embedding_models(hnsw_compatible=True)` excludes models with `dimension > 2000` |
| `test_filter_by_requires_prefix_false` | M4 | `get_embedding_models(requires_prefix=False)` excludes E5, BGE-EN-v1.5, Jina v3, instruct models |
| `test_filters_compose_with_and` | M4 | `get_embedding_models(metric="cosine", hnsw_compatible=True, requires_prefix=False)` returns a non-empty list, and every entry satisfies all three predicates |
| `test_existing_filters_unchanged` | M4 | `get_embedding_models(provider="huggingface")` and `get_embedding_models(use_case="retrieval")` keep returning what they returned before |

### Integration Tests

| Test | Description |
|---|---|
| `test_catalog_resolver_consistency` (M5) | For every HF entry, `_resolve_prefixes(model)` matches the catalog's `(prefix_query, prefix_passage)`. Reverse direction: for every model the resolver knows, the catalog declares `requires_prefix=True` |
| `test_existing_huggingface_embedding_tests_pass` | Run `pytest packages/ai-parrot/tests/embeddings/ -v` — no regressions in `test_base_registry.py` or `test_registry.py` |

### Test Data / Fixtures

```python
# tests/embeddings/test_catalog_consistency.py — fixture
@pytest.fixture
def hf_catalog_entries() -> list[dict]:
    """Filter EMBEDDING_MODELS to provider=='huggingface' for prefix checks."""
    from parrot.embeddings.catalog import EMBEDDING_MODELS
    return [e for e in EMBEDDING_MODELS if e["provider"] == "huggingface"]


@pytest.fixture
def known_prefix_models() -> list[str]:
    """Models that the resolver MUST handle, as agreed in the spec."""
    return [
        "intfloat/e5-base-v2",
        "intfloat/e5-large-v2",
        "intfloat/multilingual-e5-base",
        "intfloat/multilingual-e5-large",
        "BAAI/bge-small-en-v1.5",
        "BAAI/bge-base-en-v1.5",
        "BAAI/bge-large-en-v1.5",
        "jinaai/jina-embeddings-v3",
        "Alibaba-NLP/gte-Qwen2-1.5B-instruct",
        "intfloat/e5-mistral-7b-instruct",
        "nvidia/NV-Embed-v2",
    ]
```

---

## 5. Acceptance Criteria

- [ ] All existing 30+ catalog entries pass the new `EmbeddingModelEntry`
      Pydantic validation at module import time.
- [ ] All five new models are present in `EMBEDDING_MODELS` with complete
      metadata: `multi-qa-mpnet-base-cos-v1`, `jinaai/jina-embeddings-v3`,
      `Alibaba-NLP/gte-Qwen2-1.5B-instruct`, `intfloat/e5-mistral-7b-instruct`,
      `nvidia/NV-Embed-v2`.
- [ ] Every new model with `requires_prefix=True` is wired into
      `_resolve_prefixes()` with the correct prefix pair.
- [ ] `nvidia/NV-Embed-v2` entry has `license="cc-by-nc-4.0"` — flagged as
      non-commercial.
- [ ] `e5-mistral-7b-instruct` and `NV-Embed-v2` entries have
      `hnsw_compatible=False`.
- [ ] `multi-qa-mpnet-base-cos-v1` entry has `metric_recommended="cosine"`,
      `normalized_output=True`, `requires_prefix=False`, and use_cases
      including `qa` and `asymmetric`.
- [ ] `get_embedding_models(metric="cosine", hnsw_compatible=True, requires_prefix=False)`
      returns a non-empty list.
- [ ] `get_embedding_models(provider="huggingface")` and
      `get_embedding_models(use_case="retrieval")` return the same set as
      before this change (modulo the 5 new entries that match those filters).
- [ ] The cross-consistency pytest passes:
      `pytest packages/ai-parrot/tests/embeddings/test_catalog_consistency.py -v`.
- [ ] Existing tests pass:
      `pytest packages/ai-parrot/tests/embeddings/ -v`.
- [ ] No breaking changes to the public API exported from
      `parrot.embeddings/__init__.py`.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**

### Verified Imports

```python
# All verified in packages/ai-parrot/src/parrot/embeddings/__init__.py:1-7
from parrot.embeddings import EMBEDDING_MODELS
from parrot.embeddings import USE_CASE_DESCRIPTIONS
from parrot.embeddings import get_embedding_models
from parrot.embeddings import get_use_cases
from parrot.embeddings import EmbeddingRegistry

# Internal (package-private) — used by Module 5 tests:
from parrot.embeddings.huggingface import _resolve_prefixes  # verified line 11
from parrot.embeddings.huggingface import SentenceTransformerModel  # verified line 100
from parrot.embeddings.huggingface import ModelType  # verified line 60
from parrot.embeddings.base import EmbeddingModel  # verified line 15
```

### Existing Class & Function Signatures

```python
# packages/ai-parrot/src/parrot/embeddings/catalog.py
EMBEDDING_MODELS: List[Dict[str, Any]]  # line 12 — list of model descriptors
USE_CASE_DESCRIPTIONS: Dict[str, str]   # line 480 — currently 5 keys

def get_embedding_models(                # line 504
    provider: str = None,
    use_case: str = None,
) -> List[Dict[str, Any]]:
    ...

def get_use_cases() -> Dict[str, str]:   # line 528
    ...

# packages/ai-parrot/src/parrot/embeddings/huggingface.py
def _resolve_prefixes(                   # line 11
    model_name: str,
) -> Tuple[Optional[str], Optional[str]]:
    """Returns (query_prefix, passage_prefix) or (None, None).
    Currently handles: E5 family (line 46), BGE-EN-v1.5 (line 50)."""
    ...

class ModelType(Enum):                   # line 60
    """Enum of supported HF model identifiers. Includes MULTI_QA pointing
    to the dot-v1 variant only — needs a sibling MULTI_QA_COS entry."""
    ...

class SentenceTransformerModel(EmbeddingModel):    # line 100
    model_name: str = "sentence-transformers/all-mpnet-base-v2"

    def __init__(self, model_name: str, **kwargs):  # line 106
        # Calls _resolve_prefixes(self.model_name) at line 118
        ...

    def _apply_query_prefix(self, text: str) -> str:    # line 130
    def _apply_passage_prefix(self, texts: List[str]) -> List[str]:  # line 136
    async def embed_documents(...) -> List[List[float]]:  # line 142
    async def embed_query(...) -> Any:  # line 160

# packages/ai-parrot/src/parrot/embeddings/base.py
class EmbeddingModel(ABC):               # line 15
    # self.logger = logging.getLogger(...)  line 22
    ...
```

### Integration Points

| New / Changed | Connects To | Via | Verified At |
|---|---|---|---|
| `EmbeddingModelEntry` (new Pydantic) | `EMBEDDING_MODELS` validation | called once at module import | `catalog.py:12` (target list) |
| New 4 kwargs in `get_embedding_models` | existing call sites | optional kwargs, default `None` | `catalog.py:504-525` |
| New branches in `_resolve_prefixes` | `SentenceTransformerModel.__init__` | already calls resolver at construction | `huggingface.py:118` |
| New `USE_CASE_DESCRIPTIONS` keys | `get_use_cases()` consumers | dict-extension, no API change | `catalog.py:480-501` |
| Cross-consistency pytest | catalog + resolver | imports both modules | `tests/embeddings/` (new file) |

### Existing Tests (won't be modified)

```python
# packages/ai-parrot/tests/embeddings/test_base_registry.py
# packages/ai-parrot/tests/embeddings/test_registry.py
# Neither file imports EMBEDDING_MODELS or _resolve_prefixes today
# (verified: grep returned no matches). Safe to leave untouched.
```

### Real Consumer Reference

```python
# examples/chatbots/att/bot.py:35-38
embedding_model={
    "model": "sentence-transformers/all-mpnet-base-v2",  # to be migrated
    "model_type": "huggingface"
},
# After this spec: operator can switch to "multi-qa-mpnet-base-cos-v1"
# and the catalog will list it with metric_recommended="cosine".
```

### Does NOT Exist (Anti-Hallucination)

- ~~`parrot.embeddings.catalog.EmbeddingModelEntry`~~ — does not exist yet,
  this spec creates it.
- ~~`sentence-transformers/multi-qa-mpnet-base-cos-v1` in the current catalog~~ —
  only the `dot-v1` sibling exists at line 110.
- ~~`metric_recommended` / `requires_prefix` / `prefix_query` /
  `prefix_passage` / `normalized_output` / `max_seq_length` /
  `hnsw_compatible` / `license`~~ keys on any catalog entry — all eight
  are new in this spec.
- ~~Use-case tags `qa` / `long-context` / `instruct` / `asymmetric` /
  `symmetric`~~ — none exist in `USE_CASE_DESCRIPTIONS` today; only
  `similarity`, `retrieval`, `clustering`, `multilingual`, `code` exist.
- ~~`_resolve_prefixes` branch for Jina v3 / gte-Qwen2-instruct /
  e5-mistral-instruct / NV-Embed-v2~~ — none of these are handled today
  (verified: `huggingface.py:40-57` only branches on E5 and BGE-EN-v1.5).
- ~~`get_embedding_models(metric=..., max_dims=..., hnsw_compatible=...,
  requires_prefix=...)`~~ — current signature only accepts `provider` and
  `use_case` (verified: `catalog.py:504-507`).
- ~~`Cohere` / `Voyage` providers~~ — explicitly out of scope.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- The catalog stays a `list[dict]` at runtime — Pydantic is for validation
  only. This preserves the JSON-serialisation contract used by the consumer
  API. Validate once at module import and discard the Pydantic models.
- New catalog entries follow the existing comment-block convention
  (`# -- <Category> -------------`). Group the new entries logically:
  `multi-qa-mpnet-base-cos-v1` next to its `dot-v1` sibling at line 110;
  Jina v3 next to Jina v2 entries at line 314; instruct models in a new
  `# -- Instruct-Tuned -----` block; `NV-Embed-v2` in a new
  `# -- High-Dimension / Specialized -----` block.
- For each new model also append an entry to the `ModelType` enum
  (lines 60-97 of `huggingface.py`) — keep the enum and the catalog symmetric.
- The five new use-case tags must reuse existing entries' tags rather than
  replace them (e.g. `multi-qa-mpnet-base-dot-v1` already has `["retrieval"]`;
  it becomes `["retrieval", "qa", "asymmetric"]`).
- Prefix strings: use the canonical strings from the model authors' docs.
  Sources verified at spec time:

…(truncated)…
