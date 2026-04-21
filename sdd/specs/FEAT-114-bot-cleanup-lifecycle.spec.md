# Feature Specification: Bot Cleanup Lifecycle — BotManager-driven per-agent teardown

**Feature ID**: FEAT-114
**Date**: 2026-04-21
**Author**: Jesus Lara
**Status**: approved
**Target version**: next

---

## 1. Motivation & Business Requirements

### Problem Statement

`BotManager` tracks every active bot in `self._bots: Dict[str, AbstractBot]`,
but its aiohttp lifecycle hooks (`on_startup`, `on_shutdown`, `on_cleanup`)
**never iterate over those bots** on shutdown. As a consequence:

- `AbstractBot.cleanup()` — which closes LLM clients, vector stores,
  knowledge-base connections and MCP transports — is only invoked from
  `AbstractBot.__aexit__` (async context manager usage). When a bot is
  long-lived, created at startup and consumed via the HTTP routes
  (`AgentTalk`, `ChatHandler`) it is **never cleaned up**.
- `HookableAgent.stop_hooks()` is only called from
  `AutonomousOrchestrator.stop()`. Any agent that is not part of the
  autonomous orchestrator (e.g. `JiraSpecialist` subclasses registered
  via `@register_agent` and hosted inside Telegram Integration) leaks
  background tasks of non-HTTP hooks (IMAP polling, broker subscribers,
  scheduler jobs, Postgres LISTEN…) on shutdown.
- Recent work on webhook-backed agents (FEAT-110 JiraSpecialist webhook
  ticket creation) makes this gap material: the moment a production agent
  attaches a `JiraWebhookHook` and adds, for example, an IMAP companion
  hook, shutting down the service leaves those background tasks orphaned.

### Goals

- Make `AbstractBot.cleanup()` the **canonical per-bot teardown hook** and
  guarantee it is invoked once for every bot registered with `BotManager`
  during aiohttp's `on_cleanup` phase.
- Add a cooperative `HookableAgent.cleanup()` that stops all registered
  hooks via `stop_hooks()` and chains to `super().cleanup()` so that any
  agent that mixes in `HookableAgent` gets hook teardown for free.
- Run per-bot cleanup **in parallel** via `asyncio.gather`, isolating
  failures so one misbehaving agent cannot block the rest, and **bound
  each cleanup by a timeout** (default 20s, tunable via
  `BOT_CLEANUP_TIMEOUT`) so a hanging teardown cannot block shutdown.
- Ship unit tests that cover: happy path (all bots cleaned), one bot
  raises (others still complete), one bot hangs past timeout (others
  still complete, hanging bot logged), hook-bearing bot stops hooks
  before resource cleanup, empty bot registry (no-op).

### Non-Goals (explicitly out of scope)

- **Crews (`self._crews`) teardown.** Crews compose agents that already
  live in `self._bots`; cleaning each bot once is sufficient and crews
  do not own independent resources today. A future `crew.cleanup()` can
  be introduced when crews acquire their own disposable state.
- **`AbstractBot.shutdown()` semantics.** That method is a stub
  overridden by `Agent`, the A2A mixin, `A2AOrchestrator` and
  `MCPIntegration` with **different** semantics (A2A worker shutdown,
  MCP server teardown). This spec deliberately leaves `shutdown()`
  untouched; `cleanup()` is the resource-release hook.
- **Integration bots wired through `IntegrationBotManager`.** Telegram
  sessions, Slack sockets, Matrix transports and the HITL manager are
  already closed in `IntegrationBotManager.shutdown()`. This spec does
  not duplicate that work.
- **Changing the `__aexit__` path** — the existing usage of `cleanup()`
  from `AbstractBot.__aexit__` is preserved verbatim.
- **Reworking `AgentRegistry` instantiation/lifecycle.** The registry is
  already the source of truth for which bots get created; this feature
  only adds teardown on the `_bots` collection the manager owns.

---

## 2. Architectural Design

### Overview

The design adds three small, composable pieces:

1. A new on-cleanup callback `BotManager._cleanup_all_bots` registered
   on `self.app.on_cleanup` **before** the existing
   `_cleanup_shared_redis` callback, so bots release their per-agent
   resources before the shared Redis client is closed.
