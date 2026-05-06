---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
---

# Feature Specification: Matryoshka Embedding Truncation

**Feature ID**: FEAT-150
**Date**: 2026-05-06
**Author**: Jesus Lara
**Status**: approved
**Target version**: 0.x

---

## 1. Motivation & Business Requirements

### Problem Statement

The embeddings catalog (`parrot/embeddings/catalog.py`) already declares
`matryoshka_dimensions` for several models — `nomic-ai/nomic-embed-text-v1.5`,
`mixedbread-ai/mxbai-embed-large-v1`, `google/embeddinggemma-300m`,
`Snowflake/snowflake-arctic-embed-m-v1.5` — but **no code path consumes
this metadata**. `SentenceTransformerModel.encode()` always returns the
model's full native dimension, and `_dimension` is set unconditionally
from `model.get_embedding_dimension()` (`huggingface.py:232`).

Operators who want to take advantage of Matryoshka Representation Learning
to shrink the pgvector index (e.g. truncate a 768-dim nomic embedding to
512 or 256 dims with minimal quality loss) currently have no opt-in.
This is especially relevant for CPU-only deployments where smaller vectors
mean smaller HNSW indexes, faster ANN queries, and lower memory pressure.

### Goals

- Add an opt-in flag in `vector_store_config['embedding_model']` so an
  operator can request Matryoshka truncation per-bot.
- When enabled, slice the embedding to the requested dimension and
  re-normalize to unit length (L2) so cosine similarity stays correct.
- Validate the configuration at bot configure time (fail-loud), not at
  first query.
- Keep the default behaviour bit-exact: a bot that does not set the flag
  must produce the same vectors it produces today.

### Non-Goals (explicitly out of scope)

- **OpenAI / Google providers** — they expose a server-side `dimensions`
  parameter that is already reachable via their existing model classes.
  This FEAT targets HuggingFace / sentence-transformers only.
- **Auto-selection of an "optimal" Matryoshka dimension.** The operator
  picks the dimension explicitly from the catalog's allowed list.
- **Re-encoding existing rows when the operator changes the dimension
  after the fact.** The pgvector column is a fixed shape; changing it
  requires drop/recreate and re-ingestion. This is documented but not
  automated.
- **Adding new Matryoshka-capable models to the catalog.** Out of scope —
  the four already declared are sufficient. New entries land via
  separate catalog updates.
- **Reranker integration.** `BAAI/bge-reranker-base` and the existing
  `LocalCrossEncoderReranker` are independent; no changes here.

---

## 2. Architectural Design

### Overview

A new optional sub-dict `matryoshka` is added to the
`vector_store_config['embedding_model']` JSONB:

```json
{
  "embedding_model": {
    "model_name": "nomic-ai/nomic-embed-text-v1.5",
    "model_type": "huggingface",
    "matryoshka": {
      "enabled": true,
      "dimension": 512
    }
  }
}
```

When `matryoshka.enabled` is `true`, `SentenceTransformerModel`:

1. Validates the config against the catalog at construction time
   (`matryoshka_dimensions` exists and contains the requested `dimension`).
2. After `encode()` produces L2-normalized native vectors, slices each
   vector to the first `dimension` components and re-applies L2
   normalization so the result is a unit vector in the lower-dim space.
3. Reports the truncated dimension via `get_embedding_dimension()` so
   downstream consumers (pgvector column creation, dimension validation
   in `parrot/stores/postgres.py:1274`) see the right size.

When `matryoshka.enabled` is `false` or the key is absent, the model
behaves bit-exactly as today.

### Component Diagram

