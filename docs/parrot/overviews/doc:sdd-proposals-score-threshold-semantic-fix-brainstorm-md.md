---
type: Wiki Overview
title: 'Brainstorm: score_threshold Semantic Fix'
id: doc:sdd-proposals-score-threshold-semantic-fix-brainstorm-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'with **contradictory semantics**:'
relates_to:
- concept: mod:parrot.embeddings.registry
  rel: mentions
- concept: mod:parrot.handlers.models.bots
  rel: mentions
- concept: mod:parrot.stores.abstract
  rel: mentions
- concept: mod:parrot.stores.models
  rel: mentions
- concept: mod:parrot.stores.postgres
  rel: mentions
---

# Brainstorm: score_threshold Semantic Fix

**Date**: 2026-05-04
**Author**: Jesus Lara
**Status**: exploration
**Recommended Option**: Option B

---

## Problem Statement

`score_threshold` is used across vector stores, episodic memory backends, bots, and handlers
with **contradictory semantics**:

- **Vector stores** (PgVector, BigQuery): `score_threshold` means **maximum distance**
  (`distance <= threshold`). Lower distance = more similar.
- **Episodic memory backends** (PgVector episodic, FAISS episodic, Redis) and **ArangoDB**:
  `score_threshold` means **minimum similarity** (`score >= threshold`). Higher score = more similar.

This is a semantic footgun: a developer setting `score_threshold=0.7` gets radically different
filtering behavior depending on which component they're configuring. The name itself is ambiguous
— "score" could mean distance or similarity.

Additionally, PgVector applies the same threshold comparison (`distance_expr <= score_threshold`)
identically for COSINE (range 0-1), L2 (range 0-infinity), and MAX_INNER_PRODUCT (range varies),
meaning a threshold of 0.7 has completely different selectivity per metric.

**Affected**: All developers using RAG retrieval, episodic memory, or vector search.

## Constraints & Requirements

- Breaking API change is acceptable (no deprecation shim needed).
- Must not break existing RAG chatbot agents during the transition — bots with `context_score_threshold=0.7` in the DB must continue to work correctly.
- Episodic memory backends already use similarity semantics — their rename is cosmetic.
- PgVector and BigQuery use distance semantics — their rename carries behavioral awareness.
- Database migration is acceptable (rename columns or move to JSONB).
- Per-embedding-model recommended thresholds and search limits are a desired addition.
- FAISS metric-aware branching must be preserved and extended to PgVector.

---

## Options Explored

### Option A: Rename Only — Distinct Names, Same Behavior

Rename the parameter everywhere to match its actual semantics:
- Vector stores (PgVector, BigQuery, FAISS distance-mode): `score_threshold` -> `max_distance`
- Episodic backends, ArangoDB, FAISS similarity-mode: `score_threshold` -> `min_similarity`
- Abstract base class: `similarity_threshold` -> `max_distance` (for stores) or keep as `min_similarity`
- Bot config: `context_score_threshold` -> `context_max_distance`

No behavioral changes. Pure rename + documentation.

Pros:
- Lowest risk — no logic changes, just naming.
- Immediately resolves the naming ambiguity.
- Easy to review and test — grep-and-replace with verification.

Cons:
- Does not fix the PgVector metric-agnostic threshold bug (L2 vs cosine vs IP use same comparison).
- Does not add per-embedding recommended defaults.
- Does not move config into the JSONB `embedding_model` column.
- Leaves the system with two separate parameter names (`max_distance` and `min_similarity`) that callers must know about.

Effort: Low

Libraries / Tools:
| Package | Purpose | Notes |
|---|---|---|
| `alembic` | Database migration for column rename | Already in use |

Existing Code to Reuse:
- `parrot/stores/postgres.py` — threshold filtering at line 861
- `parrot/stores/abstract.py` — base class signature at line 217
- `parrot/handlers/models/bots.py` — DB schema and Pydantic model

---

### Option B: Full Semantic Fix — Rename + Metric-Aware Thresholds + JSONB Migration + Embedding Registry

Comprehensive fix addressing all identified issues:

1. **Rename** `score_threshold` to `max_distance` (stores) and `min_similarity` (episodic/similarity backends).
2. **Add metric-aware threshold filtering** to PgVector and BigQuery (currently only FAISS does this). For MAX_INNER_PRODUCT, the comparison should be `>=` (higher = more similar), not `<=`.
3. **Move threshold config into `embedding_model` JSONB** column with structure:
   ```json
   {
     "model_name": "sentence-transformers/all-mpnet-base-v2",
     "model_type": "huggingface",
     "max_distance": 0.7,
     "min_similarity": null,
     "search_limit": 10
   }
   ```
