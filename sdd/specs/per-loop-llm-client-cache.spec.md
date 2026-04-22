# Feature Specification: Per-Loop LLM Client Cache

**Feature ID**: FEAT-112
**Date**: 2026-04-21
**Author**: Jesus Lara
**Status**: approved
**Target version**: TBD

---

## 1. Motivation & Business Requirements

### Problem Statement

Every `AbstractClient` subclass caches a single SDK client instance on
`self.client` for the lifetime of the wrapper (see `packages/ai-parrot/src/parrot/clients/base.py:254`
and `base.py:346-353`). The SDK clients we wrap (`google.genai.Client`,
`anthropic.AsyncAnthropic`, `openai.AsyncOpenAI`, `groq.AsyncGroq`, `xai_sdk.AsyncClient`,
etc.) all lazily open an aiohttp or httpx session under the hood, and that
session binds to **whichever event loop was running the first time it was
used** (e.g. `google.genai._api_client._aiohttp_session`).

When agents are invoked from `navigator.background.BackgroundService` jobs, the
task runs in a fresh thread with its own event loop (see
`navigator/background/wrappers/__init__.py:15-47`, `coroutine_in_thread`). If
the agent is reused from that background loop, the SDK client's session — still
bound to the app-startup loop — raises:

```
RuntimeError: got Future <...> attached to a different loop
```

Concrete incident: the NextStop agent (declared in `resources/nextstop/handler.py`)
is created once at app startup via `AgentHandler._create_agent`
(`packages/ai-parrot/src/parrot/handlers/agents/abstract.py:785`). Every REST
call that goes through `register_background_task` runs `_team_performance`
on a foreign loop and intermittently fails at `chat.send_message()`.

An interim fix (loop-aware invalidation inside `GoogleGenAIClient`) landed on
`dev` in the course of debugging this: `_ensure_client` rebuilds the client
whenever the running loop differs from the cached one. It fixes the error but
throws away connection reuse every time a background task fires, because
invalidation is *destructive* — a future call back on the main loop has to
rebuild the client again.

### Goals

- Replace the "single SDK client per wrapper" cache with a **per-loop dict**
  keyed by `id(asyncio.get_running_loop())`, applied uniformly at the
  `AbstractClient` base level so every subclass benefits without per-subclass
  edits.
- Preserve connection reuse **within** each loop: two `ask()` calls that run on
  the same loop must share the same underlying SDK client, session, and
  connection pool.
- Make cross-loop reuse structurally impossible: callers from Loop B never
  touch a client that was built on Loop A.
- Safe cleanup: `close()` must close only the clients whose owning loop is
  still alive/current; clients belonging to dead or foreign loops are dropped
  (reference-only) without attempting an `await session.close()` that would
  re-trigger the same cross-loop Future binding.
- Roll back the interim `GoogleGenAIClient._ensure_client` loop-invalidation
  hack once the base-class mechanism is in place, keeping only the
  model-class invalidation (Gemini 2.x vs 3.x vs preview) as a subclass
  extension point.

### Non-Goals (explicitly out of scope)

- **Per-call client creation.** This spec deliberately keeps clients long-lived
  within a loop to avoid TLS-handshake cost on every `ask()`.
- **Changes to `navigator.background.BackgroundService` or `coroutine_in_thread`.**
  We fix the parrot side; navigator's thread-per-job model is taken as given.
- **Per-request agent creation in resource handlers.** Handlers keep caching
  agents at `app.on_startup` time; the fix is inside the client layer.
- **GeminiLiveClient cross-loop audio session migration.** The WebSocket
  session in `GeminiLiveClient` is explicitly per-interaction; this spec
  records the constraint but does not introduce cross-loop WebSocket handoff.
- **Thread-safety of `ToolManager`, `ConversationMemory`, or other non-client
  state.** Only the SDK client cache is restructured.
- **Compile-time removal of `self.client`.** We keep `self.client` as a
  convenience alias for "the client bound to the current loop" to avoid
  breaking direct-attribute access in consumers; see Codebase Contract.

---

## 2. Architectural Design

### Overview

Add a `_clients_by_loop: dict[int, Any]` attribute to `AbstractClient` and a
single async `_ensure_client()` entry point at the base class. Every call site
that currently reads `self.client` goes through `_ensure_client()`, which:

