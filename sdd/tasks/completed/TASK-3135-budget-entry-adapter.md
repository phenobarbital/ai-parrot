# TASK-3135: Budget Entry Adapter — Keyword Resolution and Coroutine / Async-Generator Wrappers

**Feature**: FEAT-550 — Cumulative Question Token Budgets for Bedrock and Mantle
**Spec**: `sdd/specs/token-budget-bedrock.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3134
**Assigned-to**: unassigned

---

## Context

Module 2, second half (spec §3 Module 2 "budget entry adapters for coroutines versus
async generators"). This task builds the **pure, client-agnostic** machinery that
TASK-3136 installs into `AbstractClient.__init_subclass__`:

1. Resolve the five §2.1 keywords (`token_budget`, `budget_mode`,
   `final_answer_reserve`, `budget_scope`, `budget_snapshot`) from a call's kwargs
   plus constructor defaults — distinguishing **omission** from an explicit `None`.
2. Decide root vs. child: an inherited live scope makes the call a child; a child
   may not disable/replace the policy (`BudgetScopeConflict`); an independent root
   with `token_budget=None` explicitly supplied disables budgeting.
3. Wrap a coroutine function or an async-generator function so that the scope is
   bound for the **whole** execution (through iteration for generators), the budget
   keywords are stripped before the legacy implementation runs, `functools.wraps`
   metadata is kept, and the introspection signature gains the budget keywords.

No budget → direct pass-through with zero allocations (AC "No inference, counting API
call, tokenizer download or ledger allocation is added to the no-budget path").

---

## Scope

- Add to `packages/ai-parrot/src/parrot/clients/budget_scope.py`:
  - `_MISSING` sentinel and `BUDGET_KWARGS: frozenset[str]` (the five names);
  - `@dataclass(frozen=True) BudgetRequest(policy: Optional[TokenBudgetPolicy], scope: Optional[BudgetScope], snapshot: Optional[BudgetSnapshot], disabled: bool)`;
  - `resolve_budget_request(call_kwargs: dict, *, defaults: BudgetDefaults) -> BudgetRequest`
    implementing §2.1 rules (raise `BudgetScopeConflict` on child conflict; raise
    `ValueError` for non-default mode/reserve without an effective budget);
  - `@dataclass(frozen=True) BudgetDefaults(token_budget, budget_mode, final_answer_reserve, registry)`;
  - `wrap_budgeted_coroutine(fn, *, method_name: str) -> Callable` and
    `wrap_budgeted_async_generator(fn, *, method_name: str) -> Callable`;
  - `budget_entry(fn, *, method_name: str) -> Callable` dispatching on
    `inspect.isasyncgenfunction`, marking the wrapper with `__parrot_budget_wrapped__ = True`
    so TASK-3136 never double-wraps; wrappers call
    `self._budget_defaults()` (a method TASK-3136 adds to `AbstractClient`) and
    `self._budget_gate(method_name, request)` (also TASK-3136) as hooks — in this task
    they are looked up with `getattr(self, ..., None)` so the module stays client-free.
- Extend `test_token_budget_scope.py` with an "entry adapter" group: omission vs `None`,
  child conflict, signature/wraps/coroutine-vs-asyncgen identity, ContextVar held
  through iteration, no allocation when no budget.

**NOT in scope**: editing `AbstractClient` (TASK-3136); bot boundary (TASK-3137).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/clients/budget_scope.py` | MODIFY | Append request resolution + wrappers |
| `packages/ai-parrot/tests/unit/clients/test_token_budget_scope.py` | MODIFY | Append entry-adapter tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified against dev `755c61347` on 2026-09-11 plus TASK-3132..3134 declared outputs.