2. An internal helper `BotManager._safe_cleanup` that wraps a single
   bot's `cleanup()` in `asyncio.wait_for(..., timeout=BOT_CLEANUP_TIMEOUT)`
   and logs — rather than raises — on exception or timeout.
3. A cooperative `HookableAgent.cleanup()` method on the
   `core/hooks/mixins.py` mixin. It calls `stop_hooks()` first, then
   chains to `super().cleanup()` via MRO. Concrete agents that use the
   mixin MUST declare it **before** their bot base in the class bases
   list (documented contract).

### Component Diagram

```
aiohttp app shutdown
      │
      ▼
 on_shutdown  ── BotManager.on_shutdown
                   ├ cancel _cleanup_task
                   ├ IntegrationManager.shutdown()  (telegram/slack/matrix/HITL)
                   └ chat_storage.close()
      │
      ▼
 on_cleanup  ── BotManager._cleanup_all_bots     (NEW — this spec)
                   └ asyncio.gather(
                        _safe_cleanup(name, bot) for bot in self._bots.values()
                     )
                        │
                        ▼
                   asyncio.wait_for(bot.cleanup(), timeout=BOT_CLEANUP_TIMEOUT)
                        │
                        ▼  (via MRO when HookableAgent is mixed in)
                   HookableAgent.cleanup()  (NEW — this spec)
                        ├ stop_hooks() → HookManager.stop_all()
                        └ await super().cleanup()  →  AbstractBot.cleanup()
                                                        (LLM, store, KBs, MCP)

              ── BotManager._cleanup_shared_redis  (existing, kept last)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `AbstractBot.cleanup()` (`bots/abstract.py:3134`) | extends contract (no code change) | Remains the canonical per-bot teardown target. Subclasses that already override it are **not** modified. |
| `AbstractBot.shutdown()` (`bots/abstract.py:2646`) | untouched | Stub stays as-is; kept separate because `Agent` / `A2AMixin` / `MCPIntegration` already own its semantics. |
| `AbstractBot.__aexit__` (`bots/abstract.py:2539-2541`) | untouched | Continues to call `self.cleanup()` when the bot is used as an async context manager. |
| `HookableAgent` (`core/hooks/mixins.py:9`) | adds new `cleanup()` | Cooperative via `super()`. Requires mixin-first MRO ordering in subclasses. |
| `BotManager.setup()` (`manager/manager.py:755-761`) | registers new `on_cleanup` callback | `_cleanup_all_bots` is appended **before** `_cleanup_shared_redis`. |
| `BotManager.on_shutdown` (`manager/manager.py:1013`) | untouched | Integration teardown and chat storage close remain here. |
| `BotManager._bots` (`manager/manager.py:103`) | iterated for cleanup | Source of truth for the set of agents to clean up. |
| `parrot.conf` (`conf.py`) | new env var | `BOT_CLEANUP_TIMEOUT` — `config.getint('BOT_CLEANUP_TIMEOUT', fallback=20)`. |

### Data Models

No new data models.

### New Public Interfaces

```python
# parrot/core/hooks/mixins.py
class HookableAgent:
    ...
    async def cleanup(self) -> None:
        """Stop hooks, then delegate to the next class in MRO.

        Cooperative override — concrete subclasses that mix in
        ``HookableAgent`` MUST list it **before** their bot base in
        the bases declaration so MRO resolves ``super().cleanup()``
        to the bot base's ``cleanup()``:

            class MyAgent(HookableAgent, JiraSpecialist):  # correct
                ...

        Swallowing any error from ``stop_hooks()`` is intentional —
        cleanup must not abort because one hook failed to stop.
        """
```

```python
# parrot/manager/manager.py
class BotManager:
    ...
    async def _cleanup_all_bots(self, app: web.Application) -> None:
        """on_cleanup callback: invoke ``bot.cleanup()`` on every
        registered bot concurrently and bounded by a timeout."""

    async def _safe_cleanup(self, name: str, bot: AbstractBot) -> bool:
        """Run ``bot.cleanup()`` with timeout and exception isolation.

        Returns True on success, False on timeout or exception.
        Never raises — the gather in ``_cleanup_all_bots`` must
        always complete.
        """
