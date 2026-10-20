# TASK-4496: `tenant` parameter and binding hooks in `ask()` / `ask_stream()`

**Feature**: FEAT-707 — Per-Tenant Skills for `SkillRegistryMixin`
**Spec**: `sdd/specs/per-tenant-skills.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 6 and design-research S1. Today a `tenant=` kwarg would fall
into `**kwargs` and could leak into downstream LLM arguments. This task makes
`tenant` a named parameter consumed at the boundary and calls the mixin's
cooperative hooks `_enter_skill_tenant(tenant, ctx)` / `_exit_skill_tenant(token)`
around the whole call — exactly like the FEAT-228 `current_agent_name` binding.
The hooks are looked up with `getattr`, so bots without `SkillRegistryMixin`
are untouched and this task has no dependency on TASK-4499 (tests use a stub hook).

---

## Scope

- Add `tenant: Optional[str] = None` to `BaseBot.ask()` and `BaseBot.ask_stream()` (after `trace_context`, before `**kwargs`).
- In each, right after `ctx` is resolved (`if ctx is None: ctx = _current_ctx.get()`), call the hook if present and keep the token in a local.
- Reset in the existing `finally`, next to `current_agent_name.reset(_agent_token)`.
- Document the parameter in both docstrings.
- Write `packages/ai-parrot/tests/unit/test_ask_tenant_binding.py`.

**NOT in scope**: the hooks' implementation (TASK-4499), other `ask`-like methods (`invoke`, `conversation`), handlers (TASK-4497).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/base.py` | MODIFY | `tenant` param + hook calls in `ask` and `ask_stream` |
| `packages/ai-parrot/tests/unit/test_ask_tenant_binding.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.bots.base import BaseBot                     # verified: bots/base.py (class defining ask at :1037)
from parrot.utils.helpers import RequestContext          # verified: utils/helpers.py:7
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/base.py
async def ask(self, question: str, ..., use_tools: bool = True, trace_context=None, **kwargs) -> AIMessage:   # 1037-1060
    _agent_token = current_agent_name.set(self.name)                     # 1093
    try:
        if ctx is None:
            ctx = _current_ctx.get()                                     # 1107-1108
        ...
    finally:
        ...
        current_agent_name.reset(_agent_token)  # FEAT-228              # 1806
async def ask_stream(self, question: str, ..., use_tools: bool = True, trace_context=None, **kwargs
                     ) -> AsyncIterator[Union[str, AIMessage]]:          # 1808-1829
    _agent_token = current_agent_name.set(self.name)                     # 1836
    try:
        if ctx is None:
            ctx = _current_ctx.get()                                     # 1843-1844
        ...
    finally:
        ...
        current_agent_name.reset(_agent_token)  # FEAT-228              # 2263
```
`ask_stream` is an async generator: its `finally` runs when iteration ends, raises, or the consumer calls `aclose()` — so the token naturally lives for the whole stream.

### Does NOT Exist
- ~~`BaseBot.ask(tenant=...)`~~ — added here.
- ~~`BaseBot._enter_skill_tenant` / `_exit_skill_tenant`~~ — defined on `SkillRegistryMixin` by TASK-4499; here only looked up with `getattr`.
- ~~A single unique anchor for `ctx = _current_ctx.get()`~~ — it appears 3× in base.py (675, 1108, 1844); anchor by enclosing method.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/bots/base.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/unit/test_ask_tenant_binding.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/bots/base.py#BaseBot.ask",
    "sym:packages/ai-parrot/src/parrot/bots/base.py#BaseBot.ask_stream"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- `tenant` must never be forwarded in `**kwargs` (spec S1) — it is a named param, so Python already consumes it.
- Declare `_tenant_token = None` next to `_user_token = _session_token = _memkey_token = None` so the `finally` is safe if the try raises early.
- Exceptions from the hook (e.g. `ValueError` for an invalid tenant) must propagate (AC-R2: `ask()` fails fast) — but only after the `finally` resets everything bound so far.

---

## Implementation Blueprint

### Steps (in order)
1. Add the parameter to both signatures — *why*: consume `tenant` at the boundary (S1).
2. Pre-declare `_tenant_token = None` in both methods — *why*: safe `finally`.
3. Call the hook right after `ctx` resolution in both — *why*: precedence needs `ctx.kwargs` (spec AC-R1).
4. Reset in both `finally` blocks — *why*: per-task isolation (AC-V3).
5. Tests with a stub bot.