1. Computes `loop_id = id(asyncio.get_running_loop())`.
2. Returns the cached client for that loop if present and still valid.
3. Otherwise builds a fresh client via `get_client()` (subclass responsibility),
   records it under `loop_id`, and returns it.
4. Updates `self.client` to point at the per-loop client, so legacy code that
   reads `self.client` directly still observes "the client for the loop I'm
   running on" without regression.

Subclasses that need additional invalidation logic (e.g. `GoogleGenAIClient`
rebuilding across Gemini model-class boundaries) override a narrow
`_client_invalid_for_current(client, **hints)` hook rather than reimplementing
the whole cache.

`close()` is rewritten to iterate the dict, closing only entries whose
recorded loop is still alive and reachable, and dropping references for the
rest. Iteration order is oldest-first to mimic the current single-instance
semantics for the common single-loop case.

### Component Diagram

```
AbstractClient
  ├── _clients_by_loop: dict[int, Any]           (NEW)
  ├── _loop_meta: dict[int, weakref|ref to loop] (NEW, for liveness checks)
  ├── _ensure_client()                            (NEW, base impl)
  ├── _client_invalid_for_current()               (NEW, subclass hook, default False)
  ├── get_client()                                (EXISTING, abstract)
  ├── close()                                     (EXISTING, rewritten)
  └── self.client                                 (EXISTING, becomes "loop-local view")
        ▲
        │  subclasses
        ├── GoogleGenAIClient  — overrides _client_invalid_for_current for model_class
        ├── AnthropicClient    — no override needed
        ├── OpenAIClient       — no override needed
        ├── GroqClient         — no override needed
        ├── GrokClient         — deletes its own self.client cache in get_client
        ├── OpenRouterClient   — inherits from OpenAIClient, no work
        ├── LocalLLMClient     — inherits from OpenAIClient, no work
        ├── vLLMClient         — inherits from LocalLLMClient, no work
        ├── TransformersClient — N/A, no SDK HTTP session
        ├── Gemma4Client       — N/A, no SDK HTTP session
        └── GeminiLiveClient   — WebSocket-based; uses the hook to pin to one loop
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `AbstractClient` (`clients/base.py`) | modifies | Adds `_clients_by_loop`, `_ensure_client`, rewrites `close()` and `__aenter__` |
| `GoogleGenAIClient` (`clients/google/client.py`) | simplifies | Removes `_client_loop_id`, `_current_loop_id`, interim `_ensure_client`. Overrides hook for model-class invalidation only. |
| `AnthropicClient` (`clients/claude.py`) | adopts | No subclass work; base handles everything |
| `OpenAIClient` (`clients/gpt.py`) | adopts | No subclass work |
| `GroqClient` (`clients/groq.py`) | adopts | No subclass work |
| `GrokClient` (`clients/grok.py`) | refactors | `get_client` currently writes `self.client` itself — remove that and return the freshly-built `AsyncClient`; let base cache it |
| `OpenRouterClient` / `LocalLLMClient` / `vLLMClient` | inherits | Via `OpenAIClient`, no direct change |
| `GeminiLiveClient` (`clients/live.py`) | adopts with caveat | WebSocket session cannot be migrated across loops; document and keep |
| `LLMFactory` (`clients/factory.py`) | unchanged | Factory builds wrappers; the per-loop cache lives on each wrapper instance |
| `AgentHandler._create_agent` (`handlers/agents/abstract.py:785`) | unchanged | Still caches one agent per app; each agent's wrapper now transparently handles N loops |
| `BackgroundService` / `TaskWrapper` (`navigator/background/...`) | unchanged | External framework, not touched |

### Data Models

```python
# parrot/clients/base.py (new module-level helper)

import asyncio
from dataclasses import dataclass
from typing import Any, Optional
from weakref import ref as weak_ref, ReferenceType

@dataclass
class _LoopClientEntry:
    """One (loop -> SDK client) binding inside AbstractClient's cache.

    ``loop_ref`` is a weakref so the cache does not keep dead loops alive.
    When the weakref returns None, the entry is stale and must be dropped
    without calling ``await client.close()`` (the close would schedule on
    the dead loop and fail).
    """
    client: Any
    loop_ref: ReferenceType  # weakref to the AbstractEventLoop that owns `client`
    # Subclasses may stash extra invalidation hints, e.g. the Gemini
    # "model class" (stable/preview/gemini3) the cached client was built for.
    metadata: dict
