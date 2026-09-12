# TASK-3136: `AbstractClient` Budget Gate — `__init_subclass__`, `budget_supported_methods`, Constructor Policy

**Feature**: FEAT-550 — Cumulative Question Token Budgets for Bedrock and Mantle
**Spec**: `sdd/specs/token-budget-bedrock.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3135
**Assigned-to**: unassigned

---

## Context

Module 3 (spec §3 "Module 3: Core Entry Guards …"), client half. This is the
**foundational** change the spec flags as needing senior review (§7 "The largest
integration risk is the common entry wrapper"): `AbstractClient.__init_subclass__`
installs the TASK-3135 entry adapter **once** on every concrete override of the four
public text methods (`ask`, `ask_stream`, `resume`, `invoke`), and a new class
attribute `budget_supported_methods: frozenset[str]` (empty by default) makes any
provider that did not opt in fail with `BudgetUnsupported` **before** its
implementation runs whenever a budget is requested or inherited (spec §2.1 "Provider
capability gate").

> `parrot/clients/base.py` is the foundation (`.agent/CONTEXT.md` "Never modify …
> without discussing first"). The spec §3 Module 3 is that discussion; this task
> implements exactly what it says and nothing else.

---

## Scope

- In `packages/ai-parrot/src/parrot/clients/base.py`:
  - add class attribute `budget_supported_methods: frozenset[str] = frozenset()`;
  - add `def __init_subclass__(cls, **kwargs: Any) -> None` that calls
    `super().__init_subclass__(**kwargs)` (cooperative), then for each name in
    `("ask", "ask_stream", "resume", "invoke")` present in `cls.__dict__` and **not**
    abstract (`getattr(fn, "__isabstractmethod__", False) is False`) replaces
    `cls.<name>` with `budget_entry(fn, method_name=name)`;
  - in `__init__`, consume the §2.1 constructor keywords from `kwargs`
    (`token_budget`, `budget_mode`, `final_answer_reserve`, `budget_registry`) into
    `self._budget_defaults_value: BudgetDefaults`, set
    `self._budget_defaults_active = token_budget is not None`, store
    `self._budget_registry`;
  - add `def _budget_defaults(self) -> BudgetDefaults` and
    `def _budget_gate(self, method_name: str, request: BudgetRequest) -> None`
    (raises `BudgetUnsupported` when `method_name not in self.budget_supported_methods`).
- Write `packages/ai-parrot/tests/unit/clients/test_token_budget_boundaries.py`
  groups "Public entry compatibility" and "Unsupported providers" (spec §4).
- Run the existing client suites to prove no-budget behaviour is unchanged.

**NOT in scope**: bot edits (TASK-3137), tool/mixin propagation (TASK-3138), any
provider opt-in (TASK-3140 / TASK-3142 set `budget_supported_methods`).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/clients/base.py` | MODIFY | `__init_subclass__`, class attr, constructor kwargs, two hooks |
| `packages/ai-parrot/tests/unit/clients/test_token_budget_boundaries.py` | CREATE | Entry compatibility + unsupported-provider tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified against dev `755c61347` on 2026-09-11.

### Verified Imports
```python
from parrot.clients.budget_scope import BudgetDefaults, BudgetRequest, budget_entry, current_budget_scope  # TASK-3134/3135
from parrot.core.exceptions import BudgetUnsupported                                                   # TASK-3132
# base.py already imports (verified lines): `from abc import ABC, abstractmethod` (:16), `import inspect` (:5),
#   `from typing import ... Any, Callable, FrozenSet` (:2), `from ..exceptions import InvokeError, TruncatedResponseError` (:36)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/clients/base.py
class AbstractClient(EventEmitterMixin, ABC):                    # line 228
    version: str = "0.1.0"                                        # line 231
    use_session: bool = False                                     # line 237  ← anchor for the new class attribute
    def __init__(self, preset=None, tools=None, use_tools=False, debug=True, tool_manager=None, **kwargs):   # line 360-368
        ...
        self.invoke_max_tokens: Optional[int] = kwargs.get("invoke_max_tokens", None)   # line 405 ← anchor for constructor kwargs
    async def _ensure_client(self, **hints: Any) -> Any            # line 903
    @abstractmethod async def ask(...)                             # line 1734-1735
    @abstractmethod async def ask_stream(...)                      # line 1775-1776
    @abstractmethod async def resume(self, session_id, user_input, state)   # line 1803-1804
    @abstractmethod async def invoke(self, prompt, *, ...)         # line 1821-1822

# EventEmitterMixin (parrot/core/events/lifecycle) defines NO __init_subclass__ (grep verified) — plain super() call is safe.
# Concrete subclasses seen today: BedrockConverseBase (amazon/bedrock.py:141) overrides all four; OpenAIBaseClient (openai_base.py:65) overrides all four;
#   thin subclasses BedrockConverseClient / NovaClient / BedrockMantleClient override NONE of the four (inherit wrapped versions — must not be re-wrapped).
```