```
vector_store_config (JSONB)
        │
        └── embedding_model
                 │
                 ├── model_name, model_type     (existing)
                 │
                 └── matryoshka                  (NEW)
                       ├── enabled: bool
                       └── dimension: int
                              │
                              ▼
        parrot.bots.abstract._initial_embedding_model()
                              │  forwards dict as-is
                              ▼
        parrot.stores.abstract.create_embedding()
                              │  must forward matryoshka kwarg
                              ▼
        parrot.embeddings.registry.EmbeddingRegistry.get_or_create()
                              │  cache key extension required
                              ▼
        parrot.embeddings.huggingface.SentenceTransformerModel.__init__
                              │  validates against catalog
                              │  stores _matryoshka_dim
                              │  overrides _dimension
                              ▼
        encode() → slice[:dim] → L2 renormalize → return
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `EMBEDDING_MODELS` (`parrot/embeddings/catalog.py:171`) | reads | Looks up `matryoshka_dimensions` for the model_name to validate the requested truncation dim. |
| `SentenceTransformerModel` (`huggingface.py:102`) | extends | New `__init__` kwarg `matryoshka`; new private helper `_apply_matryoshka()` invoked from `embed_documents` and `embed_query`. |
| `EmbeddingModel.get_embedding_dimension` (`base.py:133`) | overrides effective return | `_dimension` is set to the truncated value when Matryoshka is active. |
| `EmbeddingRegistry.get_or_create_sync` (`registry.py:202`) | extends cache key | Cache key today is `(model_name, model_type)`; must become `(model_name, model_type, matryoshka_dim or None)` so two bots using the same model with different truncation dims do not share an instance. |
| `AbstractStore.create_embedding` (`stores/abstract.py:298`) | extends | Must forward `matryoshka` from the embedding_model dict into the registry call as kwargs (today only `model_name` / `model_type` are extracted). |
| `_provision_vector_store` (`handlers/bots.py:836`) | extends validation | Enforces equality between `vector_store_config['dimension']` and `embedding_model['matryoshka']['dimension']` when Matryoshka is active. |
| `AbstractBot._initial_embedding_model` (`bots/abstract.py:190`) | unchanged | Already pass-through for the embedding_model dict — no code change, but the dict shape grows. |

### Data Models

A small Pydantic model formalises the new sub-dict and powers the
configure-time validation:

```python
# parrot/embeddings/matryoshka.py  (new module)
from typing import Optional
from pydantic import BaseModel, Field, model_validator


class MatryoshkaConfig(BaseModel):
    """Operator-supplied Matryoshka truncation configuration.

    Shape:
        {"enabled": True, "dimension": 512}

    Validation lives in :func:`validate_against_catalog`, which checks
    that the chosen ``dimension`` is in the model's
    ``matryoshka_dimensions`` list.
    """

    enabled: bool = False
    dimension: Optional[int] = Field(default=None, gt=0)

    @model_validator(mode="after")
    def _consistency(self) -> "MatryoshkaConfig":
        if self.enabled and self.dimension is None:
            raise ValueError(
                "matryoshka.enabled=True requires a 'dimension' value."
            )
        return self


def validate_against_catalog(
    cfg: MatryoshkaConfig,
    model_name: str,
) -> None:
    """Raise ``ConfigError`` if ``cfg`` is not satisfiable for ``model_name``.

    Reads ``EMBEDDING_MODELS`` to find the model entry, then checks:
    1. The entry declares a non-empty ``matryoshka_dimensions`` list.
    2. ``cfg.dimension`` is in that list.

    Out-of-catalog models cannot use Matryoshka — the function raises
    ``ConfigError`` with a clear message.
    """
    ...
```

### New Public Interfaces

```python
# parrot/embeddings/huggingface.py
class SentenceTransformerModel(EmbeddingModel):
    def __init__(
        self,
        model_name: str,
        matryoshka: dict | None = None,  # NEW
        **kwargs,
    ) -> None:
        ...

    def _apply_matryoshka(
        self,
        vectors: "np.ndarray | list[list[float]]",
    ) -> "np.ndarray | list[list[float]]":
        """Slice + L2-renormalize. No-op when Matryoshka is inactive."""
        ...