```

### New Public Interfaces

```python
# parrot/clients/base.py

class AbstractClient(ABC):

    def __init__(self, ...):
        ...
        # Replaces the current `self.client: Any = None`.
        # `self.client` stays as a property that returns the loop-local client
        # (or None if _ensure_client has not yet run on this loop).
        self._clients_by_loop: dict[int, _LoopClientEntry] = {}
        self._client_lock = asyncio.Lock()  # guards dict mutations per wrapper

    @property
    def client(self) -> Optional[Any]:  # backwards-compat getter
        """The SDK client bound to the *currently running* event loop.

        Returns None when no client has been built on this loop yet. Callers
        that need one should use ``_ensure_client()`` instead.
        """
        loop_id = self._current_loop_id()
        entry = self._clients_by_loop.get(loop_id) if loop_id is not None else None
        return entry.client if entry else None

    @client.setter
    def client(self, value: Optional[Any]) -> None:
        """Back-compat setter — allowed only in __init__ for value=None.

        Subclasses that historically assigned ``self.client = X`` directly
        must migrate to returning X from ``get_client()``. A deprecation
        warning is emitted for non-None direct assignments.
        """
        ...

    async def _ensure_client(self, **hints: Any) -> Any:
        """Return an SDK client valid for the current event loop.

        Builds a new client via ``get_client()`` when the loop has no entry,
        or when ``_client_invalid_for_current(entry.client, **hints)``
        returns True.

        Thread-safe across concurrent coroutines on the same loop via
        ``self._client_lock``. Not thread-safe across loops on purpose —
        each loop has its own entry, so there is no shared state to race on.
        """

    def _client_invalid_for_current(
        self,
        client: Any,
        **hints: Any,
    ) -> bool:
        """Subclass hook: return True to force a rebuild of the cached
        client for the current loop.

        Default implementation returns False. ``GoogleGenAIClient``
        overrides it to detect Gemini model-class changes.
        """
        return False

    async def close(self) -> None:
        """Close all per-loop clients that can still be safely closed.

        For each entry:
          - If the owning loop is the current loop AND still running,
            ``await entry.client.close()`` (when the SDK supports it).
          - Otherwise, drop the reference without awaiting; the GC
            reclaims the session handle when the owning loop dies.
        """