### Does NOT Exist
- ~~`AbstractClient.__init_subclass__`~~ — does not exist today; this task adds it.
- ~~`AbstractClient.budget_supported_methods`~~ — new.
- ~~`ABCMeta` override / custom metaclass~~ — do NOT add one; `__init_subclass__` on the class is sufficient and keeps `ABC` cooperative construction intact.
- ~~`self.token_budget` attribute on the client~~ — store only `_budget_defaults_value`; a public mutable counter on a shared client is forbidden (spec §7 "not counters/config mutations on a shared client").
- ~~`_ensure_client()` budget check~~ — the spec explicitly rejects gating only there (§2.1 "closes direct-call and cached-SDK bypasses that a check only in `_ensure_client()` would leave open").

---

## Implementation Notes

### Pattern to Follow
```python
# Wrap only concrete overrides defined ON THIS class (cls.__dict__), never inherited attributes.
def __init_subclass__(cls, **kwargs: Any) -> None:
    super().__init_subclass__(**kwargs)
    for name in _BUDGETED_METHODS:
        fn = cls.__dict__.get(name)
        if fn is None or getattr(fn, "__isabstractmethod__", False):
            continue
        setattr(cls, name, budget_entry(fn, method_name=name))
```

### Key Constraints
- Import `budget_entry` lazily inside `__init_subclass__` (function-level import) if a
  module-level import of `parrot.clients.budget_scope` from `base.py` creates a cycle
  (`budget_scope` → `budget` → `parrot.core.exceptions` → `parrot.exceptions`; none of
  those import `parrot.clients.base`, so a module-level import should be safe — verify by
  `python -c "import parrot.clients.base"` after the edit; fall back to lazy import only if it fails).
- `_budget_gate` is only reached when a budget is active (the wrapper's pass-through
  skips it), so unsupported providers keep byte-identical no-budget behaviour.
- `super().execute_llm_call` chains and `super().ask(...)` calls inside subclasses hit the
  wrapped parent method; because the wrapper is idempotent (`__parrot_budget_wrapped__`)
  and the child scope is `current_budget_scope()`-aware, nested entry creates a **child**
  scope, not a second root — assert this in tests ("nested/super calls").
- `BedrockConverseClient`, `NovaClient`, `BedrockMantleClient` inherit wrapped methods;
  `__init_subclass__` runs for them too but finds nothing in `cls.__dict__` → no re-wrap.
- Constructor kwargs are read with `kwargs.get`, matching the existing style at line 405;
  do not `pop` (other code may introspect `kwargs`).

### References in Codebase
- `packages/ai-parrot/tests/unit/clients/test_abstract_client_memoryless.py:20-45` — `StubClient` pattern for a concrete no-network subclass; copy it.
- `packages/ai-parrot/tests/unit/clients/test_all_client_ask_signatures.py` — existing signature test that must still pass after wrapping.

---

## Implementation Blueprint

### Steps (in order)
1. Add the class attribute and `__init_subclass__` — *why*: this is the single common gate spec §2.1 demands; installing per class definition means zero per-call cost for classes that never budget.
2. Add constructor consumption + the two hooks — *why*: TASK-3135's wrappers look these up by name.
3. Write the tests with two stub subclasses: one with `budget_supported_methods = frozenset({"ask","ask_stream","resume","invoke"})`, one with the default empty set.
4. Run `pytest packages/ai-parrot/tests/unit/clients -q` — *why*: AC "existing relevant client … regression tests pass with no budget configured".

### `packages/ai-parrot/src/parrot/clients/base.py` (MODIFY — imports)
```python
# occurrences: 1 (verified: grep -c 'from ..exceptions import InvokeError, TruncatedResponseError' packages/ai-parrot/src/parrot/clients/base.py)
# AFTER — insert below `from ..exceptions import InvokeError, TruncatedResponseError` (verified: base.py:36)
from ..core.exceptions import BudgetUnsupported
from .budget_scope import BudgetDefaults, BudgetRequest, budget_entry

_BUDGETED_METHODS: tuple[str, ...] = ("ask", "ask_stream", "resume", "invoke")
```
**Why**: names fixed by spec §2.1 ("the four public text methods").