### Verified Imports
```python
from parrot.clients.budget_scope import BudgetScope, BudgetRegistry, current_budget_scope, get_default_registry   # TASK-3134
from parrot.models.token_budget import TokenBudgetPolicy, BudgetSnapshot                                        # TASK-3132
from parrot.core.exceptions import BudgetScopeConflict                                                          # TASK-3132
import functools, inspect                                                                                       # stdlib
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/clients/budget_scope.py (TASK-3134)
class BudgetScope:
    def __init__(self, ledger, *, registry, is_root: bool, owner_call_id: Optional[str] = None)
    def child(self) -> BudgetScope
    async def __aenter__(self) -> BudgetScope; async def __aexit__(self, exc_type, exc, tb) -> None
    policy: TokenBudgetPolicy; operation_id: str; is_root: bool
class BudgetRegistry:
    async def create(self, policy) -> BudgetScope
    async def resume(self, state, *, snapshot=None) -> BudgetScope
def current_budget_scope() -> Optional[BudgetScope]

# Abstract entry signatures the wrappers must remain compatible with
# packages/ai-parrot/src/parrot/clients/base.py:1735  async def ask(self, prompt, model, max_tokens=None, ..., lazy_loading=False) -> MessageResponse
# packages/ai-parrot/src/parrot/clients/base.py:1776  async def ask_stream(self, prompt, model=None, ...) -> AsyncIterator[Union[str, AIMessage]]   # async generator in every concrete client
# packages/ai-parrot/src/parrot/clients/base.py:1804  async def resume(self, session_id: str, user_input: str, state: Dict[str, Any]) -> MessageResponse
# packages/ai-parrot/src/parrot/clients/base.py:1822  async def invoke(self, prompt, *, output_type=None, structured_output=None, model=None, ...) -> InvokeResult
```

### Does NOT Exist
- ~~`AbstractClient._budget_defaults()`~~ / ~~`AbstractClient._budget_gate()`~~ — added by TASK-3136; in THIS task they are optional hooks resolved via `getattr(self, name, None)`.
- ~~`inspect.signature(...).replace(parameters=...)` on a bound method~~ — operate on the *function*; set `wrapper.__signature__` explicitly.
- ~~`asyncio.iscoroutinefunction`~~ for async generators — it returns `False` for them; use `inspect.isasyncgenfunction` first.
- ~~A `budget_snapshot` keyword on `ask`/`ask_stream`/`invoke`~~ — only `resume` accepts it (spec §2.1 "Application-only input to `resume`"); reject it elsewhere with `TypeError`.

---

## Implementation Notes

### Key Constraints
- `resolve_budget_request` decision table (spec §2.1):
  | inherited scope? | `token_budget` kwarg | result |
  |---|---|---|
  | no | omitted | policy from constructor defaults (None → disabled) |
  | no | explicit `None` | disabled (overrides constructor) |
  | no | int | new root policy |
  | yes | omitted or identical to scope.policy | child of the inherited scope (`scope.child()`) |
  | yes | different / `None` | `BudgetScopeConflict` |
  Explicit `budget_scope=` kwarg behaves like an inherited scope (application-created child).
- If `budget_mode != "estimated"` or `final_answer_reserve != 0.15` is supplied and no
  effective budget exists → `ValueError("budget options require token_budget")`.
- Wrappers: build the effective scope **before** calling the wrapped function; for a
  new root, `await registry.create(policy)`; for `resume` with a snapshot,
  `await registry.resume(state, snapshot=...)` where `state` is the wrapped call's
  `state` argument (third positional / keyword) — the wrapper must read it via
  `inspect.signature(fn).bind_partial(self, *args, **kwargs).arguments["state"]`.
- Async-generator wrapper: `async with scope: async for item in fn(self, *args, **clean): yield item`
  — the `async with` is inside the generator body so the binding is held through
  iteration and released on `aclose()`/exception (spec §2.4 last sentence).
- Signature surgery: `sig = inspect.signature(fn)`; append the budget names as
  `KEYWORD_ONLY` params with default `None` unless the function already has a
  `**kwargs` catch-all (then leave the signature alone — they are legal already);
  set `wrapper.__signature__`.
- Preserve identity: coroutine functions stay coroutine functions
  (`inspect.iscoroutinefunction(wrapper)`), async-generator functions stay
  async-generator functions.