```

`embed_documents` and `embed_query` are not new public interfaces —
their signatures are unchanged. Only their post-encode pipeline grows
by one step.

---

## 3. Module Breakdown

### Module 1: `MatryoshkaConfig` and catalog validation
- **Path**: `packages/ai-parrot/src/parrot/embeddings/matryoshka.py` (new file)
- **Responsibility**: Pydantic model for the `matryoshka` sub-dict;
  `validate_against_catalog(cfg, model_name)` helper that raises
  `ConfigError` when the requested truncation dim is unsupported.
- **Depends on**: `parrot.embeddings.catalog.EMBEDDING_MODELS`,
  `parrot.exceptions.ConfigError`.

### Module 2: `SentenceTransformerModel` Matryoshka support
- **Path**: `packages/ai-parrot/src/parrot/embeddings/huggingface.py`
- **Responsibility**:
  - Accept and validate `matryoshka` kwarg in `__init__`.
  - Store `self._matryoshka_dim: int | None`.
  - Override `_dimension` to the truncated value when active (in
    `_create_embedding`, after the native dim is read).
  - Add `_apply_matryoshka()` helper.
  - Hook the helper into `embed_documents` (after `encode`, before
    `tolist`) and `embed_query` (after `encode`, before extracting `[0]`).
- **Depends on**: Module 1.

### Module 3: Registry cache-key extension
- **Path**: `packages/ai-parrot/src/parrot/embeddings/registry.py`
- **Responsibility**: Extend `CacheKey` and the `get_or_create` /
  `get_or_create_sync` methods so the cache key includes
  `matryoshka_dim` (read from kwargs). Two bots using the same model
  with different truncation dims must NOT share a cached instance —
  they have different effective dimensions.
- **Depends on**: Module 2 (so the kwarg flows through).

### Module 4: Store-layer kwarg forwarding
- **Path**: `packages/ai-parrot/src/parrot/stores/abstract.py`
- **Responsibility**: `create_embedding` currently extracts only
  `model_type` and `model_name` from the embedding_model dict
  (`stores/abstract.py:322-323`). Extend it to also extract `matryoshka`
  and forward it as a kwarg to `registry.get_or_create_sync`.
- **Depends on**: Module 3.

### Module 5: Bot provisioning enforcement
- **Path**: `packages/ai-parrot/src/parrot/handlers/bots.py`
- **Responsibility**: In `_provision_vector_store` (line 836), when
  `embedding_model['matryoshka']['enabled']` is true, enforce
  `vector_store_config['dimension'] == embedding_model['matryoshka']['dimension']`
  before calling `bot.store.create_collection`. Mismatch raises
  `ConfigError` with a clear message that lists both values.
- **Depends on**: Module 1 (for `MatryoshkaConfig` parsing).

### Module 6: Tests
- **Path**: `packages/ai-parrot/tests/embeddings/test_matryoshka.py` (new),
  plus minor additions to `tests/embeddings/test_base_registry.py` and
  `tests/handlers/` (provisioning).
- **Responsibility**:
  - Truncation math: slicing + L2 renorm yields a unit vector of the
    requested length.
  - Native-dim no-op: when `matryoshka.enabled=false` (or absent), output
    is bit-exact identical to today.
  - `get_embedding_dimension()` returns the truncated dim when active.
  - `validate_against_catalog`: raises `ConfigError` for unknown model,
    unsupported dimension, and missing `matryoshka_dimensions`.
  - Registry cache key separates two configs that differ only in
    matryoshka_dim.
  - Provisioning rejects `vector_store_config['dimension']` ≠
    `matryoshka.dimension`.
- **Depends on**: Modules 1–5.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_matryoshka_config_requires_dimension` | 1 | `enabled=True, dimension=None` raises ValueError. |
| `test_validate_against_catalog_ok` | 1 | `nomic-embed-text-v1.5` + `dimension=512` passes. |
| `test_validate_against_catalog_bad_dim` | 1 | `nomic-embed-text-v1.5` + `dimension=300` raises `ConfigError` (300 ∉ `[64,128,256,512,768]`). |
| `test_validate_against_catalog_unknown_model` | 1 | A model not in `EMBEDDING_MODELS` raises `ConfigError`. |
| `test_validate_against_catalog_no_matryoshka_field` | 1 | `BAAI/bge-base-en-v1.5` (no `matryoshka_dimensions`) raises `ConfigError`. |
| `test_apply_matryoshka_renormalizes` | 2 | Output of `_apply_matryoshka` is unit-norm (‖v‖₂ ≈ 1.0) at the requested dim. |
| `test_embed_documents_truncated_dim` | 2 | With `matryoshka={enabled:True,dimension:512}` on a known model, `embed_documents` returns 512-dim vectors. |
| `test_embed_query_truncated_dim` | 2 | Same for `embed_query`. |
| `test_get_embedding_dimension_truncated` | 2 | `get_embedding_dimension()` returns 512, not the native 768. |
| `test_no_matryoshka_no_change` | 2 | Without the flag, vector dim and values match the pre-FEAT baseline (snapshot test on a small fixture). |
| `test_registry_cache_key_separates_dims` | 3 | Two `get_or_create_sync` calls with the same model but different `matryoshka` dims return distinct instances. |
| `test_create_embedding_forwards_matryoshka` | 4 | `AbstractStore.create_embedding` forwards `matryoshka` kwarg into the registry. |