```

---

## 3. Module Breakdown

### Module 1: `AbstractClient` base — per-loop cache
- **Path**: `packages/ai-parrot/src/parrot/clients/base.py`
- **Responsibility**:
  - Introduce `_clients_by_loop`, `_client_lock`, the `client` property/setter,
    `_ensure_client()`, the `_client_invalid_for_current()` hook.
  - Rewrite `__aenter__` to delegate to `_ensure_client()` (keep `self.session`
    handling for `use_session=True` flows).
  - Rewrite `close()` to iterate the cache and safely tear down or drop
    each entry.
  - Keep the existing `get_client()` abstract signature unchanged.
- **Depends on**: nothing (leaf change).

### Module 2: `GoogleGenAIClient` simplification
- **Path**: `packages/ai-parrot/src/parrot/clients/google/client.py`
- **Responsibility**:
  - Remove the interim loop-awareness hack: delete `_client_loop_id`,
    `_current_loop_id()`, the current `_ensure_client()` override, and the
    loop-check branch inside `get_client()` / `close()`.
  - Keep `_client_model_class` tracking but migrate it to the new
    `_client_invalid_for_current(client, model=...)` hook, storing the
    cached model class in `_LoopClientEntry.metadata`.
  - Update every call site currently doing `await self._ensure_client(model=...)`
    to pass `model` as a hint; they otherwise behave the same.
- **Depends on**: Module 1.

### Module 3: Cache-aware subclass refactor (homogenization)
- **Path**:
  - `packages/ai-parrot/src/parrot/clients/claude.py`
  - `packages/ai-parrot/src/parrot/clients/gpt.py`
  - `packages/ai-parrot/src/parrot/clients/groq.py`
  - `packages/ai-parrot/src/parrot/clients/grok.py`
  - `packages/ai-parrot/src/parrot/clients/openrouter.py` (verify, likely zero changes)
  - `packages/ai-parrot/src/parrot/clients/localllm.py`
  - `packages/ai-parrot/src/parrot/clients/vllm.py`
- **Responsibility**:
  - Audit every `self.client = ...` write outside `__init__`; replace with
    `return <client>` in `get_client()`.
  - Ensure all `RuntimeError("Client not initialized. Use async context manager.")`
    call sites still fire correctly when `_ensure_client` has not been called
    (i.e. the property returns None). Decide whether to keep that guard or
    have `ask()` call `await self._ensure_client()` itself.
  - For `GrokClient.get_client` (which currently caches on `self.client`),
    strip the caching — base handles it.
- **Depends on**: Module 1.

### Module 4: `GeminiLiveClient` audit
- **Path**: `packages/ai-parrot/src/parrot/clients/live.py`
- **Responsibility**:
  - Verify that the live-voice flow is always entered and used on a single
    loop (it is, per the WebSocket session model in `GeminiLiveClient`).
  - Document in a module docstring that `GeminiLiveClient` is **not**
    designed for cross-loop reuse; the base cache still works because all
    calls happen on the entering loop, but `close()` must run on that same
    loop.
  - No structural change beyond adopting the base cache (falls out
    automatically from Module 1).
- **Depends on**: Module 1.

### Module 5: Tests
- **Path**: `packages/ai-parrot/tests/clients/test_per_loop_cache.py` (new)
- **Responsibility**:
  - Unit tests for `AbstractClient._ensure_client()` across same-loop and
    cross-loop scenarios, using a stub subclass that counts `get_client()`
    calls.
  - Unit tests for `close()` semantics: closed on live current loop, dropped
    on dead foreign loop.
  - Integration test that mimics `navigator.background.coroutine_in_thread`
    by spawning a secondary loop in a worker thread and invoking
    `_ensure_client()` from both loops; asserts two distinct clients are
    returned and neither call raises.
  - Regression test for `GoogleGenAIClient`: model-class change forces
    rebuild **within the same loop**, but loop change alone no longer
    invalidates the entry for the *other* loop.
- **Depends on**: Modules 1, 2, 3.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_same_loop_reuses_client` | Module 1 | Two `_ensure_client()` calls on the same loop return the same object. `get_client()` invoked exactly once. |
| `test_different_loop_builds_new_client` | Module 1 | `_ensure_client()` on Loop A returns client X; on Loop B returns client Y ≠ X. `get_client()` invoked twice. |
| `test_invalidation_hook_forces_rebuild` | Module 1 | Subclass hook returning True rebuilds the client for the current loop only; other loops unaffected. |
| `test_close_on_current_loop_awaits_sdk_close` | Module 1 | When the current loop owns the entry, `close()` calls the SDK client's `.close()`. |
| `test_close_on_dead_loop_drops_silently` | Module 1 | Entry whose loop has been GC'd (weakref is None) is removed without calling `.close()`. |
| `test_client_property_returns_none_before_ensure` | Module 1 | `wrapper.client` is None on a loop that has never called `_ensure_client()`. |
| `test_client_setter_rejects_non_none` | Module 1 | Direct `wrapper.client = X` raises `AttributeError` / warns; migrations must use `get_client()`. |
| `test_google_model_class_invalidates_entry` | Module 2 | Switching from `gemini-2.5-flash` to `gemini-3.1-pro` on the same loop rebuilds. |
| `test_google_loop_switch_does_not_invalidate_other_loop` | Module 2 | After running on Loops A and B, triggering a model-class change on Loop A does not rebuild Loop B's entry. |
| `test_grok_get_client_no_longer_self_caches` | Module 3 | `GrokClient.get_client()` returns a fresh `AsyncClient` each call; base caches it. |

### Integration Tests

| Test | Description |
|---|---|
| `test_background_task_reuses_cross_loop` | Spawns a thread-with-loop (mimic of `coroutine_in_thread`) and calls the same wrapper's `ask()` from both loops; asserts no `RuntimeError` and two distinct SDK clients. Uses stubbed SDK to avoid external calls. |
| `test_connection_reuse_within_loop` | On a single loop, issue N sequential `ask()` calls; assert the underlying aiohttp session is reused (one TCP connect, N requests). |
| `test_nextstop_background_task_end_to_end` | Live-ish smoke test: NextStopAgent configured as in production, issued via `BackgroundService`; asserts completion without cross-loop Future errors. Can be marked `@pytest.mark.integration` and skipped in CI if Google credentials absent. |