### References in Codebase
- `packages/ai-parrot/src/parrot/bots/base.py:1400-1410` — existing `inspect.signature(client.ask).parameters` introspection that MUST keep working (`max_iterations` probe).

---

## Implementation Blueprint

### Steps (in order)
1. Append sentinel, `BUDGET_KWARGS`, `BudgetDefaults`, `BudgetRequest`, `resolve_budget_request` — *why*: pure decision logic is unit-testable without a client.
2. Append the two wrappers and `budget_entry` — *why*: TASK-3136 needs a single callable to install per method.
3. Append tests using a minimal stand-in class (no `AbstractClient`) that defines `_budget_defaults` returning a `BudgetDefaults`.

### `packages/ai-parrot/src/parrot/clients/budget_scope.py` (MODIFY)
```python
# occurrences: 1 (verified after TASK-3134: grep -c '^__all__ = \["BudgetScope"' packages/ai-parrot/src/parrot/clients/budget_scope.py)
# BEFORE — insert above the `__all__ = [...]` line; then extend __all__ with the new names
import functools  # add to the module's import block
import inspect    # add to the module's import block
from collections.abc import Callable
from dataclasses import dataclass

_MISSING = object()
BUDGET_KWARGS: frozenset[str] = frozenset({"token_budget", "budget_mode", "final_answer_reserve", "budget_scope", "budget_snapshot"})


@dataclass(frozen=True)
class BudgetDefaults:
    """Constructor-level budget settings of a client or bot (spec §2.1)."""

    token_budget: Optional[int] = None
    budget_mode: str = "estimated"
    final_answer_reserve: int | float = 0.15
    registry: Optional[BudgetRegistry] = None


@dataclass(frozen=True)
class BudgetRequest:
    """Resolved outcome of one call's budget keywords."""

    policy: Optional[TokenBudgetPolicy]
    scope: Optional[BudgetScope]          # inherited/explicit parent scope, or None for a root
    snapshot: Optional[BudgetSnapshot]
    disabled: bool

    @property
    def active(self) -> bool:
        return not self.disabled and (self.policy is not None or self.scope is not None)


def resolve_budget_request(call_kwargs: dict[str, Any], *, defaults: BudgetDefaults, method_name: str) -> BudgetRequest:
    """Pop the §2.1 keywords from *call_kwargs* (mutating it) and decide root/child/disabled."""
    tb = call_kwargs.pop("token_budget", _MISSING)
    mode = call_kwargs.pop("budget_mode", _MISSING)
    reserve = call_kwargs.pop("final_answer_reserve", _MISSING)
    explicit_scope = call_kwargs.pop("budget_scope", None)
    snapshot = call_kwargs.pop("budget_snapshot", None)
    if snapshot is not None and method_name != "resume":
        raise TypeError("budget_snapshot is only accepted by resume()")
    parent = explicit_scope or current_budget_scope()
    if parent is not None:
        # FILL IN: omitted/identical settings -> BudgetRequest(parent.policy, parent, snapshot, False);
        #          any differing value (including explicit None) -> BudgetScopeConflict. Bounded by spec §2.1 child rules.
        raise NotImplementedError
    if tb is None:  # explicit None at an independent root disables the constructor budget
        return BudgetRequest(None, None, snapshot, True)
    budget = defaults.token_budget if tb is _MISSING else tb
    if budget is None:
        if mode is not _MISSING or reserve is not _MISSING:
            raise ValueError("budget_mode/final_answer_reserve require an effective token_budget")
        return BudgetRequest(None, None, snapshot, True)
    policy = TokenBudgetPolicy(
        token_budget=budget,
        budget_mode=defaults.budget_mode if mode is _MISSING else mode,
        final_answer_reserve=defaults.final_answer_reserve if reserve is _MISSING else reserve,
    )
    return BudgetRequest(policy, None, snapshot, False)
```
**Why this shape**: `_MISSING` is what lets the wrapper "distinguish omission from presence" (spec §2.1). Popping mutates `call_kwargs` so the legacy implementation never sees budget keywords. Strict Pydantic validation in `TokenBudgetPolicy` rejects the bad types listed in §2.1.