### `packages/ai-parrot/src/parrot/clients/base.py` (MODIFY — class attribute + `__init_subclass__`)
```python
# occurrences: 1 (verified: grep -c '    use_session: bool = False' packages/ai-parrot/src/parrot/clients/base.py)
# AFTER — insert below `    use_session: bool = False` (verified: base.py:237)
    # FEAT-550: providers that can honour a cumulative question budget list the
    # public text methods they cover. Empty means "unsupported": any requested or
    # inherited budget fails with BudgetUnsupported BEFORE the implementation runs.
    budget_supported_methods: FrozenSet[str] = frozenset()

    def __init_subclass__(cls, **kwargs: Any) -> None:
        """Install the budget entry adapter once on each concrete public text method (FEAT-550 §2.1)."""
        super().__init_subclass__(**kwargs)
        for _name in _BUDGETED_METHODS:
            _fn = cls.__dict__.get(_name)
            if _fn is None or getattr(_fn, "__isabstractmethod__", False):
                continue  # inherited or still abstract: nothing to wrap here
            setattr(cls, _name, budget_entry(_fn, method_name=_name))
```
**Why**: `cls.__dict__` (not `getattr`) is what prevents double-wrapping inherited methods; skipping `__isabstractmethod__` leaves the ABC declarations untouched so `ABC` still enforces implementation.

### `packages/ai-parrot/src/parrot/clients/base.py` (MODIFY — constructor + hooks)
```python
# occurrences: 1 (verified: grep -c 'self.invoke_max_tokens: Optional\[int\] = kwargs.get("invoke_max_tokens", None)' packages/ai-parrot/src/parrot/clients/base.py)
# AFTER — insert below `        self.invoke_max_tokens: Optional[int] = kwargs.get("invoke_max_tokens", None)` (verified: base.py:405)
        # FEAT-550 §2.1: constructor-level question budget defaults. Immutable
        # record, never a mutable counter on the shared client instance.
        _tb = kwargs.get("token_budget", None)
        self._budget_defaults_value: BudgetDefaults = BudgetDefaults(
            token_budget=_tb,
            budget_mode=kwargs.get("budget_mode", "estimated"),
            final_answer_reserve=kwargs.get("final_answer_reserve", 0.15),
            registry=kwargs.get("budget_registry", None),
        )
        self._budget_defaults_active: bool = _tb is not None
        self._budget_registry = self._budget_defaults_value.registry
        if _tb is not None:
            # FILL IN: validate eagerly by constructing TokenBudgetPolicy(...) so a bad constructor value fails at
            #          construction, not at first call — bounded by spec §2.1 "Reject booleans, strings, negative…".
            pass
```
```python
# occurrences: 1 (verified: grep -c '    async def _ensure_client(self, \*\*hints: Any) -> Any:' packages/ai-parrot/src/parrot/clients/base.py)
# BEFORE — insert above `    async def _ensure_client(self, **hints: Any) -> Any:` (verified: base.py:903)
    def _budget_defaults(self) -> BudgetDefaults:
        """Constructor-level budget settings consumed by the entry adapter (FEAT-550)."""
        return self._budget_defaults_value

    def _budget_gate(self, method_name: str, request: BudgetRequest) -> None:
        """Refuse a requested or inherited budget on a provider/method that did not opt in.

        Raises:
            BudgetUnsupported: when ``method_name`` is not in ``budget_supported_methods``.
        """
        if method_name not in self.budget_supported_methods:
            self.logger.warning("token budget requested on unsupported %s.%s", self.__class__.__name__, method_name)
            raise BudgetUnsupported(
                f"{self.__class__.__name__}.{method_name} does not support question token budgets",
                operation_id=request.scope.operation_id if request.scope is not None else None,
            )
```
**Why**: the gate runs inside the wrapper *after* keyword resolution and *before* the implementation, which is what closes the "cached-SDK bypass" (spec §2.1) — a provider with a warm `self.client` still cannot start an unbudgeted request under an inherited scope.