4. **Add an embedding model registry** mapping `(model, distance_metric)` -> `recommended_max_distance`, `recommended_search_limit`.
5. **Deprecate** standalone `context_score_threshold` and `context_search_limit` DB columns (read as fallback, write to JSONB).

Pros:
- Completely resolves the semantic ambiguity.
- Fixes the PgVector metric-agnostic threshold bug.
- Consolidates config into the JSONB column (single source of truth per bot).
- Embedding registry provides sensible defaults — reduces footgun for new users.
- Future-proof: adding new metrics or models only requires registry entries.

Cons:
- Higher effort — touches stores, bots, handlers, memory backends, and DB schema.
- Requires careful migration for existing bots with `context_score_threshold` in DB.
- Embedding registry needs maintenance as new models are released.

Effort: High

Libraries / Tools:
| Package | Purpose | Notes |
|---|---|---|
| `alembic` | Database migration (JSONB restructure + column deprecation) | Already in use |
| `pydantic` | Embedding model config schema | Already in use |

Existing Code to Reuse:
- `parrot/stores/postgres.py` — `get_distance_strategy()` (line 684) for metric dispatch
- `parrot/stores/faiss_store.py` — metric-aware threshold branching (lines 613-621) as pattern
- `parrot/stores/models.py` — `DistanceStrategy` enum (line 49)
- `parrot/handlers/models/bots.py` — `default_embed_model()` (line 16) and JSONB column
- `parrot/bots/abstract.py` — `context_score_threshold` usage (line 416)

---

### Option C: Unified Similarity Interface — Convert Everything to Similarity Space

Instead of keeping two names, normalize all stores to return similarity scores (0-1, higher = better)
by converting distances internally:
- Cosine: `similarity = 1 - distance`
- L2: `similarity = 1 / (1 + distance)`
- IP: already similarity-like (normalize to 0-1 range)

Then use a single parameter `min_similarity` everywhere. The conversion happens inside each
store's search method before returning results.

Pros:
- Single parameter name everywhere (`min_similarity`).
- Users always think in "higher = better" terms — most intuitive.
- `SearchResult.score` always means similarity — no ambiguity.
- Simplifies downstream consumers (bots, memory, tools).

Cons:
- Behavioral change in PgVector/BigQuery — existing threshold values would need recalculation.
- Conversion adds overhead (minor, but present on every search).
- L2 normalization is lossy — `1/(1+d)` compresses the high-distance range.
- MAX_INNER_PRODUCT normalization is tricky for unnormalized embeddings.
- Breaks the `SearchResult.score` / `distance` alias pattern that currently exists.
- Significantly higher risk of subtle bugs during transition.

Effort: High

Libraries / Tools:
| Package | Purpose | Notes |
|---|---|---|
| `alembic` | Database migration | Already in use |
| `numpy` | Distance-to-similarity conversions | Already a dependency |

Existing Code to Reuse:
- `parrot/stores/models.py` — `SearchResult` model (line 7) would need `score` semantics change
- `parrot/memory/episodic/backends/` — already uses similarity semantics (pattern to follow)

---

### Option D: Documentation-Only Fix + Dual-Name Support

Keep `score_threshold` working everywhere but add `max_distance` and `min_similarity` as
supported aliases. When both old and new names are provided, the new name wins. Add extensive
docstrings and a developer guide explaining the semantics per store.

Pros:
- Zero breaking changes.
- Gradual migration — old code keeps working, new code uses clear names.
- Lowest risk approach.

Cons:
- Does not fix the metric-agnostic threshold bug.
- Three names for the same concept increases confusion.
- Old code never migrates unless someone goes back and updates it.
- Does not add embedding registry or JSONB consolidation.

Effort: Low

Libraries / Tools:
| Package | Purpose | Notes |
|---|---|---|
| N/A | Documentation only | No new dependencies |

Existing Code to Reuse:
- All existing store implementations — add alias handling in `**kwargs` processing

---

## Recommendation

**Option B** is recommended because:

It is the only option that addresses all four identified problems simultaneously:
the naming ambiguity, the metric-agnostic threshold bug in PgVector, the scattered config
(separate DB columns vs. JSONB), and the missing embedding model defaults.