### Test Data / Fixtures

```python
# tests/clients/conftest.py

@pytest.fixture
def stub_sdk_client():
    """A minimal SDK-like object with an async close() and a build counter."""
    class _Stub:
        closed = False
        async def close(self): self.closed = True
    return _Stub

@pytest.fixture
def loop_in_thread():
    """Start a background thread running its own asyncio loop.

    Yields a callable that schedules a coroutine on that loop and
    returns its result synchronously — mirrors what
    ``navigator.background.coroutine_in_thread`` does, minus the
    callbacks, so tests can assert cross-loop semantics without
    pulling navigator as a test dep.
    """
    ...
```

---

## 5. Acceptance Criteria

- [ ] All new unit tests pass (`pytest tests/clients/test_per_loop_cache.py -v`).
- [ ] All existing client tests pass (no regressions in `tests/clients/`).
- [ ] `resources/nextstop/handler.py` end-to-end flow via `BackgroundService`
      completes without `Future attached to a different loop` across ≥10
      consecutive runs on a single process.
- [ ] `GoogleGenAIClient` no longer contains `_client_loop_id`,
      `_current_loop_id`, or the interim `_ensure_client` implementation.
- [ ] Direct attribute reads of `self.client` in existing code paths still
      work unchanged (the property preserves semantics for the currently
      running loop).
- [ ] Two concurrent loops each maintain their own connection pool; no
      measurable increase in TCP handshakes within a loop (measured via
      aiohttp session `_connector._conns` count across N sequential calls).
- [ ] No connection / aiohttp-session leaks after 1,000 alternating calls
      across two loops (verified via `tracemalloc` snapshot or
      `aiohttp.TraceConfig`).
- [ ] Documentation updated: `docs/agents/` or a new
      `docs/clients/per-loop-cache.md` explains the contract for subclass
      authors.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> Implementation agents MUST NOT reference imports, attributes, or methods
> not listed here without first verifying they exist.

### Verified Imports

```python
# Base client machinery — verified: packages/ai-parrot/src/parrot/clients/__init__.py:6
from parrot.clients import AbstractClient, LLM_PRESETS, StreamingRetryConfig

# Subclasses — verified via factory registry (clients/factory.py:3-10):
from parrot.clients.claude import AnthropicClient        # clients/claude.py:40
from parrot.clients.claude import ClaudeClient           # alias, clients/claude.py:1470
from parrot.clients.google import GoogleGenAIClient      # clients/google/__init__.py (re-export)
from parrot.clients.gpt import OpenAIClient              # clients/gpt.py:90
from parrot.clients.groq import GroqClient               # clients/groq.py:46
from parrot.clients.grok import GrokClient               # clients/grok.py:41
from parrot.clients.openrouter import OpenRouterClient   # clients/openrouter.py:23
from parrot.clients.localllm import LocalLLMClient       # clients/localllm.py:22
from parrot.clients.vllm import vLLMClient               # clients/vllm.py:35
from parrot.clients.live import GeminiLiveClient         # clients/live.py:467
from parrot.clients.hf import TransformersClient         # clients/hf.py:56
from parrot.clients.gemma4 import Gemma4Client           # clients/gemma4.py:49

# Factory — verified: clients/factory.py:36
from parrot.clients.factory import LLMFactory, SUPPORTED_CLIENTS

# stdlib
import asyncio
from weakref import ref as weak_ref, ReferenceType
```

### Existing Class Signatures

```python
# packages/ai-parrot/src/parrot/clients/base.py

class AbstractClient(ABC):
    use_session: bool = False                              # line ~235
    client_type: str                                       # line ~232 (class-var)
    client_name: str                                       # line ~233 (class-var)

    def __init__(
        self,
        conversation_memory: Optional[ConversationMemory] = None,
        preset: Optional[str] = None,
        tools: Optional[List[Union[str, AbstractTool]]] = None,
        use_tools: bool = False,
        debug: bool = True,
        tool_manager: Optional[ToolManager] = None,
        **kwargs,
    ):                                                     # line 242
        self.client: Any = None                            # line 254  (TO BE REPLACED BY PROPERTY)
        self.session: Optional[aiohttp.ClientSession] = None  # line 255
        self.use_session: bool = kwargs.get('use_session', self.use_session)  # line 256

    @abstractmethod
    async def get_client(self) -> Any:                     # line 342

    async def __aenter__(self):                            # line 346
        if self.use_session:
            self.session = aiohttp.ClientSession(headers=self.base_headers)  # line 349
        if not self.client:
            self.client = await self.get_client()          # line 353

    async def __aexit__(self, exc_type, exc_val, exc_tb):  # line 356

    async def close(self):                                 # line 469
        # Currently calls self.client.close() if it exists
```