### `packages/ai-parrot/tests/unit/clients/test_token_budget_boundaries.py` (CREATE)
```python
"""FEAT-550 M3 — public entry compatibility and unsupported-provider gate (spec §4 rows)."""
from __future__ import annotations

import inspect
from typing import Any

import pytest

from parrot.clients.base import AbstractClient
from parrot.clients.budget_scope import BudgetRegistry, current_budget_scope
from parrot.core.exceptions import BudgetUnsupported
from parrot.models.basic import CompletionUsage
from parrot.models.responses import AIMessage, InvokeResult


class _Base(AbstractClient):
    client_type = "stub"

    def __init__(self, **kw: Any) -> None:
        kw.setdefault("model", "stub")
        super().__init__(**kw)
        self.calls: list[tuple[str, dict]] = []

    async def get_client(self):
        return self

    async def ask(self, prompt, model=None, **kwargs):
        self.calls.append(("ask", dict(kwargs)))
        return AIMessage(input=prompt, output="ok", response="ok", model="stub", provider="stub", usage=CompletionUsage())

    async def ask_stream(self, prompt, **kwargs):
        self.calls.append(("ask_stream", dict(kwargs)))
        yield "chunk"
        yield AIMessage(input=prompt, output="ok", response="ok", model="stub", provider="stub", usage=CompletionUsage())

    async def resume(self, session_id, user_input, state):
        self.calls.append(("resume", {}))
        return await self.ask(user_input)

    async def invoke(self, prompt, **kwargs):
        self.calls.append(("invoke", dict(kwargs)))
        return InvokeResult(output="ok", model="stub", usage=CompletionUsage())


class SupportedClient(_Base):
    budget_supported_methods = frozenset({"ask", "ask_stream", "resume", "invoke"})


class UnsupportedClient(_Base):
    pass


class ThinSubclass(SupportedClient):
    """Overrides none of the four — must inherit wrapped methods without re-wrapping."""


class TestPublicEntryCompatibility:
    def test_wrappers_installed_once_and_identity_preserved(self):
        assert getattr(SupportedClient.ask, "__parrot_budget_wrapped__", False)
        assert ThinSubclass.ask is SupportedClient.ask
        assert inspect.iscoroutinefunction(SupportedClient.ask) and inspect.isasyncgenfunction(SupportedClient.ask_stream)
        assert inspect.isabstract(AbstractClient)
        assert "token_budget" in inspect.signature(SupportedClient.ask).parameters

    async def test_no_budget_pass_through(self):
        c = SupportedClient()
        msg = await c.ask("hi")
        assert msg.output == "ok" and c.calls[0][1] == {} and current_budget_scope() is None

    async def test_budget_keywords_stripped_and_scope_bound(self):
        # FILL IN: await c.ask("hi", token_budget=1000) -> calls[0][1] has no budget keys; inside the stub, current_budget_scope() was set
        #          (capture it in the stub via a module-level list). Bounded by spec §2.1.
        raise NotImplementedError

    async def test_nested_super_call_is_child_not_new_root(self):
        # FILL IN: subclass whose ask() calls super().ask(prompt, **kwargs) — assert exactly ONE registry record is created. Bounded by spec §2.1.
        raise NotImplementedError

    async def test_constructor_budget_applies_without_per_call_kwarg(self):
        # FILL IN: SupportedClient(token_budget=500).ask("x") binds a scope with policy.token_budget == 500. Bounded by spec §2.1.
        raise NotImplementedError


class TestUnsupportedProviders:
    async def test_explicit_budget_rejected_before_implementation(self):
        c = UnsupportedClient()
        with pytest.raises(BudgetUnsupported):
            await c.ask("hi", token_budget=100)
        assert c.calls == []

    async def test_inherited_scope_rejected_even_with_cached_client(self):
        # FILL IN: enter a scope from BudgetRegistry().create(policy); UnsupportedClient with self.client pre-set; ask("hi") -> BudgetUnsupported, calls == []
        raise NotImplementedError

    async def test_no_budget_keeps_behavior(self):
        c = UnsupportedClient()
        assert (await c.invoke("x")).output == "ok"
```
**Why**: exactly the spec §4 rows "Public entry compatibility" and "Unsupported providers"; `ThinSubclass` is the stand-in for `BedrockConverseClient`/`NovaClient`/`BedrockMantleClient`.

### FILL IN checklist
- [ ] `base.py::AbstractClient.__init__` — eager policy validation for constructor `token_budget`; bounded by spec §2.1 rejection list
- [ ] `test_token_budget_boundaries.py` FILL IN bodies — nested/super single-root assertion is mandatory (spec §2.1 "do not double-wrap inherited/super calls")

---

## Acceptance Criteria

