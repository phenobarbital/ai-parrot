# Per-Loop LLM Client Cache

**Audience**: Engineers writing a new `AbstractClient` subclass or debugging
cross-loop runtime errors in production.

**Related files**:

- `packages/ai-parrot/src/parrot/clients/base.py` — base implementation
- `packages/ai-parrot/src/parrot/clients/google/client.py` — model-class invalidation example
- `packages/ai-parrot/src/parrot/clients/grok.py` — minimal subclass example
- `packages/ai-parrot/src/parrot/clients/live.py` — GeminiLiveClient caveat
- `sdd/specs/per-loop-llm-client-cache.spec.md` — full design rationale

---

## Why This Exists

Most LLM provider SDKs maintain an internal HTTP session (e.g. `aiohttp.ClientSession`
or `httpx.AsyncClient`) that is bound to the event loop it was created on. When an
`AbstractClient` wrapper is reused from a background task running on a **different** loop
(e.g. `navigator.background.coroutine_in_thread` spins up a new loop in a thread), the
SDK call fails with:

```
RuntimeError: got Future attached to a different loop
```

The pattern looks like this in production code:

```
┌─ main loop (FastAPI/aiohttp) ─────────────────────┐
│  wrapper = GoogleGenAIClient()                     │
│  wrapper.client  ← aiohttp session on Loop A       │
└────────────────────────────────────────────────────┘
                │
                │  coroutine_in_thread(handler.run_job())
                ▼
┌─ background loop (fresh thread) ──────────────────┐
│  await wrapper.ask(...)                            │
│       └─ wrapper.client still bound to Loop A !!  │
│          RuntimeError: Future attached to wrong    │
│          loop                                      │
└────────────────────────────────────────────────────┘
```

The per-loop cache solves this by maintaining a **separate SDK client for each event
loop** that uses the wrapper, with no sharing across loops.

---

## How It Works

### Data structures

```python
# Inside AbstractClient (packages/ai-parrot/src/parrot/clients/base.py)

@dataclass
class _LoopClientEntry:
    client: Any                               # the SDK client instance
    loop_ref: ReferenceType                   # weakref to the event loop
    metadata: dict                            # subclass-specific state

class AbstractClient(ABC):
    def __init__(self, ...):
        self._clients_by_loop: dict[int, _LoopClientEntry] = {}
        self._locks_by_loop: dict[int, asyncio.Lock] = {}
```

- **Key**: `id(asyncio.get_running_loop())` — unique integer per live loop.
- **Value**: `_LoopClientEntry` with the SDK client and a weakref to the loop so
  dead loops can be detected without preventing garbage collection.
- **Lock**: one `asyncio.Lock` per loop (locks are loop-bound; sharing one across
  loops would deadlock).

### Cache-miss flow

```
_ensure_client(**hints)
  │
  ├─ get running loop ID
  ├─ acquire per-loop asyncio.Lock
  ├─ lookup entry in _clients_by_loop
  │
  ├─ [hit] _client_invalid_for_current(entry.client, **hints)?
  │    ├─ False → return entry.client  (no logging, hot path)
  │    └─ True  → fall through to build
  │
  └─ [miss or invalid]
       ├─ log INFO: "Per-loop cache miss: building new SDK client for loop <id>"
       ├─ await get_client(**_filter_get_client_hints(**hints))
       ├─ store new _LoopClientEntry in _clients_by_loop
       └─ return new client
```

### client property

The `client` attribute is a `@property`:

```python
@property
def client(self) -> Optional[Any]:
    loop = self._get_current_loop()
    if loop is None:
        return None
    entry = self._clients_by_loop.get(id(loop))
    return entry.client if entry else None
```

It returns the current-loop's cached SDK client or `None` if no client has been
built yet for this loop. Assigning `self.client = <non-None>` raises `AttributeError`
— subclasses must never cache on `self.client` directly.

---

## Writing a New Subclass

### Minimal example (Anthropic / OpenAI style)