Option A fixes the name but leaves the behavioral bug. Option C is theoretically cleaner
(single similarity space) but carries higher risk of subtle conversion bugs and breaks the
existing `SearchResult.score`/`distance` pattern. Option D avoids breakage but accumulates
technical debt.

The tradeoff is effort: Option B touches many files across multiple packages. However, the
changes decompose cleanly into independent tasks (rename in stores, rename in episodic, add
metric-aware filtering, JSONB migration, embedding registry), making parallel execution feasible.

The breaking API change is acceptable per user decision, and the migration path for existing
bots (read `context_score_threshold` column as fallback when JSONB key is absent) prevents
data loss.

---

## Feature Description

### User-Facing Behavior

Developers configuring vector search will use unambiguous parameter names:
- `max_distance` when working with distance-based stores (PgVector, BigQuery).
- `min_similarity` when working with similarity-based stores (ArangoDB) or episodic memory.

Bot configuration in the database moves threshold and search limit settings into the
`embedding_model` JSONB column. The old `context_score_threshold` and `context_search_limit`
columns are read as fallbacks during migration but new writes go to JSONB.

An embedding model registry provides recommended defaults:
```python
EMBEDDING_DEFAULTS = {
    "sentence-transformers/all-mpnet-base-v2": {
        "dimensions": 768,
        "distance_metric": "COSINE",
        "recommended_max_distance": 0.7,
        "recommended_search_limit": 10,
    },
    "text-embedding-3-small": {
        "dimensions": 1536,
        "distance_metric": "COSINE",
        "recommended_max_distance": 0.5,
        "recommended_search_limit": 10,
    },
}
```

When a bot does not specify a threshold, the system looks up the recommended value from
the registry based on the configured embedding model.

### Internal Behavior

1. **Store layer**: `PgVectorStore.similarity_search()` and `BigQueryStore.similarity_search()`
   accept `max_distance` parameter. Threshold filtering is metric-aware:
   - COSINE, L2: `distance_expr <= max_distance`
   - MAX_INNER_PRODUCT, DOT_PRODUCT: `distance_expr >= max_distance` (inverted — higher = closer)

2. **Episodic memory layer**: All backends accept `min_similarity` parameter with
   `score >= min_similarity` filtering (unchanged behavior, renamed parameter).

3. **Bot layer**: `AbstractBot.retrieve_context()` reads threshold from
   `self.embedding_model["max_distance"]` (falling back to `self.context_score_threshold`
   for backward compatibility). Passes `max_distance` to stores.

4. **Abstract base class**: `AbstractStore.similarity_search()` signature updated to
   use `max_distance` (replacing `similarity_threshold`).

5. **Embedding registry**: New module `parrot/embeddings/registry.py` maps model names to
   recommended thresholds. Used as default when bot config has no explicit threshold.

6. **DB migration**: Alembic migration merges `context_score_threshold` and
   `context_search_limit` into the `embedding_model` JSONB column. Old columns remain
   readable but are deprecated.

### Edge Cases & Error Handling

- **Missing JSONB keys**: If `embedding_model` JSONB lacks `max_distance`, fall back to
  `context_score_threshold` column, then to registry default, then to a safe global default.
- **Unknown embedding model**: If the model is not in the registry, log a warning and use
  a conservative global default (e.g., `max_distance=0.8` for COSINE).
- **Mixed metric configs**: If a bot's JSONB has `min_similarity` but the store expects
  `max_distance`, raise a `ValueError` with a clear message explaining the mismatch.
- **L2 threshold range**: L2 distances are unbounded (0 to infinity). The registry should
  provide model-specific defaults. A threshold of 0.7 for L2 is very restrictive — warn
  if L2 threshold < 1.0.

---

## Capabilities

### New Capabilities
- `embedding-model-registry`: Registry mapping embedding models to recommended thresholds and search limits
- `metric-aware-threshold-filtering`: Distance-metric-specific threshold comparisons in PgVector and BigQuery

