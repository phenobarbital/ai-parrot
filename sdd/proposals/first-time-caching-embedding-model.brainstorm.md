# Brainstorm: First-Time Caching Embedding Model

**Date**: 2026-03-20
**Author**: Claude (SDD Brainstorm)
**Status**: exploration
**Recommended Option**: Option B

---

## Problem Statement

Embedding models in AI-Parrot are **re-created on each access** rather than being properly cached after first load. This wastes GPU/CPU resources and adds latency:

1. **Per-bot duplication**: Each bot that uses the same embedding model (e.g., `all-MiniLM-L12-v2`) creates its own instance, consuming redundant GPU memory.
2. **KnowledgeBaseStore eager loading**: `KnowledgeBaseStore.__init__` directly instantiates `SentenceTransformer` on construction, even if the KB is never queried.
3. **AbstractStore re-creation**: `AbstractStore.create_embedding()` creates a new `EmbeddingModel` instance every time it's called — no deduplication by model name.
4. **No shared cache**: There is no process-wide registry to share a loaded model across bots, stores, and KB instances.

**Who is affected:**
- **Developers**: Pay unexpected latency on first requests; hard to reason about which models are loaded.
- **Ops**: GPU memory grows linearly with bot count, even when all bots use the same model.
- **End users**: First query latency can be 5-30s depending on model size and device.

## Constraints & Requirements

- Must be **backwards-compatible**: existing `warmup_on_configure` and lazy `@property` patterns continue to work.
- Must support **async initialization** without blocking the event loop.
- Cache key must be `(model_name, model_type)` — same model shared, different models coexist.
- Must include **LRU eviction** for GPU memory management.
- Must work as a **standalone utility** (`from parrot.embeddings import EmbeddingRegistry`).
- Must handle **concurrent first-access** safely (multiple bots requesting the same model simultaneously).
- All embedding consumers (vector stores, KB stores, bots) must go through the registry.
- Queue-and-wait semantics: first request waits for model load, subsequent requests are instant.

---

## Options Explored

### Option A: Simple Module-Level Cache Dict

Add a module-level `_cache: Dict[str, EmbeddingModel] = {}` in `parrot/embeddings/__init__.py` with a `get_or_create(model_name, model_type)` function. Each call checks the cache before instantiation.

**Pros:**
- Minimal code change — add ~30 lines to `__init__.py`
- No new classes or abstractions
- Easy to understand and debug