### Integration Tests

| Test | Description |
|---|---|
| `test_provision_vector_store_dim_mismatch` | Calling `_provision_vector_store` with `vector_store_config['dimension']=768` and `matryoshka.dimension=512` raises `ConfigError` before `create_collection` runs. |
| `test_provision_vector_store_dim_match` | When the two dims match, the pgvector table is created with `vector(512)` and ingestion of a sample document succeeds. |
| `test_end_to_end_search_truncated` | Bot configured with `nomic-embed-text-v1.5` + `matryoshka.dimension=512` ingests 5 short documents and retrieves the most-similar one for a query with cosine ≥ 0.5. |

### Test Data / Fixtures

```python
@pytest.fixture
def matryoshka_bot_config():
    return {
        "vector_store_config": {
            "table": "test_matryoshka",
            "schema": "public",
            "dimension": 512,
            "name": "postgres",
            "metric_type": "COSINE",
            "embedding_model": {
                "model_name": "nomic-ai/nomic-embed-text-v1.5",
                "model_type": "huggingface",
                "matryoshka": {
                    "enabled": True,
                    "dimension": 512,
                },
            },
        }
    }
```

The unit tests in Modules 1–4 must NOT load the heavy
sentence-transformer weights — they should monkeypatch `_create_embedding`
to inject a stub that returns a predictable native-dim numpy array.
Only the integration tests in Module 6 should load real weights.

---

## 5. Acceptance Criteria

- [ ] All unit tests pass: `pytest packages/ai-parrot/tests/embeddings/test_matryoshka.py -v`
- [ ] Existing embedding tests still pass: `pytest packages/ai-parrot/tests/embeddings/ -v`
- [ ] Existing catalog filter tests still pass: `pytest packages/ai-parrot/tests/embeddings/test_get_embedding_models_filters.py -v`
- [ ] Provisioning integration test passes (or is skipped with a clear marker when the test postgres is unavailable).
- [ ] A bot with `matryoshka.enabled=true, dimension=512` on `nomic-embed-text-v1.5` produces 512-dim L2-normalized vectors from both `embed_documents` and `embed_query`, and `get_embedding_dimension()` returns 512.
- [ ] A bot without the flag (or with `enabled=false`) produces the same vectors as before this FEAT — verified by a snapshot test on a small fixture against a stub model.
- [ ] Misconfiguration (unknown dim, unsupported model, dim ≠ vector_store_config.dimension) raises `ConfigError` at bot configure time, before any embedding is computed.
- [ ] Two `EmbeddingRegistry.get_or_create_sync` calls with the same model but different `matryoshka.dimension` return distinct objects.
- [ ] No breaking change to existing public API — `SentenceTransformerModel(model_name=...)` without the new kwarg works identically.
- [ ] Documentation: a new short subsection in `docs/` (or the closest existing rag/embeddings doc) describes the flag, the validation rules, and the operational caveat that changing `matryoshka.dimension` after ingestion requires drop/recreate.