```

```python
# parrot/conf.py
BOT_CLEANUP_TIMEOUT = config.getint('BOT_CLEANUP_TIMEOUT', fallback=20)
```

---

## 3. Module Breakdown

### Module 1: HookableAgent cooperative cleanup
- **Path**: `parrot/core/hooks/mixins.py`
- **Responsibility**: Add an `async def cleanup(self)` that stops the
  hooks and then chains to `super().cleanup()`. Guard the call with
  `getattr(self, "_hook_manager", None) is not None` so the mixin
  remains safe even if `_init_hooks()` was never called. Swallow
  individual exceptions from `stop_hooks()` with
  `self._hooks_logger.exception(...)` so cleanup cannot abort.
- **Depends on**: existing `HookableAgent.stop_hooks()` and
  `self._hook_manager` fields. No new imports required.

### Module 2: BotManager on_cleanup wiring
- **Path**: `parrot/manager/manager.py`
- **Responsibility**:
  1. Add two new coroutines `_cleanup_all_bots(app)` and
     `_safe_cleanup(name, bot)` to `BotManager`.
  2. In `BotManager.setup(app)`, append `_cleanup_all_bots` to
     `self.app.on_cleanup` **before** the existing
     `_cleanup_shared_redis` registration (line
     `manager/manager.py:736`). The order matters: bots that still
     depend on `app['redis']` during their own cleanup must see a
     live client.
  3. Log the outcome summary: `"Bot cleanup complete: X ok, Y failed"`.
- **Depends on**: Module 1 (HookableAgent.cleanup is reached via MRO
  from bots that use the mixin). No cross-task runtime dependency —
  Module 2 ships a safe no-op for bots without `cleanup()` overrides
  because `AbstractBot.cleanup()` already exists.

### Module 3: Configuration constant
- **Path**: `parrot/conf.py`
- **Responsibility**: Add
  `BOT_CLEANUP_TIMEOUT = config.getint('BOT_CLEANUP_TIMEOUT', fallback=20)`
  to the existing `navconfig`-backed constants block.
- **Depends on**: nothing.
- **Import in `manager.py`**: extend the existing
  `from ..conf import (...)` block to include `BOT_CLEANUP_TIMEOUT`.

### Module 4: Tests
- **Path**: `packages/ai-parrot/tests/core/hooks/test_hookable_cleanup.py`
  and `packages/ai-parrot/tests/manager/test_bot_cleanup_lifecycle.py`
- **Responsibility**: Unit tests defined in §4.
- **Depends on**: Modules 1 and 2.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_hookable_cleanup_calls_stop_hooks` | 1 | Mixin calls `stop_hooks()` once when `_hook_manager` exists. |
| `test_hookable_cleanup_no_hooks_initialized` | 1 | Mixin is a safe no-op when `_init_hooks()` was never called (no AttributeError). |
| `test_hookable_cleanup_chains_super` | 1 | Subclass `(HookableAgent, SomeBase)` invokes `SomeBase.cleanup()` through MRO. |
| `test_hookable_cleanup_swallows_stop_hooks_error` | 1 | If `stop_hooks()` raises, cleanup still returns and `super().cleanup()` is called. |
| `test_cleanup_all_bots_empty` | 2 | With no bots registered, `_cleanup_all_bots` logs and returns without calling gather. |
| `test_cleanup_all_bots_happy_path` | 2 | Two bots; both `cleanup()` coroutines awaited exactly once. |
| `test_cleanup_all_bots_isolates_exceptions` | 2 | Bot A raises in `cleanup()`, Bot B succeeds. Both awaited; returned summary reports 1 ok / 1 failed. |
| `test_cleanup_all_bots_timeout` | 2 | Bot A's `cleanup()` sleeps longer than `BOT_CLEANUP_TIMEOUT` (patched to 0.1s); `_safe_cleanup` logs timeout and returns False; Bot B finishes normally. |
| `test_cleanup_registered_on_app` | 2 | `BotManager.setup(app)` appends `_cleanup_all_bots` to `app.on_cleanup`, and its index is **before** `_cleanup_shared_redis`. |
| `test_bot_cleanup_timeout_default` | 3 | `conf.BOT_CLEANUP_TIMEOUT == 20` when env var not set. |
| `test_bot_cleanup_timeout_env_override` | 3 | With `BOT_CLEANUP_TIMEOUT=5` in env, the constant reads 5. |