```python
# packages/ai-parrot/src/parrot/clients/google/client.py

class GoogleGenAIClient(AbstractClient, GoogleGeneration, GoogleAnalysis):
    client_type: str = 'google'                            # line 66
    _default_model: str = 'gemini-2.5-flash'               # line 68

    # Existing state — Module 2 removes these:
    self.client: Optional[genai.Client]                    # line 94
    self._client_model_class: str                          # line 95
    self._client_loop_id: Optional[int]                    # line 99 (ADDED BY INTERIM FIX)

    def _current_loop_id(self) -> Optional[int]            # line 165 (ADDED BY INTERIM FIX)
    async def _ensure_client(self, model=None) -> genai.Client  # line ~172 (ADDED BY INTERIM FIX)
    async def get_client(self, model=None, **kwargs) -> genai.Client  # line ~210
    async def close(self)                                  # line ~290 (MODIFIED BY INTERIM FIX)

    # Method signatures that call _ensure_client (all to be adjusted when
    # _ensure_client moves to the base class with a hints-kwargs API):
    # - simple_chat loop:          client.py:1897
    # - stateful retry rebuild:    client.py:2113
    # - streaming retry rebuild:   client.py:2721
    # - image/file-upload path:    client.py:3115
    # - suspended-state resume:    client.py:3349
```

```python
# packages/ai-parrot/src/parrot/clients/claude.py

class AnthropicClient(AbstractClient):                     # line 40
    client_type: str = "anthropic"                         # line 43
    client_name: str = "claude"                            # line 44

    def __init__(self, api_key=None, base_url=..., **kwargs):  # line 50
        self.client: Optional[AsyncAnthropic] = None       # line 58

    async def get_client(self) -> AsyncAnthropic:          # line 66
        return AsyncAnthropic(api_key=self.api_key, max_retries=2)

ClaudeClient = AnthropicClient                             # line 1470 (alias)
```

```python
# packages/ai-parrot/src/parrot/clients/gpt.py

class OpenAIClient(AbstractClient):                        # line 90
    async def get_client(self) -> AsyncOpenAI:             # line 126
        return AsyncOpenAI(api_key=..., base_url=..., timeout=...)
```

```python
# packages/ai-parrot/src/parrot/clients/groq.py

class GroqClient(AbstractClient):                          # line 46
    client_type: str = "groq"                              # line 56
    async def get_client(self) -> AsyncGroq:               # line 76
        return AsyncGroq(api_key=self.api_key)
```

```python
# packages/ai-parrot/src/parrot/clients/grok.py

class GrokClient(AbstractClient):                          # line 41
    self.client: Optional[AsyncClient]                     # line 78
    async def get_client(self) -> AsyncClient:             # line 80
        # CURRENT: caches on self.client internally — Module 3 strips this
        if not self.client:
            self.client = AsyncClient(api_key=..., timeout=...)  # line 83
        return self.client

    async def close(self):                                 # line 89
        await super().close()
        self.client = None                                 # line 92 (NEEDS REMOVAL)
```

```python
# packages/ai-parrot/src/parrot/clients/live.py

class GeminiLiveClient(AbstractClient):                    # line 467
    async def get_client(self) -> genai.Client:            # line 577
        # Returns a genai.Client configured for live/voice endpoints.
        # NOTE: the downstream LiveConnect WebSocket session is per-call,
        # not reused across loops.
```

```python
# packages/ai-parrot/src/parrot/handlers/agents/abstract.py

class AgentHandler(BaseView):
    async def _create_agent(self, app: web.Application) -> BasicAgent:  # line 785
        # Creates the agent once at app.on_startup; stores in app[self.agent_id]
        # and self._agent. The wrapper's per-loop cache handles reuse from
        # background-task loops afterwards.
```