---

## 6. Codebase Contract

### Verified Imports

```python
from parrot.embeddings.catalog import EMBEDDING_MODELS  # verified: parrot/embeddings/catalog.py:171
from parrot.embeddings import (
    EMBEDDING_MODELS,
    EmbeddingRegistry,
    get_embedding_models,
    get_model_recommendations,
    get_use_cases,
    supported_embeddings,
)  # verified: parrot/embeddings/__init__.py:1-31
from parrot.embeddings.huggingface import SentenceTransformerModel  # verified: huggingface.py:102
from parrot.embeddings.base import EmbeddingModel  # verified: base.py:15
from parrot.exceptions import ConfigError  # verified: parrot/exceptions.py:45
```

### Existing Class Signatures

```python
# parrot/embeddings/catalog.py
class EmbeddingModelEntry(BaseModel):  # line 36
    model: str                                       # line 76
    provider: Provider                               # line 77
    name: str                                        # line 78
    dimension: int = Field(gt=0)                     # line 79
    multilingual: bool                               # line 80
    language: str                                    # line 81
    use_case: list[UseCaseTag]                       # line 82
    description: str                                 # line 83
    metric_recommended: Metric                       # line 85
    requires_prefix: bool                            # line 86
    prefix_query: Optional[str] = None               # line 87
    prefix_passage: Optional[str] = None             # line 88
    normalized_output: bool                          # line 89
    max_seq_length: int = Field(gt=0)                # line 90
    hnsw_compatible: bool                            # line 91
    license: str                                     # line 92
    recommended_score_threshold: float = Field(...)  # line 93
    recommended_search_limit: int = Field(...)       # line 94
    matryoshka_dimensions: Optional[list[int]] = None  # line 96  ← KEY field for this FEAT

EMBEDDING_MODELS: List[Dict[str, Any]] = [...]       # line 171 (validated at import)

def get_model_recommendations(model_name) -> Optional[Dict[str, Any]]:  # line 1248
    # Returns ONLY recommended_score_threshold and recommended_search_limit.
    # Does NOT currently surface matryoshka_dimensions — Module 1 must read
    # EMBEDDING_MODELS directly (or extend this function) for validation.
```

```python
# parrot/embeddings/base.py
class EmbeddingModel(ABC):                            # line 15
    def __init__(self, model_name: str, **kwargs):    # line 20
        self.model_name = model_name                  # line 21
        self._dimension = None                        # line 25
        self._kwargs = kwargs                         # line 29

    def get_embedding_dimension(self) -> int:         # line 133
        return self._dimension                        # line 134

    async def embed_documents(                        # line 169
        self, texts: List[str], batch_size: Optional[int] = None
    ) -> List[List[float]]:
        result = await self.encode(texts, normalize_embeddings=True)  # line 183
        if hasattr(result, "tolist"):
            return result.tolist()                    # line 185
        return result

    async def embed_query(                            # line 188
        self, text: str, as_nparray: bool = False
    ) -> Union[List[float], List[np.ndarray]]:
        result = await self.encode(
            [text],
            convert_to_tensor=False,
            normalize_embeddings=True,
            show_progress_bar=False,
        )                                              # line 202-207
        if hasattr(result, "tolist"):
            result = result.tolist()
        embedding = result[0]                          # line 211
        ...

    @abstractmethod
    async def encode(self, texts: List[str], **kwargs) -> np.ndarray:  # line 226
        pass
```