```python
from parrot.clients.base import AbstractClient

class MyProviderClient(AbstractClient):
    client_type = "myprovider"
    client_name = "myprovider"

    def __init__(self, api_key: str = None, **kwargs):
        self.api_key = api_key or os.getenv("MYPROVIDER_API_KEY")
        super().__init__(**kwargs)
        # NOTE: do NOT write self.client = None here — the base property handles it.

    async def get_client(self) -> MyAsyncSDK:
        """Return a FRESH SDK client on every call.

        The base _ensure_client() caches this result per loop; get_client()
        must NOT do any caching itself.
        """
        return MyAsyncSDK(api_key=self.api_key)

    async def ask(self, prompt: str, **kwargs):
        await self._ensure_client()   # ensures current-loop entry exists
        return await self.client.chat.complete(prompt=prompt, **kwargs)
```

### Rules for subclasses

| Rule | Explanation |
|---|---|
| **MUST** implement `async def get_client(self)` that returns a **fresh** SDK client | The base cache calls `get_client()` on a miss; it must never cache internally. |
| **MUST NOT** write `self.client = ...` (except `None`) | The property setter raises `AttributeError` for non-`None` values. |
| **SHOULD** call `await self._ensure_client()` at the top of public methods | Replaces the old `if not self.client: raise RuntimeError(...)` guard. |
| **SHOULD** override `_client_invalid_for_current()` only when caching metadata matters | Only needed if the same loop might need a different SDK client (e.g. different model endpoint). |
| **MAY** override `_filter_get_client_hints(**hints)` | Select which hint kwargs reach `get_client(...)`. Base implementation passes nothing. |

---

## With Invalidation Hints (Google-style)

`GoogleGenAIClient` builds different `genai.Client` instances for different model
families (Gemini 2.x vs 3.x). The pattern:

### Step 1 — override `_client_invalid_for_current`

```python
def _client_invalid_for_current(self, client: Any, **hints: Any) -> bool:
    """Return True when the cached client was built for a different model class."""
    model = hints.get("model") or self.model or self._default_model
    if isinstance(model, GoogleModel):
        model = model.value
    desired = self._model_class_key(model)

    loop = self._get_current_loop()
    if loop is None:
        return False
    entry = self._clients_by_loop.get(id(loop))
    if entry is None:
        return True                               # no entry yet → rebuild
    cached = entry.metadata.get("model_class")
    return cached is not None and cached != desired
```

### Step 2 — override `_ensure_client` as a thin wrapper to stamp metadata

```python
async def _ensure_client(self, model: str = None, **hints: Any) -> genai.Client:
    if model is not None:
        hints["model"] = model
    client = await super()._ensure_client(**hints)   # base does the caching
    # Stamp model-class on the entry so the hook has state on the next call.
    loop = asyncio.get_running_loop()
    entry = self._clients_by_loop.get(id(loop))
    if entry is not None:
        resolved = hints.get("model") or self.model or self._default_model
        if isinstance(resolved, GoogleModel):
            resolved = resolved.value
        entry.metadata["model_class"] = self._model_class_key(resolved)
    return client
```

### Step 3 — override `_filter_get_client_hints`

```python
def _filter_get_client_hints(self, **hints: Any) -> dict:
    return {"model": hints["model"]} if "model" in hints else {}
```

> **Key insight**: The metadata is stored in `_LoopClientEntry.metadata`, not on
> `self`. Each loop's entry has independent metadata, so a model-class change on
> Loop A does not invalidate Loop B's client.

---

## Error Recovery Mid-Request

When a network error forces a mid-request client reset (e.g. aiohttp connection
drops), use `_close_current_loop_entry()`, **never** `close()` or `close_all()`:

```python
# WRONG — evicts ALL loops' healthy clients:
await self.close()
await self._ensure_client(model=current_model)

# CORRECT — evicts only the current loop's broken entry:
await self._close_current_loop_entry()
await self._ensure_client(model=current_model)
```

`close()` and `close_all()` tear down every loop's entry. During a mid-request
recovery on one loop, you do not want to discard healthy clients on sibling loops
that are still serving concurrent requests.

