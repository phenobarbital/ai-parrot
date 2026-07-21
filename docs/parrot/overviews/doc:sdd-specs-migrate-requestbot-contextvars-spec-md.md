---
type: Wiki Overview
title: 'Feature Specification: Migrate RequestBot to ContextVar-based RequestContext'
id: doc:sdd-specs-migrate-requestbot-contextvars-spec-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: The current request-scoping mechanism uses `RequestBot`, a `__getattr__`-based
relates_to:
- concept: mod:parrot.utils
  rel: mentions
- concept: mod:parrot.utils.helpers
  rel: mentions
---

---
type: feature
base_branch: dev
---

# Feature Specification: Migrate RequestBot to ContextVar-based RequestContext

**Feature ID**: FEAT-175
**Date**: 2026-05-15
**Author**: Jesus Lara
**Status**: approved
**Target version**: next

---

## 1. Motivation & Business Requirements

### Problem Statement

The current request-scoping mechanism uses `RequestBot`, a `__getattr__`-based
dynamic proxy that wraps every method call on an `AbstractBot` delegate to
automatically inject a `RequestContext` into kwargs. While functional, this
pattern has several costs:

- **Lost introspection**: wrapper closures created on every attribute access
  strip `__doc__`, `__name__`, type hints, and async-generator protocol from
  wrapped methods.
- **Virtual-subclass hack**: `AbstractBot.register(RequestBot)` is needed so
  `isinstance(wrapper, AbstractBot)` returns True — a workaround for the proxy
  not being a real subclass.
- **Unfamiliar pattern**: the `__getattr__` delegation surprises contributors
  and makes debugging harder (stack traces show closures, not real methods).
- **Per-access overhead**: a new closure is allocated on every attribute lookup,
  even for repeated calls to the same method.

Python's `contextvars.ContextVar` solves the same per-asyncio-task isolation
problem natively. The codebase already uses ContextVar in four places for
identical purposes. Migrating to ContextVar eliminates the proxy wrapper,
simplifies the call chain, and enables any code deep in the stack (tools,
knowledge bases, middleware) to access the ambient `RequestContext` without
explicit parameter threading.

### Goals

- Replace `RequestBot` proxy with a `ContextVar`-based ambient context mechanism
- Add `AbstractBot.session()` context manager that binds `RequestContext` to the
  current asyncio task, absorbing PBAC enforcement and semaphore from `retrieval()`
- Add ContextVar fallback in `ask()`, `ask_stream()`, `conversation()`, `invoke()`
  so explicit `ctx=` still wins but ambient context is used when omitted
- Expose `current_context()` accessor for deep-stack consumers (tools, KBs)
- Remove `RequestBot` class and `retrieval()` method entirely
- Update all handler callers and tests

### Non-Goals (explicitly out of scope)

- Modifying `RequestContext` itself (it stays as-is; only gains a ContextVar wrapper)
- Adopting `session()` in integration handlers (Telegram, Slack, Teams, WhatsApp) —
  they call `ask()` directly without ctx and will continue to do so
- Passing ctx to LLM client, memory classes, or prompt pipeline middleware —
  these subsystems receive extracted `user_id`/`session_id` and don't need the
  full RequestContext