### Integration Tests

| Test | Description |
|---|---|
| `test_aiohttp_cleanup_triggers_bot_cleanup` | Spin up an `aiohttp.web.Application`, run `BotManager.setup(app)`, register two dummy `AbstractBot` stubs whose `cleanup()` sets a flag, start then stop the app via `aiohttp.test_utils.TestServer`, assert both flags flipped. |
| `test_hookable_cleanup_via_botmanager_end_to_end` | Same scaffold but with one bot that is a `HookableAgent` subclass with a fake hook; on app shutdown, assert (a) hook's `stop()` was awaited, (b) bot's resource `cleanup()` still ran after hook stop, (c) order was `stop_hooks` → `super().cleanup`. |

### Test Data / Fixtures

```python
@pytest.fixture
def dummy_bot_factory():
    """Returns a factory that builds minimal AbstractBot stubs for cleanup tests.

    Stubs implement only the attributes BotManager needs (name) and a
    recordable ``cleanup()`` coroutine. They do NOT inherit from
    AbstractBot to keep tests isolated from its constructor (which
    pulls in navconfig, LLM clients, etc.). BotManager only reads
    ``bot.name`` and awaits ``bot.cleanup()``, so duck typing suffices.
    """

@pytest.fixture
async def test_app():
    """aiohttp test application wired with BotManager.setup()."""
```

---

## 5. Acceptance Criteria

This feature is complete when ALL of the following are true:

- [ ] `HookableAgent.cleanup()` exists on the mixin and calls
  `stop_hooks()` + `super().cleanup()` cooperatively.
- [ ] `BotManager._cleanup_all_bots` is registered on `app.on_cleanup`
  during `BotManager.setup(app)`, strictly before
  `_cleanup_shared_redis`.
- [ ] Every bot in `BotManager._bots` has `cleanup()` awaited exactly
  once during aiohttp's `on_cleanup` phase, concurrently via
  `asyncio.gather`.
- [ ] Per-bot cleanup is bounded by `BOT_CLEANUP_TIMEOUT` (default 20s,
  overridable via env var). A timeout logs a warning and returns; it
  does not propagate.
- [ ] A single bot raising or timing out does not prevent the other
  bots from being cleaned up.
- [ ] `AbstractBot.shutdown()` is **not modified**. `AbstractBot.cleanup()`
  is **not modified**.
- [ ] `IntegrationBotManager.shutdown()` remains unchanged and is not
  called twice (verified by reading `on_shutdown` / `on_cleanup`
  flows in the resulting code).
- [ ] Unit tests in §4 all pass: `pytest packages/ai-parrot/tests/core/hooks/test_hookable_cleanup.py packages/ai-parrot/tests/manager/test_bot_cleanup_lifecycle.py -v`.
- [ ] Integration test `test_aiohttp_cleanup_triggers_bot_cleanup` passes.
- [ ] No existing tests regress:
  `pytest packages/ai-parrot/tests/core/hooks -v` and
  `pytest packages/ai-parrot/tests/manager -v`
  (if present; create the `tests/manager/` directory if it does not
  exist yet).
- [ ] Documentation updated in
  `packages/ai-parrot/docs/` where the hook/agent lifecycle is
  described, including the MRO contract note for `HookableAgent`.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> This section is the single source of truth for what exists in the
> codebase. Implementation agents MUST NOT reference imports,
> attributes, or methods not listed here without first verifying they
> exist via `grep` or `read`.

### Verified Imports

```python
# In manager/manager.py (already present — extend the conf import tuple)
from ..conf import (
    ENABLE_CREWS,
    ENABLE_DATABASE_BOTS,
    ENABLE_DASHBOARDS,
    ENABLE_REGISTRY_BOTS,
    ENABLE_SWAGGER,
    REDIS_URL,
    BOT_CLEANUP_TIMEOUT,   # NEW — added by this feature
)
# verified in packages/ai-parrot/src/parrot/manager/manager.py:54-61

from ..bots.abstract import AbstractBot
# verified in packages/ai-parrot/src/parrot/manager/manager.py:17

import asyncio
from aiohttp import web
# verified in packages/ai-parrot/src/parrot/manager/manager.py:10,12
```