### Modified Capabilities
- `vector-store-search`: Rename `score_threshold` to `max_distance`, add metric-aware filtering
- `episodic-memory-search`: Rename `score_threshold` to `min_similarity`
- `bot-context-retrieval`: Read threshold from `embedding_model` JSONB, fallback chain
- `bot-database-schema`: Migrate threshold config into `embedding_model` JSONB

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `parrot/stores/postgres.py` | modifies | Rename param, add metric-aware filtering |
| `parrot/stores/bigquery.py` | modifies | Rename param, add metric-aware filtering |
| `parrot/stores/faiss_store.py` | modifies | Rename param (keep existing metric-aware logic) |
| `parrot/stores/abstract.py` | modifies | Rename `similarity_threshold` to `max_distance` |
| `parrot/stores/models.py` | extends | Add threshold metadata to `DistanceStrategy` or `SearchResult` |
| `parrot_tools/arangodbsearch.py` | modifies | Rename `score_threshold` to `min_similarity` |
| `parrot/memory/episodic/backends/*.py` | modifies | Rename param to `min_similarity` |
| `parrot/memory/episodic/store.py` | modifies | Rename param propagation |
| `parrot/memory/episodic/recall.py` | modifies | Rename param propagation |
| `parrot/bots/abstract.py` | modifies | Read from JSONB, fallback chain |
| `parrot/bots/base.py` | modifies | Propagate renamed param |
| `parrot/bots/chatbot.py` | modifies | Propagate renamed param |
| `parrot/bots/flow/fsm.py` | modifies | Propagate renamed param |
| `parrot/bots/orchestration/crew.py` | modifies | Propagate renamed param |
| `parrot/handlers/models/bots.py` | modifies | JSONB schema update, column deprecation |
| `parrot/handlers/models/users_bots.py` | modifies | Propagate renamed field |
| `parrot/interfaces/vector.py` | modifies | Rename param in ensemble search |
| `parrot/tools/vectorstoresearch.py` | modifies | Rename param |
| `parrot/advisors/catalog/catalog.py` | modifies | Rename param |
| `parrot/models/responses.py` | modifies | Rename response model field |
| `parrot/registry/routing/store_router.py` | modifies | Update kwargs documentation |
| `parrot/embeddings/registry.py` | new | Embedding model defaults registry |
| `parrot/manager/manager.py` | modifies | Propagate renamed param |
| DB migration (alembic) | new | JSONB restructure + column deprecation |

---

## Code Context

### Verified Codebase References

#### Classes & Signatures
```python
# From parrot/stores/postgres.py:684
def get_distance_strategy(
    self,
    embedding_column_obj,
    query_embedding,
    metric: str = None
) -> Any:
    ...

# From parrot/stores/postgres.py:741 (approx)
async def similarity_search(
    self,
    query: str,
    collection: str = None,
    limit: int = 2,
    score_threshold: Optional[float] = None,  # THIS IS THE TARGET
    ...
) -> list:
    ...

# From parrot/stores/postgres.py:860-861 — THE BUG
# if score_threshold is not None:
#     stmt = stmt.where(distance_expr <= score_threshold)
# ^ Same comparison for all metrics — wrong for MAX_INNER_PRODUCT

# From parrot/stores/abstract.py:217
@abstractmethod
async def similarity_search(
    self,
    query: str,
    collection: Union[str, None] = None,
    limit: int = 2,
    similarity_threshold: float = 0.0,  # NOTE: different name from implementations
    search_strategy: str = "auto",
    metadata_filters: Union[dict, None] = None,
    include_parents: bool = False,
    **kwargs
) -> list:
    ...

# From parrot/stores/faiss_store.py:613-621 — METRIC-AWARE PATTERN TO FOLLOW
# if score_threshold is not None:
#     if self.distance_strategy == DistanceStrategy.EUCLIDEAN_DISTANCE:
#         if distances[np.where(indices == idx)[0][0]] > score_threshold:
#             continue
#     else:
#         if score < score_threshold:
#             continue

# From parrot/stores/models.py:49
class DistanceStrategy(str, Enum):
    EUCLIDEAN_DISTANCE = "EUCLIDEAN_DISTANCE"
    MAX_INNER_PRODUCT = "MAX_INNER_PRODUCT"
    DOT_PRODUCT = "DOT_PRODUCT"
    JACCARD = "JACCARD"
    COSINE = "COSINE"

# From parrot/stores/models.py:7
class SearchResult(BaseModel):
    id: str
    content: str
    metadata: Dict[str, Any] = Field(default_factory=dict)
    score: float = Field(...)  # raw metric value, lower=closer for distance

# From parrot/handlers/models/bots.py:16-20
def default_embed_model():
    return {
        "model_name": "sentence-transformers/all-mpnet-base-v2",
        "model_type": "huggingface"
    }

# From parrot/handlers/models/bots.py:247-251
# context_score_threshold: float = Field(default=0.7)

# From parrot/bots/abstract.py:416-417
# self.context_score_threshold: float = kwargs.get('context_score_threshold', 0.7)

# From parrot/memory/episodic/backends/pgvector.py:335
# if score >= score_threshold:  # SIMILARITY semantics (correct)

# From parrot/memory/episodic/backends/redis_vector.py:301
# if score >= score_threshold:  # SIMILARITY semantics (correct)
```