**Cons:**
- No LRU eviction (cache grows unbounded)
- No async-safe initialization (race conditions on concurrent first access)
- No preload API — can't eagerly warm models at startup
- Hard to add features later (metrics, memory tracking, unload)
- No integration with bot lifecycle (warmup_on_configure can't leverage it cleanly)

**Effort:** Low

**Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| (none) | Pure Python dict | No new dependencies |

**Existing Code to Reuse:**
- `parrot/embeddings/__init__.py` — extend with cache dict
- `parrot/embeddings/base.py` — `EmbeddingModel` instances stored in cache

---

### Option B: EmbeddingRegistry Singleton with Async Loading and LRU Eviction

Create a dedicated `EmbeddingRegistry` class (singleton pattern) that manages the full lifecycle of embedding models: creation, caching by `(model_name, model_type)`, async initialization, LRU eviction, and explicit preload/unload APIs.

The registry uses an `asyncio.Lock` per model key to ensure only one coroutine loads a given model, while others await the same future. An internal `OrderedDict` tracks access order for LRU eviction. A configurable `max_models` threshold triggers eviction of the least-recently-used model when exceeded.

**Pros:**
- Process-wide singleton — all bots, stores, and KBs share models automatically
- Async-safe with per-key locking (no duplicate loads under concurrency)
- LRU eviction with configurable max_models threshold
- Explicit `preload()` and `unload()` APIs for operational control
- Clean integration point: `AbstractStore.create_embedding()` and `KnowledgeBaseStore.__init__` delegate to registry
- Standalone utility — usable outside bot lifecycle
- Metrics-ready (load count, cache hits, eviction count)

**Cons:**
- Medium complexity — new class with ~150-200 lines
- Singleton pattern requires care in testing (need reset/clear for test isolation)
- LRU eviction may surprise users if a model is evicted mid-conversation (mitigated by reasonable defaults)

**Effort:** Medium

**Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `asyncio` | Per-key locks, async loading | stdlib |
| `collections.OrderedDict` | LRU access tracking | stdlib |
| `threading.Lock` | Sync fallback for non-async contexts | stdlib |
| `torch` | GPU memory cleanup on eviction | existing dep |

**Existing Code to Reuse:**
- `parrot/embeddings/base.py` — `EmbeddingModel` base class (instances managed by registry)
- `parrot/embeddings/__init__.py` — `supported_embeddings` dict for model class resolution
- `parrot/stores/abstract.py:create_embedding()` — refactor to call registry instead of direct instantiation
- `parrot/stores/kb/store.py` — refactor to use registry for SentenceTransformer
- `parrot/bots/abstract.py:warmup_embeddings()` — simplify to call `registry.preload()`

---

### Option C: WeakRef Cache with Garbage Collection

Use `weakref.WeakValueDictionary` to cache embedding model instances. Models stay cached as long as at least one bot holds a reference; when all bots are garbage-collected, the model is freed automatically.

**Pros:**
- Automatic memory management — no explicit eviction logic
- Simple implementation (~50 lines)
- Models naturally freed when no longer referenced

**Cons:**
- No explicit preload/unload API (models only exist while referenced)
- WeakRef doesn't work with all object types (may need wrapper)
- No LRU semantics — eviction is based on reference count, not access recency
- Cannot keep a model "warm" across bot restarts without an external reference
- GPU memory not explicitly freed (depends on Python GC + torch cache)
- Unpredictable behavior — hard to reason about when models are loaded/unloaded

**Effort:** Low

**Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `weakref` | WeakValueDictionary | stdlib |

**Existing Code to Reuse:**
- `parrot/embeddings/base.py` — `EmbeddingModel` base class
- `parrot/embeddings/__init__.py` — model resolution

---

### Option D: External Cache Layer (Redis/Shared Memory)

Use an external cache (Redis, shared memory, or mmap) to store serialized model weights, allowing cross-process sharing.

**Pros:**
- Cross-process model sharing (multiple worker processes share one model)
- Survives process restarts
- Could work with model serving frameworks (Triton, TorchServe)

**Cons:**
- Massive complexity — serialization, IPC, consistency
- High latency for deserialization on each access (defeats the purpose)
- Overkill for single-process async framework
- External dependency (Redis) for a core feature
- SentenceTransformer models don't serialize efficiently to Redis

**Effort:** High

**Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `redis` | External cache | existing dep, but overkill here |
| `torch.save/load` | Model serialization | complex for transformers |

**Existing Code to Reuse:**
- (minimal — this is a fundamentally different architecture)

---

## Recommendation

**Option B** (EmbeddingRegistry Singleton) is recommended because:

1. **Meets all requirements**: async-safe, LRU eviction, standalone utility, preload API — all from the constraints.
2. **Right level of complexity**: Option A is too simple (no eviction, no async safety), Option D is overkill. Option C's WeakRef semantics are unpredictable and don't support preload.
3. **Clean integration**: `AbstractStore.create_embedding()` and `KnowledgeBaseStore` can delegate to the registry with minimal refactoring — the registry handles deduplication transparently.
4. **Operational control**: The `preload()` and `unload()` APIs give ops teams explicit control over GPU memory, while the LRU eviction provides a safety net.
5. **Testing**: A `clear()` method enables test isolation without global state leakage.

**Tradeoff accepted**: The singleton pattern adds ~150 lines of new code, but it's self-contained in one module and simplifies all consumers (stores, KBs, bots).

---

## Feature Description

### User-Facing Behavior

**For developers:**
```python
from parrot.embeddings import EmbeddingRegistry

# Explicit preload at app startup (optional)
registry = EmbeddingRegistry.instance()
await registry.preload([
    {'model_name': 'all-MiniLM-L12-v2', 'model_type': 'huggingface'},
    {'model_name': 'text-embedding-3-small', 'model_type': 'openai'},
])

# Bots transparently share models — no code change needed
bot1 = MyChatbot(embedding_model={'model_name': 'all-MiniLM-L12-v2', 'model_type': 'huggingface'})
bot2 = MyAgent(embedding_model={'model_name': 'all-MiniLM-L12-v2', 'model_type': 'huggingface'})
# bot1 and bot2 share the SAME model instance in memory

# Explicit unload when needed
await registry.unload('all-MiniLM-L12-v2', 'huggingface')

# Check loaded models
print(registry.loaded_models())  # [('all-MiniLM-L12-v2', 'huggingface'), ...]
```

**For end users:** First query latency is paid once per model per process lifetime. Subsequent queries (even from different bots) are instant.

### Internal Behavior

1. **Registry singleton** (`EmbeddingRegistry`) holds an `OrderedDict[Tuple[str, str], EmbeddingModel]` keyed by `(model_name, model_type)`.
2. **`get_or_create(model_name, model_type, **kwargs)`**: The core method.
   - If model is in cache: move to end of OrderedDict (LRU touch), return it.
   - If not in cache: acquire per-key `asyncio.Lock`, create model via `_create_embedding()`, store in cache.
   - If cache exceeds `max_models`: evict LRU entry, call `model.free()` to release GPU memory.
3. **`preload(models)`**: Async method that calls `get_or_create()` for each model config, loading them into cache eagerly.
4. **`unload(model_name, model_type)`**: Remove from cache, call `model.free()`.
5. **Integration points**:
   - `AbstractStore.create_embedding()` → calls `registry.get_or_create()` instead of direct instantiation.
   - `KnowledgeBaseStore.__init__` → calls `registry.get_or_create()` instead of `SentenceTransformer(...)`.
   - `AbstractBot.warmup_embeddings()` → simplified to call `registry.preload()`.
6. **Sync fallback**: A `get_or_create_sync()` method for non-async contexts (e.g., `@property model` in `EmbeddingModel`).

### Edge Cases & Error Handling

- **Concurrent first-access**: Per-key `asyncio.Lock` ensures only one coroutine loads a model; others await the same result.
- **Model load failure**: Exception propagates to caller. Failed models are NOT cached (retry on next access).
- **LRU eviction during active use**: The evicted model object is only dereferenced from the registry — if a bot still holds a reference, it continues working. Next registry access re-creates it.
- **Process restart**: Cache is in-memory only — models reload on first access after restart. Use `preload()` in app startup for production.
- **Test isolation**: `registry.clear()` resets all cached models. Use in test fixtures.
- **Mixed sync/async**: The `model` property on `EmbeddingModel` uses sync `get_or_create_sync()` with a `threading.Lock`; async paths use `get_or_create()` with `asyncio.Lock`.

---

## Capabilities

### New Capabilities
- `embedding-registry`: Process-wide singleton registry for embedding model caching with LRU eviction
- `embedding-preload-api`: Explicit async preload and unload APIs for operational control

### Modified Capabilities
- `bot-configure`: `warmup_embeddings()` simplified to delegate to registry
- `vector-store-embedding`: `AbstractStore.create_embedding()` delegates to registry
- `kb-store-embedding`: `KnowledgeBaseStore` uses registry instead of direct SentenceTransformer

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `parrot/embeddings/base.py` | modifies | Add registry-aware `model` property |
| `parrot/embeddings/__init__.py` | extends | Export `EmbeddingRegistry` |
| `parrot/embeddings/registry.py` | **new file** | The registry singleton |
| `parrot/stores/abstract.py` | modifies | `create_embedding()` uses registry |
| `parrot/stores/kb/store.py` | modifies | `__init__` uses registry for SentenceTransformer |
| `parrot/bots/abstract.py` | modifies | `warmup_embeddings()` simplified |
| `parrot/conf.py` | extends | Add `EMBEDDING_REGISTRY_MAX_MODELS` config |
| `tests/` | extends | New tests for registry, eviction, concurrency |

---

## Parallelism Assessment

- **Internal parallelism**: Tasks can be split — registry implementation is independent from consumer refactoring (stores, KB, bots).
- **Cross-feature independence**: No conflicts with in-flight specs. Changes to `abstract.py` are additive.
- **Recommended isolation**: `per-spec` — tasks are sequential (registry must exist before consumers can be refactored).
- **Rationale**: The registry is the foundation; consumer refactoring depends on it. Sequential in one worktree is cleaner.

---

## Open Questions

- [ ] What should `max_models` default to? Suggest 5 for typical deployments. — *Owner: team*: Yes, 10 is a good number.
- [ ] Should eviction log a warning so ops can tune `max_models`? — *Owner: team*: Yes, it should log a warning when a model is evicted.
- [ ] Should the registry track GPU memory usage (via `torch.cuda.memory_allocated`) for smarter eviction, or just count models? — *Owner: team*: Yes, it should track GPU memory usage.