- [ ] `AbstractClient.budget_supported_methods == frozenset()`; `SupportedClient.ask` carries `__parrot_budget_wrapped__`; `ThinSubclass.ask is SupportedClient.ask`
- [ ] Abstract declarations remain abstract (`inspect.isabstract(AbstractClient)`); `inspect.signature(...)` of wrapped methods lists the budget keywords
- [ ] No budget → identical behaviour, empty kwargs reach the implementation, no registry record created
- [ ] Explicit or inherited budget on an unsupported provider → `BudgetUnsupported` before the implementation runs, even with a cached client
- [ ] Nested `super().ask()` under a budget creates exactly one ledger
- [ ] `pytest packages/ai-parrot/tests/unit/clients -q` passes (includes `test_all_client_ask_signatures.py`, `test_abstract_client_memoryless.py`)
- [ ] `pytest packages/ai-parrot-client-amazon/tests/unit -q` passes unchanged (thin subclasses inherit wrapped methods)
- [ ] `python -c "import parrot.clients.base"` succeeds (no import cycle); `ruff check packages/ai-parrot/src/parrot/clients/base.py` clean

---

## Test Specification

Scaffold above. Add `test_bad_constructor_budget_fails_at_construction` (`SupportedClient(token_budget=True)` raises) and `test_budget_snapshot_only_on_resume` (`ask(..., budget_snapshot=obj)` → `TypeError`).

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** §2.1 "Provider capability gate", §3 Module 3, §7 Known Risks
2. **Check dependencies** — TASK-3135 in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — re-run the three `grep -c` anchor checks above; if any count differs, stop and update this file first
4. **Update status** in `sdd/tasks/index/token-budget-bedrock.json` → `"in-progress"`
5. **Implement** from the Blueprint; do not add a metaclass or touch `_ensure_client`
6. **Verify** all acceptance criteria — run BOTH the core and the Amazon unit suites
7. **Move this file** to `sdd/tasks/completed/TASK-3136-abstract-client-budget-gate.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sdd-worker orchestrator (parrot-sdd-coder pool: qwen attempt 1 timed out,
gemini attempt 2 succeeded); orchestrator performed the senior review this task explicitly
flags as required (spec §7 "the largest integration risk")
**Date**: 2026-09-11
**Notes**: Reviewed gemini's diff line-by-line against the blueprint before accepting. It
matched exactly: `budget_supported_methods: FrozenSet[str] = frozenset()`, the cooperative
`__init_subclass__` wrapping only concrete overrides in `cls.__dict__` (never abstract
declarations, never re-wrapping inherited/thin-subclass methods), constructor consumption of
the four §2.1 keywords into an immutable `BudgetDefaults`, eager `TokenBudgetPolicy(...)`
construction so a bad constructor `token_budget` fails at construction time, and the
`_budget_defaults()`/`_budget_gate()` hooks with the `BudgetUnsupported` refusal. Found and
fixed one regression during review: the coder placed the new `_BUDGETED_METHODS` module-level
tuple in the middle of `base.py`'s existing import block (between two pre-existing import
statements), which is not an import itself and made ruff flag E402 on every import below it;
moved it to just above `LLM_PRESETS` after all imports. Also found the test file was missing
`test_budget_snapshot_only_on_resume`, an explicitly required addition per the task's own Test
Specification section — added it (`ask(..., budget_snapshot=...)` raises `TypeError`).
Verified: `python -c "import parrot.clients.base"` succeeds (no import cycle);
`pytest packages/ai-parrot/tests/unit/clients/test_token_budget_boundaries.py -v` → 10 passed;
`pytest packages/ai-parrot/tests/unit/clients -q` → 397 passed / 1 pre-existing unrelated
failure; `pytest packages/ai-parrot-client-amazon/tests/unit -q` → 30 passed (thin subclasses
inherit wrapped methods without re-wrapping, confirmed); broader regression sweep —
`packages/ai-parrot/tests/unit/bots` (322 passed / 5 pre-existing failures, confirmed
byte-identical on `dev` HEAD before this feature) and all four spot-checked satellite client
packages (anthropic/google/openai/groq, all green) — to cover the foundational-file risk this
task itself calls out; `ruff check` clean on both files after the E402 fix.
Note: a separate automated post-commit hook ("style: apply black formatting (post
sdd-worker)") swept my manual review fixes (the `_BUDGETED_METHODS` relocation and the added
test) into its own commit alongside genuine black reformatting of unrelated pre-existing code
in the same files. Content verified correct either way; re-ran the full acceptance-criteria
suite after that commit to confirm.

**Deviations from spec**: none

Seat: qwen (attempt 1, timed out after 552.7s) → gemini (attempt 2, succeeded) · Backend: nova →
google-compat · Model: qwen.qwen3-coder-480b-a35b-instruct → gemini-3.5-flash · Attempts: 2 ·
Duration: 552.7s + 209.0s · Tokens: 3036738 in / 13036 out (gemini attempt) · Orchestrator senior
review + 2 fixes (misplaced module-level constant, missing required test) on top.