```python
# In core/hooks/mixins.py (already present — no new imports needed)
import logging
from .base import BaseHook
from .manager import HookManager
from .models import HookEvent
# verified in packages/ai-parrot/src/parrot/core/hooks/mixins.py:1-6
```

```python
# In conf.py (already present at line 5)
from navconfig import config, BASE_DIR
# verified in packages/ai-parrot/src/parrot/conf.py:5
# Existing pattern for int env vars:
#   ONTOLOGY_CACHE_TTL = config.getint('ONTOLOGY_CACHE_TTL', fallback=86400)
#   (conf.py:120)
```

### Existing Class Signatures

```python
# packages/ai-parrot/src/parrot/core/hooks/mixins.py
class HookableAgent:
    def _init_hooks(self) -> None:                            # line 26
    @property
    def hook_manager(self) -> HookManager:                    # line 35
    def attach_hook(self, hook: BaseHook) -> str:             # line 48
    async def start_hooks(self) -> None:                      # line 59
    async def stop_hooks(self) -> None:                       # line 63
    async def handle_hook_event(self, event: HookEvent) -> None:  # line 67

    # Key internal state set by _init_hooks():
    #   self._hook_manager: HookManager
    #   self._hooks_logger: logging.Logger
```

```python
# packages/ai-parrot/src/parrot/core/hooks/manager.py
class HookManager:
    async def start_all(self) -> None:                        # line 139
    async def stop_all(self) -> None:                         # line 159
    # stop_all() iterates self._hooks.values(), calls hook.stop()
    # and logs per-hook failures without re-raising.
```

```python
# packages/ai-parrot/src/parrot/bots/abstract.py
class AbstractBot(ABC):
    async def __aenter__(self):                               # line 2536
    async def __aexit__(self, exc_type, exc_value, traceback):  # line 2539
        # Calls self.cleanup() under contextlib.suppress — line 2540-2541
    async def shutdown(self, **kwargs) -> None:               # line 2646
        # Empty stub. Leave untouched per §1 non-goals.
    async def cleanup(self) -> None:                          # line 3134
        # Closes _llm, _llm.session, self.store, self.knowledge_bases,
        # self.kb_store, and self.tool_manager.disconnect_all_mcp().
        # Leave untouched — HookableAgent.cleanup() chains into it via super().
```

```python
# packages/ai-parrot/src/parrot/manager/manager.py
class BotManager:
    def __init__(self, *, enable_crews=..., enable_database_bots=..., ...):
        self.app = None                                       # line 102
        self._bots: Dict[str, AbstractBot] = {}               # line 103
        self._botdef: Dict[str, Type] = {}                    # line 104
        self._cleanup_task: Optional[asyncio.Task] = None     # line 106
        self._redis_owned: bool = False                       # line 125

    def add_bot(self, bot: AbstractBot) -> None:              # line 523
        self._bots[bot.name] = bot

    def setup(self, app: web.Application) -> web.Application:  # line 755
        # Existing order (keep):
        #   self.app.on_startup.append(self.on_startup)      # line 760
        #   self.app.on_shutdown.append(self.on_shutdown)    # line 761
        # Existing on_cleanup registration:
        #   self.app.on_cleanup.append(self._cleanup_shared_redis)  # line 736
        # NEW in this feature:
        #   self.app.on_cleanup.append(self._cleanup_all_bots)
        #   — appended BEFORE _cleanup_shared_redis in call order.

    async def _cleanup_shared_redis(self, app) -> None:       # exists near line 736
        # Closes the shared Redis client only if BotManager owns it
        # (self._redis_owned is True).

    async def on_shutdown(self, app: web.Application) -> None:  # line 1013
        # Cancels _cleanup_task, calls IntegrationManager.shutdown(),
        # closes chat_storage. Does NOT iterate bots. Leave untouched.
```

```python
# packages/ai-parrot/src/parrot/integrations/manager.py
class IntegrationBotManager:
    async def shutdown(self) -> None:                         # line 320
        # Cancels polling tasks, closes Telegram/Slack/Matrix sessions
        # and HITL manager. Leave untouched.
```