```python
# navigator/background/wrappers/__init__.py (external dependency)

def coroutine_in_thread(coro, callback=None, on_complete=None):  # line 15
    """Run a coroutine in a new thread with a new event loop.

    Every TaskWrapper runs through this, which means every
    `NextStopAgent._team_performance` call runs on a fresh loop.
    """
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `AbstractClient._ensure_client` | `get_client()` (abstract) | subclass method call | `clients/base.py:342` |
| `AbstractClient._ensure_client` | `_client_invalid_for_current` (new hook) | subclass override | — (new symbol) |
| `GoogleGenAIClient._client_invalid_for_current` | `_model_class_key()` | internal method | `clients/google/client.py:149` |
| New property `AbstractClient.client` | `_clients_by_loop[loop_id]` | dict lookup | — (new attribute) |
| `close()` rewrite | `entry.loop_ref()` liveness check | `weakref.ref` | stdlib |
| Every `await self._ensure_client(...)` call in Google client | Base class impl | super-delegation | `clients/google/client.py:1897, 2113, 2721, 3115, 3349` |

### Does NOT Exist (Anti-Hallucination)

- ~~`parrot.clients.base.ClientCache`~~ — no existing cache abstraction; this spec introduces the per-loop cache directly on `AbstractClient`.
- ~~`parrot.clients.base.AbstractClient.loop_id`~~ — not an existing attribute.
- ~~`parrot.clients.base.AbstractClient._per_loop`~~ — name reserved for future; the spec uses `_clients_by_loop`.
- ~~`asyncio.current_event_loop()`~~ — not a real API; correct spelling is `asyncio.get_running_loop()` (or the deprecated `asyncio.get_event_loop()`, which we MUST NOT use because it creates a new loop when none is running).
- ~~`navigator.background.BackgroundService.use_main_loop`~~ — no such flag; do not attempt to reconfigure navigator to avoid the thread-per-job model.
- ~~`GoogleGenAIClient.per_call_client()`~~ — not a method; the spec explicitly rejects per-call clients.
- ~~`AnthropicClient.client_pool`~~ — no pool attribute; Anthropic's `AsyncAnthropic` owns its own httpx pool internally.
- ~~`LLMFactory.create_for_loop()`~~ — the factory does not need a loop-aware entry point; caching happens inside each wrapper.
- ~~`parrot.clients.ClaudeClient`~~ as a separate class — `ClaudeClient` is only an alias for `AnthropicClient` (`clients/claude.py:1470`). Do not define a separate class.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- Async-first throughout — `_ensure_client` is an `async def`.
- Use `self.logger` (already on `AbstractClient`) for every cache miss /
  rebuild / cleanup decision, at DEBUG level for hot paths.
- Use `asyncio.Lock` (per wrapper instance) to serialize concurrent
  first-time builds on the same loop. Do not use a global lock — that
  would serialize independent wrappers.
- `_clients_by_loop` key is `id(asyncio.get_running_loop())`. Never use
  `asyncio.get_event_loop()` — it creates a new loop when none is running
  and would poison the cache.
- `weakref.ref` to the loop object: when the weakref yields None, the loop
  has been GC'd and its entry must be treated as dead.
- Google's model-class metadata moves from a dedicated instance attribute
  to `_LoopClientEntry.metadata["model_class"]`. Subclasses should not
  store per-loop state on the instance itself.

### Known Risks / Gotchas

- **`self.client` setter semantics.** Some existing subclass code writes
  `self.client = None` in `close()` (e.g. `GrokClient.close` at
  `clients/grok.py:92`). The rewritten `close()` must clear the
  underlying dict; the property setter accepts `None` as a reset signal
  and rejects non-None writes with a deprecation warning during the
  migration window.
- **Error-recovery paths that rebuild the client mid-request.** The
  existing `"'NoneType' object has no attribute 'getaddrinfo'"` branch in
  `GoogleGenAIClient` (client.py ~2105) and its streaming counterpart
  (~2715) explicitly `await self.close()` then `await self._ensure_client()`.
  After migration these must close only the **current-loop** entry, not
  the whole dict, or they will evict healthy sessions on sibling loops.
  Introduce `await self._close_current_loop_entry()` for that use case.
- **`use_session=True` path.** `AbstractClient.__aenter__` opens an
  `aiohttp.ClientSession` on `self.session`. That session is also
  loop-bound. For now, scope-match it: `self.session` becomes
  `_sessions_by_loop: dict[int, aiohttp.ClientSession]` with the same
  lifecycle rules. Verify which subclasses set `use_session=True` (grep;
  I believe currently none do in the main clients — **check
  before implementing**).
  NOTE: aiohttp.ClientSession in AbstractClient was used when we used a direct HTTP connection instead the existing anthropic library, if no Client is using that underlying ClientSession, I think we can remove it.
- **GeminiLiveClient.** Its WebSocket stream is created inside a specific
  loop and fundamentally cannot be migrated. The per-loop cache works
  because LiveClient consumers always enter via `async with` on the same
  loop. Add a docstring warning; no special code path needed.
- **Thread-unsafe dict writes.** `_clients_by_loop` is mutated from
  multiple loops (each on its own thread). Python's GIL protects
  individual dict ops, but read-modify-write must go through the lock —
  and each lock acquisition must be on the **current** loop's lock.
  Simplest: allocate the `asyncio.Lock` lazily per loop too
  (`_locks_by_loop: dict[int, asyncio.Lock]`), because `asyncio.Lock()`
  itself is loop-bound.
- **Factory create() timing.** `LLMFactory.create()` (factory.py:68)
  runs synchronously when the agent is configured; no client is built
  yet, so no loop binding happens there. No change needed.
- **Test flakiness.** Tests that spin up secondary loops must join those
  threads and run `new_loop.close()` in a `finally`. Use a
  `loop_in_thread` fixture with strict teardown.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| (no new deps) | — | The spec uses only stdlib (`asyncio`, `weakref`) and existing SDK wrappers |

---

## 8. Open Questions

- [x] **Scope of `close()`.** Should `wrapper.close()` be a "close only my
      current loop" operation (safer, idempotent) or "tear down every
      loop's entry" (current single-instance semantics)? Proposal: both —
      `close()` for current loop only, `close_all()` for full teardown.
      *Owner: Jesus Lara*: I'm ok with both, close and close_all.
- [x] **Deprecation window for `self.client = X` direct writes.** Warn for
      one release, then error? Or hard-error immediately since subclasses
      are all in-tree? *Owner: Jesus Lara*: all subclasses are touched on this feat, we can deprecate now.
- [ ] **`use_session=True` audit.** Confirm no production subclass
      currently sets `use_session=True` before shipping the session
      per-loop changes; if any do, they must migrate in Module 3.
      *Owner: Jesus Lara*
- [x] **LLMFactory test double.** Do we add a `DummyClient` to
      `SUPPORTED_CLIENTS` under a feature-flag for testing, or keep the
      stub local to the test module? Proposal: local to tests.
      *Owner: Jesus Lara*: a DummyClient can help to test AbstractClient easily.
- [x] **Metrics.** Should we emit a log line / counter on cache miss
      (new loop seen)? Useful to spot unexpected loop proliferation
      caused by buggy callers. Proposal: DEBUG-level only.
      *Owner: Jesus Lara*: log line.
- [x] **Live voice loop handoff.** If a future feature needs to migrate a
      `GeminiLiveClient` session across loops (e.g. resume a voice chat
      on a different worker), does it live here or in a separate spec?
      Proposal: separate spec; out of scope here.
      *Owner: Jesus Lara*: separate spec.

---

## Worktree Strategy

- **Default isolation unit**: `per-spec` (single worktree, sequential tasks).
- Rationale: the base-class change (Module 1) is a hard dependency for every
  subclass task (Modules 2, 3, 4) and for tests (Module 5). Parallelizing
  after Module 1 lands would require merging the base change to `dev` mid-feature,
  which breaks the "one worktree, one PR" pattern.
- **Cross-feature dependencies**: none known. The interim loop-invalidation
  code in `GoogleGenAIClient` shipped on `dev` as a patch; Module 2 removes
  it, so this spec must be merged **after** that patch lands.

Worktree command once tasks are decomposed:

```bash
git checkout dev && git pull origin dev
git worktree add -b feat-112-per-loop-llm-client-cache \
  .claude/worktrees/feat-112-per-loop-llm-client-cache HEAD
```

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-04-21 | Jesus Lara | Initial draft |