```python
# parrot/embeddings/huggingface.py
class SentenceTransformerModel(EmbeddingModel):       # line 102
    model_name: str = "sentence-transformers/all-mpnet-base-v2"  # line 106

    def __init__(self, model_name: str, **kwargs):    # line 108
        super().__init__(model_name=model_name, **kwargs)
        self._query_prefix, self._passage_prefix = _resolve_prefixes(
            self.model_name
        )                                              # lines 120-122

    async def embed_documents(                         # line 144
        self, texts, batch_size=None
    ) -> List[List[float]]:
        prefixed = self._apply_passage_prefix(texts)   # line 156
        result = await self.encode(prefixed, normalize_embeddings=True)  # 157
        if hasattr(result, "tolist"):
            return result.tolist()                     # line 159
        return result

    async def embed_query(                             # line 162
        self, text, as_nparray=False
    ):
        prefixed = self._apply_query_prefix(text)      # line 174
        result = await self.encode(
            [prefixed],
            convert_to_tensor=False,
            normalize_embeddings=True,
            show_progress_bar=False,
        )                                              # lines 175-180
        if hasattr(result, "tolist"):
            result = result.tolist()
        embedding = result[0]                          # line 183
        ...

    def _create_embedding(self, model_name=None, **kwargs):  # line 188
        ...
        self._dimension = model.get_embedding_dimension()  # line 232  ← override here
        ...

    async def encode(self, texts, **kwargs) -> np.ndarray:  # line 242
        raw_model = self.model
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            self.executor,
            lambda: raw_model.encode(texts, **kwargs),
        )                                              # lines 247-251
```

```python
# parrot/embeddings/registry.py
class EmbeddingRegistry:
    def _build_model(self, model_name: str, model_type: str, **kwargs):  # line 115
        ...
        klass = getattr(module, cls_name)
        return klass(model_name=model_name, **kwargs)  # line 140

    async def get_or_create(
        self, model_name: str, model_type: str = "huggingface", **kwargs,
    ) -> Any:                                          # line 182
        key: CacheKey = (model_name, model_type)       # line 202  ← extend this
        ...

    def get_or_create_sync(
        self, model_name: str, model_type: str = "huggingface", **kwargs,
    ) -> Any:                                          # line 294
```

```python
# parrot/stores/abstract.py
def create_embedding(self, embedding_model: dict, **kwargs):  # line 298
    from ..embeddings import EmbeddingRegistry
    model_type = embedding_model.get('model_type', 'huggingface')   # line 322
    model_name = embedding_model.get('model_name', EMBEDDING_DEFAULT_MODEL)  # line 323
    if model_type not in supported_embeddings:
        raise ConfigError(
            f"Embedding Model Type: {model_type} not supported."
        )
    registry = EmbeddingRegistry.instance()
    return registry.get_or_create_sync(model_name, model_type, **kwargs)  # line 329
    # ↑ NOTE: kwargs flows from the caller, not from embedding_model itself.
    #         Module 4 must extract embedding_model['matryoshka'] and merge it.
```

```python
# parrot/handlers/bots.py
async def _provision_vector_store(self, bot, vector_store_config: dict) -> dict:  # line 836
    if not bot or not vector_store_config:
        return {"status": "none"}
    table = vector_store_config.get('table')                   # line 857
    schema = vector_store_config.get('schema')                 # line 858
    if not table or not schema:
        return {"status": "none"}
    store_type = vector_store_config.get('name', 'postgres')   # line 862
    dimension = vector_store_config.get('dimension', 384)      # line 863
    embedding_model = vector_store_config.get('embedding_model')  # line 864
    # ↑ Module 5 inserts the dim-equality check here, BEFORE define_store.
    ...
    bot.define_store(vector_store=store_type, **store_kwargs)  # line 875
    bot.configure_store()                                      # line 876
    await bot.store.connection()
    await bot.store.create_collection(
        table=table, schema=schema, dimension=dimension
    )                                                          # lines 878-880
```