#### Verified Imports
```python
# These imports have been confirmed to work:
from parrot.stores.models import DistanceStrategy    # parrot/stores/models.py:49
from parrot.stores.models import SearchResult        # parrot/stores/models.py:7
from parrot.stores.abstract import AbstractStore     # parrot/stores/abstract.py
```

#### Key Attributes & Constants
- `PgVectorStore.distance_strategy` -> `DistanceStrategy` (parrot/stores/postgres.py)
- `AbstractBot.context_score_threshold` -> `float` (parrot/bots/abstract.py:416)
- `BotModel.context_score_threshold` -> `float` default 0.7 (parrot/handlers/models/bots.py:247)
- `BotModel.context_search_limit` -> `int` default 10 (parrot/handlers/models/bots.py)
- `BotModel.embedding_model` -> `dict` (parrot/handlers/models/bots.py:237)
- Default threshold 0.7 used in: bots/abstract.py, bots/flow/fsm.py, bots/orchestration/crew.py
- Default threshold 0.3 used in: episodic/backends/pgvector.py, advisors/catalog/catalog.py

### Does NOT Exist (Anti-Hallucination)
- ~~`parrot.embeddings.registry`~~ — does not exist yet (to be created)
- ~~`parrot.stores.postgres.PgVectorStore.metric_aware_filter()`~~ — no such method exists
- ~~`parrot.stores.abstract.AbstractStore.max_distance`~~ — parameter is currently `similarity_threshold`
- ~~`parrot.handlers.models.bots.BotModel.embedding_model["max_distance"]`~~ — JSONB currently only has `model_name` and `model_type`
- ~~`parrot.stores.models.DistanceStrategy.threshold_range`~~ — enum has no threshold metadata

---

## Parallelism Assessment

- **Internal parallelism**: High. The feature decomposes into several independent tracks:
  1. Store rename + metric-aware filtering (PgVector, BigQuery) — independent
  2. Episodic memory rename — independent (different files, different semantics)
  3. Embedding model registry — independent (new module)
  4. JSONB migration + bot layer changes — depends on registry (#3)
  5. FAISS rename — independent
  6. ArangoDB rename — independent
  Tracks 1, 2, 3, 5, 6 can run in parallel. Track 4 depends on 3.

- **Cross-feature independence**: Low conflict risk. The main shared files are
  `parrot/bots/abstract.py` and `parrot/handlers/models/bots.py` which are frequently
  modified but the changes here are parameter renames, not structural.

- **Recommended isolation**: `per-spec` (single worktree with sequential task execution)

- **Rationale**: Although tasks are logically independent, they touch shared interfaces
  (`AbstractStore`, `AbstractBot`) and a coordinated rename is safer in one worktree
  to avoid merge conflicts from parallel renames of the same parameter in different tasks.

---

## Open Questions

- [ ] What embedding models should be in the initial registry? At minimum: `sentence-transformers/all-mpnet-base-v2`, `text-embedding-3-small`, `text-embedding-3-large`, `text-embedding-ada-002`. What others? — *Owner: Jesus*
- [ ] Should `max_distance` for MAX_INNER_PRODUCT be renamed differently since "distance" is misleading for IP? Or is the metric-aware comparison inversion sufficient? — *Owner: Jesus*
- [ ] For the JSONB migration: should existing `context_score_threshold` DB values be copied into the JSONB automatically by the migration, or left as fallback-only? — *Owner: Jesus*
- [ ] Should the abstract base class `similarity_search` support both `max_distance` and `min_similarity` kwargs, or only `max_distance` with stores that use similarity semantics converting internally? — *Owner: Jesus*
- [x] Is a breaking API change acceptable? — *Owner: Jesus*: Yes, breaking change is acceptable.
- [x] Should FAISS keep metric-aware branching? — *Owner: Jesus*: Yes, and extend the pattern to PgVector.
- [x] Should DB column be renamed or moved to JSONB? — *Owner: Jesus*: Move to JSONB `embedding_model`, deprecate standalone columns.