```python
# packages/ai-parrot/src/parrot/core/hooks/base.py
class BaseHook(ABC):
    @abstractmethod
    async def start(self) -> None:                            # line 85
    @abstractmethod
    async def stop(self) -> None:                             # line 89
    # stop() is the per-hook teardown; HookManager.stop_all() dispatches
    # to every enabled hook. No change to BaseHook in this feature.
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `HookableAgent.cleanup()` | `HookableAgent.stop_hooks()` | method call | `core/hooks/mixins.py:63` |
| `HookableAgent.cleanup()` | `super().cleanup()` (resolves to `AbstractBot.cleanup` via MRO) | method call | `bots/abstract.py:3134` |
| `BotManager._cleanup_all_bots` | `self._bots` | dict iteration | `manager/manager.py:103` |
| `BotManager._cleanup_all_bots` | `asyncio.gather(...)` | stdlib call | `manager/manager.py:10` (import already present) |
| `BotManager._safe_cleanup` | `asyncio.wait_for(bot.cleanup(), timeout=BOT_CLEANUP_TIMEOUT)` | stdlib + new constant | `conf.py` (new constant), `manager/manager.py` (new wrapper) |
| `BotManager.setup()` | `self.app.on_cleanup.append(self._cleanup_all_bots)` | aiohttp signal registration | `manager/manager.py:736,755-761` |

### Does NOT Exist (Anti-Hallucination)

- ~~`BotManager.shutdown_bots()`~~ — does not exist. Do not invent a
  parallel teardown method; the work belongs in `_cleanup_all_bots`.
- ~~`BotManager._cleanup_bots`~~ — no such name in the code. Use
  `_cleanup_all_bots` to avoid collision with
  `_cleanup_shared_redis`.
- ~~`HookableAgent.close()`~~ / ~~`HookableAgent.shutdown()`~~ — do not
  exist on the mixin. The new method MUST be named `cleanup` so that
  MRO dispatches from `BotManager._safe_cleanup(bot)` → `bot.cleanup()`
  correctly.
- ~~`AbstractBot.on_cleanup`~~ — there is no per-bot on_cleanup hook;
  the aiohttp `on_cleanup` signal is on the `web.Application`, not on
  the bot.
- ~~`AbstractBot.shutdown()` doing resource cleanup~~ — it is a stub
  (`bots/abstract.py:2646`). Do not move cleanup logic into it, and do
  not rename `cleanup()` to `shutdown()`.
- ~~`for bot in self._crews`~~ — crews are explicitly out of scope.
  Touching `self._crews` is a scope violation.
- ~~`AutonomousOrchestrator.stop()` call from BotManager~~ — the
  autonomous orchestrator is a separate subsystem
  (`autonomous/orchestrator.py:243`) with its own lifecycle. Do not
  invoke it from `BotManager._cleanup_all_bots`.
- ~~`app.on_shutdown.append(self._cleanup_all_bots)`~~ — the chosen
  signal is `on_cleanup`, not `on_shutdown`. Registering on the wrong
  signal will run bot cleanup before `IntegrationBotManager.shutdown()`
  finishes and may still-have-open channels referencing the bot.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- **Cooperative mixin via `super()`** — `HookableAgent.cleanup()` uses
  `super().cleanup()` so the mixin composes cleanly with any future
  base class that also defines `cleanup()`. Document clearly that the
  mixin must be listed **before** the bot base in the subclass bases.
  Example: `class JiraTroc(HookableAgent, JiraSpecialist):` not the
  reverse.
- **Exception isolation at cleanup** — follow the same pattern used by
  `HookManager.stop_all` (`core/hooks/manager.py:159-176`): log
  failures per item with `logger.exception`, never re-raise during
  teardown.
- **`asyncio.gather(..., return_exceptions=False)` plus internal try/except** —
  because `_safe_cleanup` never raises, `return_exceptions=False` is
  safe and keeps the gather semantics clean. Do NOT use
  `return_exceptions=True` and then silently discard results — log
  the outcome summary explicitly.
- **Log levels** —
  `self.logger.info` for the summary line,
  `self.logger.warning` for timeouts,
  `self.logger.exception` for unexpected exceptions.
- **Env-var loading** — put `BOT_CLEANUP_TIMEOUT` in `parrot/conf.py`
  next to the other `config.getint` constants (see `conf.py:120,123,172,238`).

### Known Risks / Gotchas

- **MRO ordering**. If a developer declares
  `class MyAgent(JiraSpecialist, HookableAgent)` (mixin last),
  `super().cleanup()` inside `HookableAgent.cleanup()` resolves to
  `object`, which has no `cleanup`, and Python raises
  `AttributeError`. Mitigation (belt-and-braces):
  - Document the ordering contract in the mixin's docstring.
  - In `HookableAgent.cleanup()`, guard the super call with
    `if callable(getattr(super(), "cleanup", None)):` before awaiting.
  This makes the mixin safe in either ordering, but the documented
  ordering is still the recommended one.
- **Bots without `_hook_manager`**. Agents that mix in `HookableAgent`
  but never call `_init_hooks()` will not have `self._hook_manager`.
  `HookableAgent.cleanup()` must guard with
  `getattr(self, "_hook_manager", None) is not None` before calling
  `stop_hooks()`.
- **Double cleanup via `__aexit__`**. If a caller uses a bot as
  `async with bot:` and the bot is also registered with `BotManager`,
  `cleanup()` may run twice (once from `__aexit__`, once from
  `_cleanup_all_bots`). `AbstractBot.cleanup()` today is not
  idempotent — it calls `close()` unconditionally. **Decision**: make
  `_safe_cleanup` idempotent at the BotManager layer by tracking
  `bot.name` in a `self._cleaned_up: set[str]` guard populated on
  entry of `_safe_cleanup`. This avoids requiring every subclass to
  implement idempotency. This is an Open Question (see §8) because it
  could mask real double-dispose bugs.
- **Import cycle risk**. `BOT_CLEANUP_TIMEOUT` in `parrot/conf.py` is
  a plain int; adding it to the existing `from ..conf import (...)`
  tuple in `manager/manager.py` cannot introduce a cycle.
- **Tests must not import real LLM clients / MCP transports**. Use
  `dummy_bot_factory` (see §4) — duck-typed objects with a `name`
  attribute and an `async def cleanup(self)` method.
- **Existing callers of `AbstractBot.cleanup()`** — only
  `AbstractBot.__aexit__` (`bots/abstract.py:2540`) calls it today.
  `pytest` must still pass after this feature ships.
- **Telegram Integration host** — when the host application is
  Telegram Integration (the scenario that motivated FEAT-110),
  `BotManager.setup(app)` runs on the host's aiohttp app, so the new
  `on_cleanup` fires as part of the host's shutdown sequence. No
  extra plumbing needed on the Telegram Integration side.

### External Dependencies

None. The feature uses only stdlib (`asyncio`) and `navconfig` (already
a project dependency).

---

## 8. Open Questions

- [x] **Idempotency guard in `_safe_cleanup`** — adopt the
  `self._cleaned_up: set[str]` guard to protect bots used as both
  async context managers and `BotManager`-tracked singletons, or
  rely on subclass idempotency? *Owner: Jesus Lara — decide before
  implementation.* Recommended default: adopt the guard. It is cheap
  and prevents accidental double-close of LLM sessions: yes, adopt the guard.
- [x] **Should `AbstractBot.cleanup()` gain a finished/closed flag?** —
  Related to the above. Out of scope if we go with the BotManager-side
  guard. *Owner: Jesus Lara.*: out of scope,
- [x] **Tests directory location** — no `packages/ai-parrot/tests/manager/`
  directory exists today. Confirm we create it, or pick an existing
  test module to host the new integration tests. *Owner: Jesus Lara.*: create it.

---

## 9. Worktree Strategy

- **Default isolation unit**: **per-spec**. All tasks are small, live
  in the same three files (`core/hooks/mixins.py`, `manager/manager.py`,
  `conf.py`) plus tests, and must be committed together to keep the
  `on_cleanup` chain consistent. One worktree, sequential task
  execution.
- **Cross-feature dependencies**: none. This spec does not depend on
  in-flight FEAT-110, FEAT-112 or FEAT-113 specs and does not modify
  any file those specs target. It can be merged in any order
  relative to them.
- **Suggested worktree command** (to run after `/sdd-task` has
  produced the task artefacts):
  ```bash
  git worktree add -b feat-114-bot-cleanup-lifecycle \
    .claude/worktrees/feat-114-bot-cleanup-lifecycle HEAD
  ```

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-04-21 | Jesus Lara | Initial draft from in-conversation design. |