```python
# parrot/bots/abstract.py
@staticmethod
def _initial_embedding_model(                                  # line 190
    vector_store_config: Any,
    legacy_kwarg: Any = None,
) -> dict:
    if isinstance(vector_store_config, dict):
        emb = vector_store_config.get('embedding_model')       # line 202
        if isinstance(emb, dict) and emb:
            return emb                                          # line 204  ← pass-through, no change
    ...

# parrot/bots/abstract.py:520-525  (in __init__)
_legacy_emb_kwarg = kwargs.get('embedding_model')
if _legacy_emb_kwarg and isinstance(self._vector_store, dict):
    self._vector_store.setdefault('embedding_model', _legacy_emb_kwarg)
self.embedding_model = self._initial_embedding_model(
    self._vector_store, _legacy_emb_kwarg
)
```

### Catalog entries with `matryoshka_dimensions`

Verified at `parrot/embeddings/catalog.py`:

| Model | Line | Allowed Matryoshka dims |
|---|---|---|
| `nomic-ai/nomic-embed-text-v1.5` | 779 | `[64, 128, 256, 512, 768]` |
| `mixedbread-ai/mxbai-embed-large-v1` | 804 | `[128, 256, 512, 768, 1024]` |
| `google/embeddinggemma-300m` | 831 | `[128, 256, 512, 768]` |
| `Snowflake/snowflake-arctic-embed-m-v1.5` | 882 | `[128, 256, 384, 512, 768]` |

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `MatryoshkaConfig` | `EMBEDDING_MODELS` | Direct list lookup by `model` field | `catalog.py:171` |
| `_apply_matryoshka()` | `numpy` slicing + L2 renorm | Function call inside `embed_documents` / `embed_query` | `huggingface.py:144,162` |
| Registry cache key | `OrderedDict` keyed on tuple | Adds 3rd element `matryoshka_dim or None` | `registry.py:202` |
| `create_embedding` | `registry.get_or_create_sync` | Passes `matryoshka=...` in kwargs | `stores/abstract.py:329` |
| `_provision_vector_store` | `MatryoshkaConfig` | Validates dim equality before `create_collection` | `handlers/bots.py:863-880` |

### Does NOT Exist (Anti-Hallucination)

- ~~`EmbeddingModelEntry` is exported from `parrot.embeddings`~~ — **NOT exported** (intentionally hidden, see `embeddings/__init__.py:11-13`). The implementation must read `EMBEDDING_MODELS` (the validated dict list) and not import the schema class.
- ~~`get_model_recommendations()` returns `matryoshka_dimensions`~~ — it returns ONLY `recommended_score_threshold` and `recommended_search_limit` (`catalog.py:1248-1275`). New code must read `EMBEDDING_MODELS` directly or extend this helper.
- ~~`SentenceTransformer.encode()` accepts `truncate_dim` automatically~~ — it does in sentence-transformers ≥ 3.0 for some models, but the project does not pin that version everywhere. Implementation MUST do its own slice + L2 renorm to be portable; do NOT rely on `truncate_dim`.
- ~~`EmbeddingRegistry` cache key already includes kwargs~~ — it does NOT (`registry.py:202`: `key: CacheKey = (model_name, model_type)`). Module 3 must change this.
- ~~There is a generic `embedding_factory` function~~ — there is not. The flow is: `create_embedding(embedding_model_dict)` (`stores/abstract.py:298`) → `EmbeddingRegistry.get_or_create_sync` → `_build_model` → `klass(...)`.
- ~~`AbstractBot._initial_embedding_model` validates the dict~~ — it does NOT validate, only resolves precedence. Validation must live in `SentenceTransformerModel.__init__` and `_provision_vector_store`.
- ~~OpenAI / Google embedding classes need updating~~ — out of scope. Their dimension control is server-side via different APIs.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- Pydantic v2 for the new `MatryoshkaConfig` model, consistent with
  `EmbeddingModelEntry` in `catalog.py`.