---

## GeminiLiveClient Caveat

`GeminiLiveClient` uses the per-loop cache for its setup `genai.Client` (safe), but
the **LiveConnect WebSocket session** is opened inside a specific `async with` body
and cannot be migrated to a different loop.

Rules:
- Always open a LiveConnect session and consume its stream on a single loop.
- Do NOT attempt to resume a Live session from a background task running on a fresh
  loop — start a new session instead.
- See `packages/ai-parrot/src/parrot/clients/live.py` → `GeminiLiveClient` class
  docstring ("Cross-loop reuse" section) for the authoritative statement.

---

## Verifying No Leaks (Runbook)

The spec acceptance criterion requires "no aiohttp session leaks across 1,000
alternating calls". This is a manual verification step, not a CI test.

### Procedure

1. Write a harness that alternates `_ensure_client()` between Loop A and Loop B 500
   times each (1,000 total) while tracking memory:

   ```python
   import tracemalloc, asyncio, gc
   from parrot.clients.claude import AnthropicClient   # or any subclass

   tracemalloc.start()
   client = AnthropicClient()

   loop_a = asyncio.new_event_loop()
   loop_b = asyncio.new_event_loop()

   for i in range(500):
       loop_a.run_until_complete(client._ensure_client())
       loop_b.run_until_complete(client._ensure_client())

   gc.collect()
   snapshot = tracemalloc.take_snapshot()
   stats = snapshot.statistics("lineno")
   for stat in stats[:10]:
       print(stat)

   # Assert only 2 entries remain:
   assert len(client._clients_by_loop) == 2
   loop_a.close(); loop_b.close()
   ```

2. Verify that `tracemalloc` shows flat (non-growing) memory. A growing count in
   `_clients_by_loop` would indicate the dead-loop cleanup is not firing.

3. Check `len(client._clients_by_loop)` never exceeds 2 at steady state.

---

## Known Limitations

### Foreign-loop clients are not `close()`-d

When `close()` or `close_all()` is called from Loop A, entries belonging to Loop B
**cannot** have `await client.close()` called on them — you cannot `await` a coroutine
on a foreign loop without re-entering it. Those SDK clients are dropped (their reference
removed from the dict) without an explicit async close.

**Practical impact**: The underlying connection pool held by the SDK
(e.g. `aiohttp.ClientSession`, `httpx.AsyncClient`) is abandoned without teardown.
The OS will reclaim file descriptors and sockets on process exit. During the
process lifetime the resources remain allocated until the loop itself is GC'd
and Python finalises the objects.

**Mitigation**: For long-running processes that spawn many short-lived background
loops, the automatic dead-entry sweep in `_ensure_client()` (triggered on each
build) keeps `_clients_by_loop` from growing unbounded. SDK clients for dead
loops are dropped at sweep time; their connection pools are released when their
reference count reaches zero.

### Loop-id recycling

CPython may reuse `id(loop)` for a new loop after an old one is garbage-collected.
`_ensure_client()` detects this by checking `entry.loop_ref()` (the weakref to the
original loop) before reusing a cached entry. If the weakref is dead, the entry
**and its lock** are evicted and a fresh client is built for the new loop, preventing
a stale session from being handed to the wrong caller.

---

## Related

| Resource | Description |
|---|---|
| `packages/ai-parrot/src/parrot/clients/base.py` | `AbstractClient`, `_LoopClientEntry`, `_ensure_client` |
| `packages/ai-parrot/src/parrot/clients/google/client.py` | Model-class invalidation hook example |
| `packages/ai-parrot/src/parrot/clients/grok.py` | Minimal subclass (no invalidation) |
| `packages/ai-parrot/src/parrot/clients/live.py` | LiveConnect cross-loop caveat |
| `packages/ai-parrot/tests/test_per_loop_cache.py` | Unit tests (11 offline) |
| `packages/ai-parrot/tests/test_per_loop_cache_integration.py` | Integration tests |
| `sdd/specs/per-loop-llm-client-cache.spec.md` | Full design rationale and decision log |