- Making tools ContextVar-aware — `current_context()` is exposed but no existing
  tool is modified to use it (that's a separate feature)

---

## 2. Architectural Design

### Overview

The migration replaces the runtime-proxy pattern with Python's native
per-asyncio-task isolation. A module-level `_current_ctx: ContextVar` in
`parrot/utils/helpers.py` holds the active `RequestContext`. A new
`AbstractBot.session()` async context manager sets/resets the token, absorbs
PBAC enforcement and the concurrency semaphore from the removed `retrieval()`.
Entry points (`ask`, `ask_stream`, `conversation`, `invoke`) fall back to
`_current_ctx.get()` when no explicit `ctx=` is passed.

### Component Diagram

```
Handler (AgentTalk.post, ChatTalk.post, etc.)
    │
    ▼
async with bot.session(request=req, user_id=uid, session_id=sid) as b:
    │   ┌─────────────────────────────────┐
    │   │ session() internals:            │
    │   │  1. Build RequestContext        │
    │   │  2. PBAC enforcement            │
    │   │  3. _current_ctx.set(ctx)       │
    │   │  4. async with self._semaphore  │
    │   │  5. yield self                  │
    │   │  6. _current_ctx.reset(token)   │
    │   └─────────────────────────────────┘
    │
    ▼
await b.ask(question=...)          ← b IS the real bot (no proxy)
    │
    ├─ ctx = _current_ctx.get()    ← fallback (explicit ctx= wins)
    │
    ├─ _build_kb_context(ctx=ctx)
    │   └─ kb.search(ctx=ctx)
    │       └─ kb._get_employee_id(ctx)
    │           └─ reads ctx.request.session
    │
    └─ [tools can call current_context() if needed]
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `AbstractBot` | modified | Add `session()` method, ContextVar fallback in 4 entry points |
| `RequestContext` | unchanged | Stays as-is; now stored in ContextVar |
| `RequestBot` | **removed** | Class deleted from `helpers.py` |
| `AbstractBot.retrieval()` | **removed** | Replaced by `session()` |
| `AgentTalk.post()` | modified | Switch from `retrieval()` to `session()` |
| `ChatTalk.post()` | modified | Switch from `retrieval()` to `session()` |
| `BotConfigTestHandler` | modified | Switch from `retrieval()` to `session()` |
| KB classes | unchanged | Already accept `ctx=` parameter; no changes |
| Integration handlers | unchanged | Continue calling `ask()` directly without ctx |

### Data Models

No new Pydantic models. `RequestContext` is unchanged.

### New Public Interfaces

```python
# parrot/utils/helpers.py — new additions
from contextvars import ContextVar

_current_ctx: ContextVar[Optional["RequestContext"]] = ContextVar(
    "parrot_request_ctx", default=None
)

def current_context() -> Optional["RequestContext"]:
    """Return the RequestContext bound to the current asyncio task, if any."""
    return _current_ctx.get()


# parrot/bots/abstract.py — new method on AbstractBot
class AbstractBot:
    @asynccontextmanager
    async def session(
        self,
        ctx: Optional[RequestContext] = None,
        *,
        request: web.Request = None,
        app: Optional[Any] = None,
        llm: Optional[Any] = None,
        user_id: Union[str, int, None] = None,
        session_id: Optional[str] = None,
        **ctx_kwargs,
    ) -> AsyncIterator["AbstractBot"]:
        """Bind a RequestContext to the current task for the block's lifetime.

        Absorbs PBAC enforcement and concurrency limiting from the removed
        retrieval() method. Anything awaited beneath this block can call
        current_context() and get the same RequestContext object.
        """
        ...
```

---

## 3. Module Breakdown

### Module 1: ContextVar Infrastructure
- **Path**: `parrot/utils/helpers.py`
- **Responsibility**: Add `_current_ctx` ContextVar, `current_context()` accessor,
  remove `RequestBot` class
- **Depends on**: nothing

### Module 2: AbstractBot.session() + Entry Point Fallbacks
- **Path**: `parrot/bots/abstract.py`
- **Responsibility**: Add `session()` context manager (absorbing PBAC + semaphore
  from `retrieval()`), add ContextVar fallback in `ask()`, `ask_stream()`,
  `conversation()`, `invoke()`. Remove `retrieval()`, remove
  `AbstractBot.register(RequestBot)`, update imports.
- **Depends on**: Module 1

### Module 3: Handler Migration
- **Path**: `parrot/handlers/agent.py`, `parrot/handlers/chat.py`,
  `parrot/handlers/test_handler.py`
- **Responsibility**: Replace `agent.retrieval(...)` with `agent.session(...)`
  in all three handlers. Update type annotations if any reference `RequestBot`.
- **Depends on**: Module 2

### Module 4: BaseBot Concrete Fallback (Optional)
- **Path**: `parrot/bots/base.py`
- **Responsibility**: Add ContextVar fallback in `BaseBot.ask()`,
  `BaseBot.ask_stream()`, `BaseBot.conversation()` concrete implementations
  (belt-and-suspenders — the abstract methods already fall back, but concrete
  overrides should too).
- **Depends on**: Module 1

### Module 5: Test Updates
- **Path**: `tests/bots/test_abstractbot_policy.py`,
  `tests/auth/test_policy_rules_integration.py`, new test file
  `tests/bots/test_session_contextvar.py`
- **Responsibility**: Update existing PBAC tests from `retrieval()` → `session()`.
  Add new tests for ContextVar isolation, fallback semantics, and PBAC in session().
- **Depends on**: Module 2, Module 3

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_current_context_default_none` | Module 1 | `current_context()` returns None when no session is active |
| `test_current_context_within_session` | Module 1+2 | `current_context()` returns the bound RequestContext inside `session()` |
| `test_current_context_reset_after_session` | Module 1+2 | `current_context()` returns None after `session()` exits |
| `test_session_yields_real_bot` | Module 2 | `session()` yields the bot itself, not a proxy wrapper |
| `test_session_isinstance_abstractbot` | Module 2 | Yielded object passes `isinstance(b, AbstractBot)` without virtual registration |
| `test_ask_explicit_ctx_wins` | Module 2+4 | `ask(ctx=explicit)` uses explicit ctx, not the ambient ContextVar |
| `test_ask_falls_back_to_contextvar` | Module 2+4 | `ask()` without `ctx=` reads from ContextVar when inside `session()` |
| `test_ask_no_ctx_no_session` | Module 2+4 | `ask()` without `ctx=` gets `ctx=None` when outside `session()` |
| `test_session_concurrent_isolation` | Module 2 | Two concurrent `session()` blocks on the same bot instance have isolated ctx |
| `test_session_pbac_denied` | Module 2 | `session()` raises `HTTPUnauthorized` when PBAC denies access |
| `test_session_pbac_allowed` | Module 2 | `session()` yields bot when PBAC allows access |
| `test_session_semaphore_limits` | Module 2 | `session()` respects `_semaphore` concurrency limit |

### Integration Tests

| Test | Description |
|---|---|
| `test_agenttalk_session_integration` | AgentTalk POST handler uses `session()` and ctx propagates to KB layer |
| `test_existing_pbac_tests_pass` | Existing PBAC tests in `test_abstractbot_policy.py` pass after migration |

### Test Data / Fixtures

```python
@pytest.fixture
def mock_request():
    """Minimal aiohttp Request mock for testing session()."""
    ...

@pytest.fixture
def configured_bot():
    """A concrete AbstractBot subclass with PBAC and semaphore configured."""
    ...
```

---

## 5. Acceptance Criteria

- [ ] `RequestBot` class is completely removed from `parrot/utils/helpers.py`
- [ ] `_current_ctx` ContextVar and `current_context()` accessor exist in `helpers.py`
- [ ] `AbstractBot.session()` context manager exists with PBAC + semaphore
- [ ] `AbstractBot.retrieval()` method is removed
- [ ] `AbstractBot.register(RequestBot)` line is removed
- [ ] `ask()`, `ask_stream()`, `conversation()`, `invoke()` in both `abstract.py`
  and `base.py` fall back to `_current_ctx.get()` when `ctx=None`
- [ ] All three handlers (`agent.py`, `chat.py`, `test_handler.py`) use `session()`
- [ ] Existing PBAC tests pass (updated from `retrieval()` to `session()`)
- [ ] New ContextVar isolation tests pass (concurrent tasks, reset after exit)
- [ ] No breaking changes to integration handlers (Slack, Telegram, Teams, WhatsApp)
- [ ] `pytest tests/bots/ tests/auth/ -v` passes
- [ ] `ruff check parrot/` passes with no new violations

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**

### Verified Imports

```python
from parrot.utils.helpers import RequestContext         # verified: parrot/utils/helpers.py:5
from parrot.utils.helpers import RequestBot             # verified: parrot/utils/helpers.py:43 — TO BE REMOVED
from ..utils.helpers import RequestContext, RequestBot   # verified: parrot/bots/abstract.py:55
from ..utils.helpers import RequestContext               # verified: parrot/bots/base.py:20
```

### Existing Class Signatures

```python
# parrot/utils/helpers.py
class RequestContext:                                    # line 5
    def __init__(
        self,
        request: web.Request = None,                    # line 21
        app: Optional[Any] = None,                      # line 22
        llm: Optional[Any] = None,                      # line 23
        user_id: Union[str, int] = None,                # line 24
        session_id: str = None,                         # line 25
        **kwargs                                        # line 26
    ): ...
    async def __aenter__(self): return self              # line 36
    async def __aexit__(self, ...): pass                 # line 39

class RequestBot:                                        # line 43 — TO BE REMOVED
    def __init__(self, delegate: Any, context: RequestContext): ...  # line 48
    def __getattr__(self, name: str): ...                # line 52
```

```python
# parrot/bots/abstract.py
class AbstractBot(ABC):
    _semaphore: asyncio.BoundedSemaphore               # line 560: self._semaphore = asyncio.BoundedSemaphore(max_concurrency)

    async def __aenter__(self): return self              # line 3096
    async def __aexit__(self, ...):                      # line 3099
        with contextlib.suppress(Exception):
            await self.cleanup()                         # line 3101

    @asynccontextmanager
    async def retrieval(                                 # line 3103 — TO BE REPLACED
        self,
        request: web.Request = None,
        app: Optional[Any] = None,
        llm: Optional[Any] = None,
        **kwargs
    ) -> AsyncIterator["RequestBot"]:
        ctx = RequestContext(request=request, app=app, llm=llm, **kwargs)  # line 3133
        wrapper = RequestBot(delegate=self, context=ctx)                   # line 3139
        # PBAC enforcement: lines 3141-3197
        async with self._semaphore:                                        # line 3200
            yield wrapper                                                  # line 3202

    @abstractmethod
    async def ask(self, ..., ctx: Optional[RequestContext] = None, ...) -> AIMessage:        # line 3473
    @abstractmethod
    async def ask_stream(self, ..., ctx: Optional[RequestContext] = None, ...) -> AsyncIterator:  # line 3520
    @abstractmethod
    async def conversation(self, ..., ctx: Optional[RequestContext] = None, ...) -> AIMessage:    # line 2942
    @abstractmethod
    async def invoke(self, ..., ctx: Optional[RequestContext] = None, ...) -> AIMessage:          # line 3217

    async def _build_kb_context(                         # line 2609
        self, question, user_id=None, session_id=None, ctx=None
    ) -> Tuple[str, Dict[str, Any]]:
        # Passes ctx to kb.should_activate() at line 2664
        # Passes ctx to kb.search() at line 2679

AbstractBot.register(RequestBot)                         # line 3759 — TO BE REMOVED
```

```python
# parrot/bots/base.py
class BaseBot(AbstractBot):
    async def ask(self, ..., ctx: Optional[RequestContext] = None, ...) -> AIMessage:   # line 653, ctx at line 666
        # Forwards ctx to _build_kb_context at line 826
    async def ask_stream(self, ..., ctx: Optional[RequestContext] = None, ...) -> AsyncIterator:  # line 1157, ctx at line 1170
        # Forwards ctx to _build_kb_context at line 1257
    async def conversation(self, ..., ctx: Optional[RequestContext] = None, ...) -> AIMessage:    # line 115, ctx at line 130
        # Forwards ctx to _build_kb_context at line 235
```

### Handler Call Sites (all switch from retrieval → session)

```python
# parrot/handlers/agent.py — AgentTalk.post()
async with agent.retrieval(self.request, app=app, user_id=user_id, session_id=user_session) as bot:  # line 1504
    # method_name path: line 1505
    # stream path: self._handle_stream_response(bot=bot, ...) at line 1516
    #   → bot.ask_stream() at line 1989
    # ask path: bot.ask() at line 1550

# parrot/handlers/chat.py — ChatTalk.post()
async with chatbot.retrieval(self.request, app=app, llm=llm) as bot:  # line 455

# parrot/handlers/test_handler.py — BotConfigTestHandler
async with agent.retrieval(...) as bot:  # line 197
```

### Test Call Sites (update retrieval → session)

```python
# tests/bots/test_abstractbot_policy.py
async with bot.retrieval(request=request) as wrapper:  # lines 166, 185, 202, 220, 230

# tests/auth/test_policy_rules_integration.py
async with bot.retrieval(request=request) as wrapper:  # lines 137, 160, 361
```

### Existing ContextVar Patterns (reference)

```python
# parrot/handlers/web_hitl.py — line 52
current_web_session: ContextVar[Optional[str]] = ContextVar("current_web_session", default=None)

# parrot/tools/dataset_manager/tool.py — line 41
_pctx_var: contextvars.ContextVar = contextvars.ContextVar("dataset_manager_pctx", default=None)
```

### Does NOT Exist (Anti-Hallucination)

- ~~`AbstractBot.session()`~~ — does not exist yet (this spec creates it)
- ~~`parrot.utils.helpers._current_ctx`~~ — does not exist yet (this spec creates it)
- ~~`parrot.utils.helpers.current_context()`~~ — does not exist yet (this spec creates it)
- ~~`RequestContext` in `parrot/utils/__init__.py`~~ — NOT exported from `__init__.py`;
  must import from `parrot.utils.helpers` directly
- ~~existing tests for `RequestBot`~~ — no tests exist that test RequestBot directly
- ~~`AbstractBot.ctx` attribute~~ — does not exist; ctx is not stored on the bot instance

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- **ContextVar pattern from `web_hitl.py`**: module-level `ContextVar` + accessor
  function + set/reset in a context manager. Follow this exact pattern.
- **PBAC enforcement from `retrieval()`**: copy the PBAC block (lines 3141-3197)
  verbatim into `session()`. Do not redesign — port directly.
- **Semaphore from `retrieval()`**: wrap the yield with `async with self._semaphore:`
  exactly as `retrieval()` does at line 3200.
- **`session()` yields `self`, not a wrapper**: this is the key difference from
  `retrieval()`. The bot instance is real, not proxied. The ContextVar provides
  the ctx propagation that RequestBot's `__getattr__` used to provide.

### Known Risks / Gotchas

- **PBAC regression**: if PBAC enforcement code is not ported correctly from
  `retrieval()` to `session()`, access control silently breaks. Mitigation:
  existing PBAC tests (`test_abstractbot_policy.py`) must pass after migration.
- **Semaphore omission**: if `session()` doesn't include the semaphore, bot
  concurrency becomes unbounded. Mitigation: port the `async with self._semaphore:`
  block and add a test that verifies the limit.
- **`_handle_stream_response` receives `bot`**: the streaming helper at
  `agent.py:1948` takes `bot: AbstractBot` as parameter. After migration, `bot`
  is the real bot (not RequestBot). The method calls `bot.ask_stream()` which
  will use the ContextVar fallback — no changes needed in the helper itself.
- **`followup()` method**: called at `agent.py:1535` — this method also takes
  `ctx` via RequestBot injection. After migration, `followup()` needs the same
  ContextVar fallback added. Verify if `followup()` exists on AbstractBot and
  add the fallback if it accepts ctx.
- **async context manager nesting**: `session()` enters `RequestContext`'s
  async context manager (`async with ctx:`). Since `RequestContext.__aenter__`
  and `__aexit__` are no-ops, this is safe but must be preserved for future
  lifecycle hooks.

### External Dependencies

None. `contextvars` is stdlib (Python 3.7+).

---

## 8. Open Questions

### Resolved (during proposal phase)

- [x] **How should PBAC + semaphore from retrieval() be handled?** —
  *Resolved in proposal*: Move everything into `session()`. `retrieval()` is
  removed entirely.
- [x] **What happens to RequestBot?** — *Resolved in proposal*: Remove
  immediately. No deprecation period.

### Unresolved (defer to implementation)

- [x] **Does `followup()` accept `ctx`?** — If so, it needs the ContextVar
  fallback. Check the method signature during implementation. *Owner: implementer*: yes, followup accept ctx.
- [x] **Should `current_context()` be re-exported from `parrot.utils.__init__.py`?** —
  Currently `RequestContext` is NOT exported from `__init__.py`. The new accessor
  could follow the same pattern (import from `helpers` directly) or be promoted.
  *Owner: implementer*: follow same pattern.

---

## Worktree Strategy

- **Isolation unit**: per-spec (sequential tasks)
- **Rationale**: all modules modify overlapping files (`abstract.py` is touched
  by Module 2, 3, and 5). Sequential execution avoids merge conflicts.
- **Cross-feature dependencies**: none — this feature is self-contained.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-05-15 | Jesus Lara / Claude Opus 4.6 | Initial draft from FEAT-175 proposal |