- Async-first: do not introduce blocking I/O in any new code path. The
  truncation post-processing is pure CPU on numpy arrays — no async
  primitives needed.
- Logger via `self.logger` (already wired in `EmbeddingModel.__init__`
  at `base.py:22`); INFO log when Matryoshka activates with the
  effective dimension.
- Fail-loud: configuration errors raise `ConfigError` (a subclass of
  `ParrotError`) at configure time. Never silently fall back to native
  dim when the operator asked for truncation.

### Known Risks / Gotchas

- **Registry cache key pollution.** Today the cache key is
  `(model_name, model_type)`. Two bots that use the same model with
  different `matryoshka.dimension` would silently share one instance —
  whichever one loaded first wins. Module 3 fixes this by extending the
  key. This is the highest-risk failure mode if the spec is implemented
  incompletely.

- **Dimension drift between pgvector column and embedding output.**
  pgvector columns are fixed-size at table creation. If
  `vector_store_config['dimension']` and `matryoshka.dimension` disagree
  (or someone changes one without the other), inserts will fail at
  runtime with a cryptic error from
  `parrot/stores/postgres.py:1274`. Module 5 validates this upfront.

- **No re-encoding on dim change.** Once a pgvector table is created
  with `vector(N)`, changing the truncation dim later requires
  drop/recreate the table and re-ingest all documents. The spec
  documents this caveat; automation is out of scope.

- **L2 renormalization correctness.** A truncated unit vector is no
  longer unit-norm (only the full vector is). Re-normalizing is
  required for cosine to remain comparable across dims. The unit test
  `test_apply_matryoshka_renormalizes` exists specifically to catch a
  forgotten renorm.

- **Models without true Matryoshka training.** Slicing + renorming any
  model produces a vector — it just has poor quality unless the model
  was Matryoshka-trained. The catalog's `matryoshka_dimensions` field
  is the authority on which models are safe; out-of-list dims are
  rejected.

- **Sentence-transformers version drift.** Some recent versions of
  `sentence-transformers` accept `truncate_dim` natively. We do NOT use
  that — we do our own slicing — to keep behaviour stable across
  versions. Document this in the implementation comment.

- **Backward compatibility of the embedding_model dict.** The new
  `matryoshka` key is optional. Existing bots in DB with no
  `matryoshka` field continue to work unchanged. No migration of
  `vector_store_config` rows is required.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| (none new) | — | All work uses existing `numpy`, `pydantic`, `sentence-transformers`, `transformers`. |

---

## Worktree Strategy

- **Default isolation unit**: per-spec.
- All six modules are tightly coupled (data shape → model → registry →
  store → handler → tests) and must land together on one feature
  branch. Tasks run sequentially in a single worktree at
  `.claude/worktrees/feat-150-matryoshka-embedding-truncation/`.
- **Cross-feature dependencies**: none. The reranker subsystem
  (FEAT-133 / `parrot/rerankers/`) is independent and not touched here.

---

## 8. Open Questions

- [x] Should `validate_against_catalog` be promoted to a public helper in
      `parrot.embeddings` (alongside `get_model_recommendations`), or stay
      module-private? — *Owner: implementer*. Pick whichever is consistent
      with how other configure-time validators are exposed in the
      package; not a design blocker: promoted to public helper.
- [x] Should the registry cache key also include relevant `**kwargs` in
      general (defensive), or only `matryoshka_dim`? — *Owner: implementer*.
      Recommendation: only `matryoshka_dim` for now — generalising the
      cache-key contract is a separate scope: only matryoshka_dim

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-05-06 | Jesus Lara | Initial draft (no brainstorm — feature scope was clear from prior conversation). |