### `packages/ai-parrot/src/parrot/clients/budget_scope.py` (MODIFY, continued — wrappers, same insertion point)
```python
async def _enter_scope(self: Any, request: BudgetRequest, *, method_name: str, state: Optional[dict] = None) -> BudgetScope:
    """Materialise the scope for one call: child of parent, resumed ledger, or new root."""
    registry = (getattr(self, "_budget_registry", None) or get_default_registry())
    if request.scope is not None:
        return request.scope.child()
    if method_name == "resume" and state is not None and TOKEN_BUDGET_STATE_KEY in state:
        return await registry.resume(state, snapshot=request.snapshot)
    return await registry.create(request.policy)


def _amend_signature(fn: Callable, wrapper: Callable) -> None:
    sig = inspect.signature(fn)
    if any(p.kind is inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()):
        wrapper.__signature__ = sig  # type: ignore[attr-defined]
        return
    extra = [inspect.Parameter(n, inspect.Parameter.KEYWORD_ONLY, default=None) for n in sorted(BUDGET_KWARGS)]
    wrapper.__signature__ = sig.replace(parameters=[*sig.parameters.values(), *extra])  # type: ignore[attr-defined]


def wrap_budgeted_coroutine(fn: Callable, *, method_name: str) -> Callable:
    """Wrap a coroutine method: resolve keywords, bind scope for the await, strip keywords."""

    @functools.wraps(fn)
    async def wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
        if not (BUDGET_KWARGS & kwargs.keys()) and current_budget_scope() is None and getattr(self, "_budget_defaults_active", False) is False:
            return await fn(self, *args, **kwargs)  # zero-cost pass-through (AC: nothing added to no-budget path)
        defaults = self._budget_defaults() if hasattr(self, "_budget_defaults") else BudgetDefaults()
        request = resolve_budget_request(kwargs, defaults=defaults, method_name=method_name)
        if not request.active:
            return await fn(self, *args, **kwargs)
        gate = getattr(self, "_budget_gate", None)
        if gate is not None:
            gate(method_name, request)  # raises BudgetUnsupported when the provider did not opt in (TASK-3136)
        state = inspect.signature(fn).bind_partial(self, *args, **kwargs).arguments.get("state") if method_name == "resume" else None
        scope = await _enter_scope(self, request, method_name=method_name, state=state)
        async with scope:
            return await fn(self, *args, **kwargs)

    _amend_signature(fn, wrapper)
    wrapper.__parrot_budget_wrapped__ = True  # type: ignore[attr-defined]
    return wrapper


def wrap_budgeted_async_generator(fn: Callable, *, method_name: str) -> Callable:
    """Wrap an async-generator method: hold the scope binding through iteration (spec §2.4)."""

    @functools.wraps(fn)
    async def wrapper(self: Any, *args: Any, **kwargs: Any):
        # FILL IN: same resolution as the coroutine wrapper (pass-through / resolve / gate), then
        #          `async with scope: async for item in fn(self, *args, **kwargs): yield item`.
        #          The pass-through branch must be `async for item in fn(...): yield item` too. Bounded by spec §2.4 last paragraph.
        raise NotImplementedError
        yield  # keeps this an async generator function

    _amend_signature(fn, wrapper)
    wrapper.__parrot_budget_wrapped__ = True  # type: ignore[attr-defined]
    return wrapper


def budget_entry(fn: Callable, *, method_name: str) -> Callable:
    """Pick the right wrapper for *fn*; idempotent on already-wrapped functions."""
    if getattr(fn, "__parrot_budget_wrapped__", False):
        return fn
    if inspect.isasyncgenfunction(fn):
        return wrap_budgeted_async_generator(fn, method_name=method_name)
    return wrap_budgeted_coroutine(fn, method_name=method_name)
```
**Why this shape**: `__parrot_budget_wrapped__` is the "installed once … do not double-wrap inherited/super calls" guarantee (spec §2.1). The pass-through check reads only `kwargs` keys, one ContextVar and one attribute — no allocation. `_budget_defaults_active` is a cheap bool TASK-3136 sets when the constructor carried a `token_budget`, so a constructor-configured budget still enters the slow path.