### `packages/ai-parrot/src/parrot/bots/base.py` (MODIFY) — signatures
```python
# occurrences of `        trace_context=None,`: 4 (verified: grep -c) → disambiguate by context:
# ask (base.py:1057-1060):
        use_tools: bool = True,
        trace_context=None,
        tenant: Optional[str] = None,
        **kwargs,
    ) -> AIMessage:
# ask_stream (base.py:1827-1829; `) -> AsyncIterator[Union[str, AIMessage]]:` occurs 1×):
        trace_context=None,
        tenant: Optional[str] = None,
        **kwargs,
    ) -> AsyncIterator[Union[str, AIMessage]]:
# FILL IN: add `tenant:` to both Args docstrings — "Per-tenant skill scope (FEAT-707); consumed here,
#          never forwarded. Ignored by bots without SkillRegistryMixin." — bounded by Google docstrings
```

### `base.py` (MODIFY) — binding (repeat in ask and ask_stream)
```python
# anchor (3 occurrences in base.py — use the one inside the method being edited):
#            if ctx is None:
#                ctx = _current_ctx.get()
# AFTER — insert directly below those two lines (ask: base.py:1107-1108; ask_stream: base.py:1843-1844)
            _enter = getattr(self, "_enter_skill_tenant", None)
            if _enter is not None:
                _tenant_token = _enter(tenant, ctx)

# and the pre-declaration, next to the existing
#        _user_token = _session_token = _memkey_token = None
# (ask ≈ base.py:1096; ask_stream ≈ base.py:1839):
        _tenant_token = None

# BEFORE `            current_agent_name.reset(_agent_token)  # FEAT-228` inside each method's finally
# (ask: base.py:1806; ask_stream: base.py:2263 — 3 occurrences with the comment; 844 belongs to another method):
            _exit = getattr(self, "_exit_skill_tenant", None)
            if _exit is not None and _tenant_token is not None:
                _exit(_tenant_token)
```
**Why**: same lifetime as `current_agent_name` (spec §2 Overview); `getattr` keeps non-mixin bots untouched (AC-B1).

### `packages/ai-parrot/tests/unit/test_ask_tenant_binding.py` (CREATE)
```python
"""FEAT-707 — tenant binding in ask()/ask_stream() (TASK-4496)."""
import pytest

# FILL IN: build the smallest BaseBot subclass the existing unit tests already use for ask() —
#          look for a fake-client fixture in packages/ai-parrot/tests/unit/conftest.py or an existing
#          test that calls BaseBot.ask with a mocked client; reuse it rather than inventing one.
#          The bot gets stub `_enter_skill_tenant(tenant, ctx)` (records args, binds a ContextVar,
#          returns its token) and `_exit_skill_tenant(token)`; a tool/LLM stub reads the ContextVar.
# Tests:
#  test_ask_binds_and_resets_tenant
#  test_ask_passes_ctx_to_hook (ctx=RequestContext(tenant="x") reaches the hook)
#  test_ask_reset_on_exception
#  test_ask_hook_value_error_propagates
#  test_ask_stream_holds_tenant_across_iteration (value visible while consuming chunks)
#  test_ask_stream_reset_on_aclose
#  test_non_mixin_bot_ignores_tenant_kwarg (no hook attrs; tenant not in the client call kwargs)
# — bounded by AC-R1, AC-R2, AC-V3, AC-B1
```

### FILL IN checklist
- [ ] docstrings
- [ ] test fixture reuse + seven tests

---

## Acceptance Criteria

- [ ] `tenant` is a named parameter of both methods and never reaches `**kwargs`/the client call.
- [ ] Hook called once per call with `(tenant, ctx)`; token reset in `finally` on success, exception and `aclose()`.
- [ ] Bots without the hooks behave exactly as before.
- [ ] `ruff check` clean.

## Validation Commands

- `pytest packages/ai-parrot/tests/unit/test_ask_tenant_binding.py -q`

---

## Test Specification

See the CREATE block.

---

## Agent Instructions

1. **Work in the feature worktree** (`python -m scripts.sdd.ensure_worktree --slug per-tenant-skills --feature-id FEAT-707`).
2. **Read the spec** §3 Module 6, §7 (ContextVar gotchas).
3. **Check dependencies**: none.
4. **Verify the Codebase Contract** — re-locate each anchor inside the right method; line numbers drift.
5. **Update status** → `"in-progress"`; commit only the index file.
6. **Implement** from the blueprint.
7. **Validate** with `PYTHONPATH=packages/ai-parrot/src`.
8. **Commit code** — only the listed files.
9. **Close** with `scripts/sdd/close_task.sh TASK-4496 per-tenant-skills verified`.
10. **Fill in the Completion Note** and commit the SDD state.

---

## Completion Note


- Task: TASK-4496
- Feature: per-tenant-skills
- Implementation SHA: a2440c6aa43e008523bbe06c3eb3a56770636843
- Closed at (UTC): 2026-10-19T21:27:15+00:00
- Fix commits: none

| Metric | Value |
|---|---|
| validation_refs | 1 |
| fix_commits | 0 |
| seat_summary | Seat: sonnet · Backend: native · Model: sonnet · Attempts: 1 · Duration: 380s · Tokens: n/a |