### `packages/ai-parrot/tests/unit/clients/test_token_budget_scope.py` (MODIFY)
```python
# occurrences: 1 (verified after TASK-3134: grep -c 'class TestRegistryLifecycle' packages/ai-parrot/tests/unit/clients/test_token_budget_scope.py)
# AFTER — append at end of file
import inspect  # noqa: E402
from parrot.clients.budget_scope import BUDGET_KWARGS, BudgetDefaults, budget_entry, resolve_budget_request  # noqa: E402


class _Stub:
    def __init__(self, token_budget=None):
        self._budget_defaults_active = token_budget is not None
        self._defaults = BudgetDefaults(token_budget=token_budget)

    def _budget_defaults(self):
        return self._defaults

    async def ask(self, prompt: str, model: str = None, **kwargs):
        return {"prompt": prompt, "kwargs": kwargs, "scope": current_budget_scope()}

    async def ask_stream(self, prompt: str):
        yield "a"
        yield current_budget_scope()


class TestResolveBudgetRequest:
    def test_omitted_inherits_constructor_and_explicit_none_disables(self):
        d = BudgetDefaults(token_budget=500)
        assert resolve_budget_request({}, defaults=d, method_name="ask").policy.token_budget == 500
        assert resolve_budget_request({"token_budget": None}, defaults=d, method_name="ask").disabled

    async def test_child_conflict(self):
        # FILL IN: inside `async with await BudgetRegistry().create(POLICY)`, token_budget=1 -> BudgetScopeConflict. Bounded by spec §2.1.
        raise NotImplementedError

    def test_options_without_budget_rejected(self):
        with pytest.raises(ValueError):
            resolve_budget_request({"budget_mode": "strict"}, defaults=BudgetDefaults(), method_name="ask")


class TestEntryWrappers:
    def test_identity_signature_and_wraps_preserved(self):
        w_ask = budget_entry(_Stub.ask, method_name="ask")
        w_stream = budget_entry(_Stub.ask_stream, method_name="ask_stream")
        assert inspect.iscoroutinefunction(w_ask) and inspect.isasyncgenfunction(w_stream)
        assert w_ask.__name__ == "ask" and w_ask.__wrapped__ is _Stub.ask
        assert BUDGET_KWARGS <= set(inspect.signature(w_stream).parameters)
        assert budget_entry(w_ask, method_name="ask") is w_ask  # idempotent

    async def test_no_budget_pass_through_and_keywords_stripped(self):
        # FILL IN: no budget -> result["scope"] is None and no registry record created; with token_budget=100 -> kwargs has no budget keys
        #          and result["scope"].is_root. Bounded by spec §2.1 "strips them before calling legacy implementations".
        raise NotImplementedError

    async def test_stream_holds_scope_through_iteration(self):
        # FILL IN: collect items from wrapped ask_stream(token_budget=100); second item is a BudgetScope; after loop current_budget_scope() is None.
        raise NotImplementedError
```
**Why**: covers spec §4 "Public entry compatibility" at the pure-wrapper level so TASK-3136 can focus on class construction.

### FILL IN checklist
- [ ] `budget_scope.py::resolve_budget_request` child branch — identical vs conflicting; bounded by spec §2.1
- [ ] `budget_scope.py::wrap_budgeted_async_generator` — mirror coroutine flow with `async for … yield`; bounded by spec §2.4
- [ ] `test_token_budget_scope.py::TestResolveBudgetRequest.test_child_conflict`, `TestEntryWrappers.*` bodies

---

## Acceptance Criteria

- [ ] `resolve_budget_request({}, …)` with constructor budget → policy; `{"token_budget": None}` → disabled; child conflict → `BudgetScopeConflict`; options without budget → `ValueError`
- [ ] `budget_entry` keeps coroutine/async-generator identity, `__name__`, `__wrapped__`, and exposes the five keywords in `inspect.signature`
- [ ] Re-wrapping a wrapped function returns the same object
- [ ] No budget → wrapped call performs no registry `create` (assert registry record count unchanged)
- [ ] Async-generator wrapper holds the ContextVar through iteration and resets after exhaustion or `aclose()`
- [ ] `pytest packages/ai-parrot/tests/unit/clients/test_token_budget_scope.py -v` passes
- [ ] `ruff check packages/ai-parrot/src/parrot/clients/budget_scope.py` clean

---

## Test Specification

Scaffold above. Add `test_budget_snapshot_rejected_outside_resume` (`TypeError`) and `test_resume_with_state_envelope_reattaches` (stub `resume(self, session_id, user_input, state)` wrapped; state from `registry.suspend` → wrapper enters the resumed scope, `is_root` True).

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** §2.1 (entire section) and §2.4 last paragraph
2. **Check dependencies** — TASK-3134 in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — confirm `BudgetScope.child()` and `BudgetRegistry.resume()` exist as declared
4. **Update status** in `sdd/tasks/index/token-budget-bedrock.json` → `"in-progress"`
5. **Implement** from the Blueprint
6. **Verify** all acceptance criteria
7. **Move this file** to `sdd/tasks/completed/TASK-3135-budget-entry-adapter.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sdd-worker orchestrator (parrot-sdd-coder native haiku seat returned a
`fidelity_violation` — it wrote `sdd/tasks/completed/...` and `sdd/tasks/index/...` itself,
which is the orchestrator's job only; per the FEAT-549 fidelity gate the merge was refused
and the orchestrator implemented the task directly as the required next attempt)
**Date**: 2026-09-11
**Notes**: Appended `_MISSING`, `BUDGET_KWARGS`, `BudgetDefaults`, `BudgetRequest`,
`resolve_budget_request` (root/child/disabled decision table from spec §2.1, including the
child-conflict raise for any differing setting and the `ValueError` for non-default mode/
reserve without an effective budget), `_enter_scope`, `_amend_signature`,
`wrap_budgeted_coroutine`, `wrap_budgeted_async_generator` (scope held through iteration via
`async with scope: async for item in fn(...): yield item`, mirroring the coroutine wrapper's
pass-through/resolve/gate branches), and `budget_entry` to `budget_scope.py`. Extended
`test_token_budget_scope.py` with `TestResolveBudgetRequest` (omission vs explicit-None,
child-conflict inside an active scope, non-default options without a budget, `budget_snapshot`
rejected outside `resume`) and `TestEntryWrappers` (identity/signature/`__wrapped__`
preservation, idempotent re-wrapping, no-budget pass-through with keyword stripping, the
async-generator wrapper holding `current_budget_scope()` through iteration and resetting after,
and a `resume()` reattachment test using a stub whose constructor `token_budget` matches the
original session so the wrapper's own decision logic — not a manual override — drives it into
`registry.resume(state, snapshot=...)`).
Verified: `pytest packages/ai-parrot/tests/unit/clients/test_token_budget_scope.py -v` → 18
passed; `pytest packages/ai-parrot/tests/unit/clients -q` → 387 passed / 1 pre-existing
unrelated failure (`test_client_class_attrs[google]`); `ruff check` clean on `budget_scope.py`
and the test file.
Note: a separate automated process (commit `be58462d0`, "style: apply black formatting (post
sdd-worker)") reformatted several FEAT-550 files concurrently with this task; verified all
affected suites still pass after that reformat before building on top of it.

**Deviations from spec**: none

Seat: haiku (native), attempt 1 → `fidelity_violation` (touched `sdd/` files out of scope) ·
sdd-worker orchestrator, attempt 2 (implemented directly) · Backend: n/a → orchestrator (Claude
Sonnet 5) · Attempts: 1 (pool, rejected by fidelity gate) + 1 (orchestrator) · Duration: 332.6s
(pool, discarded) + orchestrator implementation/test-authoring time · Tokens: 103792
(subagent_tokens, discarded — not merged).
