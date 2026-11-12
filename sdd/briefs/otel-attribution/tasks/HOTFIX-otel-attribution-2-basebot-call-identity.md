# HOTFIX-otel-attribution-2: Shared call-identity helper on BaseBot; tenant in conversation() and invoke()

**Feature**: otel-attribution — tag every agent LLM call's OTel telemetry with agent and tenant
**Spec**: `sdd/briefs/otel-attribution.brief.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Telemetry identity comes from two ContextVars captured on lifecycle events: `current_agent_name` and
`current_tenant`. `BaseBot` binds the agent name in all four entry points (`conversation` `bots/base.py:240`,
`invoke` `:697`, `ask` `:1128`, `ask_stream` `:1911`) but the tenant only in `ask` / `ask_stream`
(`:1151-1153`, `:1927-1929`), through the module-level resolver `_resolve_call_tenant` (`:48`).
Calls through `conversation()` / `invoke()` therefore carry no tenant, and agents that override `ask()`
(HOTFIX-otel-attribution-3) have no reusable way to bind either value. This task adds one shared helper and
uses it for the missing tenant binding.

## Scope

In `packages/ai-parrot/src/parrot/bots/base.py`:

1. Module level:
   - `import functools` and `from contextvars import Token` (`inspect` is already imported at `:10`;
     `NamedTuple` comes from `typing`, extend the import at `:8`).
   - `class CallIdentityTokens(NamedTuple)` with fields `agent: Token` and `tenant: Optional[Token]` (docstring).
   - `def with_call_identity(method)` — decorator for **coroutine** entry points that bypass `BaseBot.ask`.
     It resolves `tenant` and `ctx` from the call via `inspect.signature(method).bind_partial(self, *args, **kwargs)`:
     a named `tenant`/`ctx` parameter if the method declares one, otherwise the same key inside the method's
     `**kwargs` parameter (find its name from the signature's `VAR_KEYWORD` parameter; do not assume `kwargs`).
     It calls `self._bind_call_identity(tenant, ctx)`, awaits the method, and calls
     `self._reset_call_identity(tokens)` in `finally`. Use `functools.wraps`. It must never remove
     `tenant` or `ctx` from the arguments it forwards.
2. On `BaseBot`:
   - `def _bind_call_tenant(self, tenant: Optional[str], ctx: Any) -> Optional[Token]` — returns
     `current_tenant.set(t)` for `t = _resolve_call_tenant(tenant, ctx)`, or `None` when `t is None`
     (preserving an enclosing binding, the existing semantics).
   - `def _bind_call_identity(self, tenant: Optional[str] = None, ctx: Any = None) -> CallIdentityTokens` —
     when `ctx is None` use `_current_ctx.get()`; bind `current_agent_name` to `self.name`, then the tenant
     via `_bind_call_tenant`.
   - `@staticmethod def _reset_call_identity(tokens: Optional[CallIdentityTokens]) -> None` — no-op for
     `None`; otherwise reset the tenant token (if any) and then the agent token (reverse order).
3. `ask()` and `ask_stream()`: replace the three lines
   ```python
               _call_tenant = _resolve_call_tenant(tenant, ctx)
               if _call_tenant is not None:
                   _generic_tenant_token = current_tenant.set(_call_tenant)
   ```
   (`:1151-1153` and `:1927-1929`) with `_generic_tenant_token = self._bind_call_tenant(tenant, ctx)`.
   Their existing resets (`current_tenant.reset(_generic_tenant_token)` at `:1865`, `:2376`), the agent binding
   and the skill-tenant (`_enter_skill_tenant`) handling are unchanged.
4. `conversation()`: after `_memkey_token = current_memory_key_id.set(self.memory_key_id)` (`:243`) and before
   `try:` (`:244`), add `_tenant_token = self._bind_call_tenant(kwargs.get("tenant"), ctx if ctx is not None else _current_ctx.get())`.
   In its `finally` (`:267`), reset it first: `if _tenant_token is not None: current_tenant.reset(_tenant_token)`.
5. `invoke()`: pre-declare `_tenant_token = None` with the other tokens (`:701`); inside `try`, right after
   `ctx = _current_ctx.get()` (`:705`), add `_tenant_token = self._bind_call_tenant(kwargs.get("tenant"), ctx)`.
   In its `finally` (`:866`), reset it before `current_memory_key_id`.
6. Tests: extend `tests/unit/bots/test_current_tenant_binding.py`.

**NOT in scope**: applying the decorator to any agent (HOTFIX-otel-attribution-3), changing
`_resolve_call_tenant`'s precedence, popping `tenant` from `kwargs`, any telemetry module.

## Files to Create / Modify

| File | Action | What |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/base.py` | MODIFY | helper, decorator, ask/ask_stream refactor, tenant in conversation/invoke |
| `packages/ai-parrot/tests/unit/bots/test_current_tenant_binding.py` | MODIFY | new cases |

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# already in packages/ai-parrot/src/parrot/bots/base.py
import inspect                                                    # :10
from typing import Optional, Union, Type, AsyncIterator, Any, List  # :8 (add NamedTuple)
from ..utils.helpers import RequestContext, _current_ctx          # :22
from parrot.observability.context import (current_agent_name, ..., current_tenant, ...)  # :77-81
# to add
import functools
from contextvars import Token
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/bots/base.py
def _resolve_call_tenant(tenant: Optional[str], ctx: Any) -> Optional[str]   # :48
class BaseBot(AbstractBot):                                                   # :94
    async def conversation(self, question, ..., ctx: Optional[RequestContext] = None, ..., **kwargs)  # :177 (ctx :192)
    async def invoke(self, question, ..., ctx: Optional[RequestContext] = None, ..., **kwargs)        # :671 (ctx :678)
    async def ask(self, question, ..., ctx=None, ..., tenant: Optional[str] = None, ...)             # :1069 (tenant :1091)
    async def ask_stream(self, question, ..., ctx=None, ..., tenant: Optional[str] = None, ...)      # :1878 (tenant :1898)
```

Verbatim anchors:
- `:240` `_agent_token = current_agent_name.set(self.name)` (conversation); `:267-271` its `finally`.
- `:697` `_agent_token = current_agent_name.set(self.name)` (invoke); `:703-705` `try:` / `if ctx is None:` /
  `ctx = _current_ctx.get()`; `:866-875` its `finally`.
- `:1151-1153` and `:1927-1929` the three tenant lines quoted in Scope step 3.

### Does NOT Exist

- ~~`BaseBot._bind_call_tenant`~~, ~~`BaseBot._bind_call_identity`~~, ~~`BaseBot._reset_call_identity`~~,
  ~~`CallIdentityTokens`~~, ~~`with_call_identity`~~ — created here.
- ~~`tenant` parameter on `conversation()` / `invoke()`~~ — it arrives (if at all) in `**kwargs`; do not add a parameter.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/bots/base.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/unit/bots/test_current_tenant_binding.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/bots/base.py#_resolve_call_tenant",
    "sym:packages/ai-parrot/src/parrot/bots/base.py#BaseBot",
    "sym:packages/ai-parrot/src/parrot/bots/base.py#BaseBot.conversation",
    "sym:packages/ai-parrot/src/parrot/bots/base.py#BaseBot.invoke",
    "sym:packages/ai-parrot/src/parrot/bots/base.py#BaseBot.ask",
    "sym:packages/ai-parrot/src/parrot/bots/base.py#BaseBot.ask_stream"
  ]
}
```

---

## Implementation Notes

### Key Constraints

- Token-based `set`/`reset` is what makes nested agents restore the outer identity (FEAT-228). Every token
  you create must be reset exactly once, in a `finally`, in reverse order.
- `_bind_call_tenant` returning `None` means "leave the enclosing tenant in place"; never set `None` explicitly.
- `with_call_identity` is for coroutines only. Async generators (VoiceBot) bind inline in their existing
  `try/finally` (HOTFIX-otel-attribution-3).
- `bots/base.py` is large; change only the lines listed.

## Implementation Blueprint

### Steps (in order)

1. Imports, `CallIdentityTokens`, `with_call_identity` (module level, after `_resolve_call_tenant`).
2. The three `BaseBot` methods (near the other private helpers; keep Google-style docstrings).
3. Refactor `ask()` / `ask_stream()` tenant lines.
4. Tenant binding in `conversation()` and `invoke()`.
5. Tests.

### FILL IN checklist

- [ ] `with_call_identity` resolves `tenant`/`ctx` from named params or the var-keyword dict.
- [ ] `ask` / `ask_stream` behaviour unchanged (existing tests pass untouched).
- [ ] `conversation()` / `invoke()` bind and reset the tenant.

## Acceptance Criteria

- [ ] `conversation(..., tenant="t1")` and `invoke(..., tenant="t1")` observe `current_tenant.get() == "t1"` inside
      the call, and `None` after it returns or raises.
- [ ] A `RequestContext` whose `kwargs["tenant"] == "t2"` (passed as `ctx`) binds `"t2"` when no explicit tenant is given.
- [ ] `_bind_call_identity` / `_reset_call_identity` restore an enclosing agent name and tenant.
- [ ] A coroutine decorated with `with_call_identity` sees `current_agent_name.get() == bot.name` and the tenant from a
      named `tenant` parameter or from `**kwargs`, and the arguments it receives are unchanged.
- [ ] Existing cases in `test_current_tenant_binding.py` pass unmodified.
- [ ] `ruff check packages/ai-parrot/src/parrot/bots/base.py` reports nothing new.

## Validation Commands

- `pytest packages/ai-parrot/tests/unit/bots/test_current_tenant_binding.py -q`
- `pytest packages/ai-parrot/tests/unit/clients/test_client_emits_agent_name.py -q`

## Test Specification

```python
# packages/ai-parrot/tests/unit/bots/test_current_tenant_binding.py — add:
# - test_conversation_binds_tenant: stub bot._conversation_body to record current_tenant.get() and raise;
#   await bot.conversation("hi", tenant="t1"); assert seen == ["t1"] and current_tenant.get() is None.
# - test_invoke_binds_tenant: stub bot.create_system_prompt (called inside invoke's try, base.py:782) the same way.
# - test_invoke_tenant_from_request_context: pass ctx=RequestContext(...) carrying kwargs={"tenant": "t2"}
#   (check RequestContext's constructor in parrot/utils/helpers.py first).
# - test_bind_and_reset_call_identity_restore_outer_values: set outer agent/tenant, bind, reset, assert restored.
# - test_with_call_identity_named_and_var_keyword_tenant: decorate two local async functions
#   (one with a `tenant` param, one taking **extra) and call them with a make_bot() instance as `self`.
# Reuse the make_bot fixture (tests/unit/bots/conftest.py:318) and the _ASK_KWARGS style already in the file.
```

## Agent Instructions

1. Work in the brief worktree (`fix-otel-attribution-otel-attribution`), never on `dev`.
2. Read `sdd/briefs/otel-attribution.brief.md`.
3. Verify the anchors above; if one moved, update this file first.
4. Mark this task `in-progress` in `sdd/briefs/otel-attribution.index.json` and commit only that file.
5. Implement; run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`.
6. Commit only the two files above: `fix(otel-attribution): HOTFIX-otel-attribution-2 — BaseBot call-identity helper`.
7. Close with `parrot sdd task close HOTFIX-otel-attribution-2 otel-attribution verified`, fill in the
   Completion Note, commit the SDD state.

---

## Completion Note

**Completed by**: sdd-worker (orchestrator) with gpt-5.6-sol (codex), 1 attempt
**Date**: 2026-11-12
**Status**: done-with-issues
**Notes**: Shared call-identity helper on BaseBot (bots/base.py) and tenant binding in conversation()/invoke(); tests extended in tests/unit/bots/test_current_tenant_binding.py. Commits: lint db65ac689e, merge 24914e5e66. Task 3 (needs this helper) is not done.

Merge-tier validation did NOT settle green: the engine runs ended `timed_out` (second run exit -15/SIGTERM after ~1 min, no pytest summary; the first two runs ended `timed_out` with exit 0). No failure was observed in the tests that did run, and the cause of the stall is unidentified. Accepted by the operator as done-with-issues.

Three failing tests seen in the first validation log are NOT caused by this brief (static diff evidence vs origin/dev, not a baseline run): `test_agent_name_is_not_pii_field` -> issue:ea9f2f8ab334 (`user_id` already declared on AfterClientCallEvent on dev; this brief adds only `tenant`); `test_live_envelope.py::TestCanonicalRole` x2 -> issue:33b76e470d2b (stream_voice role handling untouched by this brief).

**Deviations from spec**: none in scope
**Status promoted to `done` (2026-11-12)** on the user's explicit instruction. The caveats above (unrun merge-tier validation, three known failing tests `issue:ea9f2f8ab334` / `issue:33b76e470d2b`, deferred review findings `issue:4591f0dd1f03` / `issue:6c08bea1a8b2` / `issue:2e7011858c08` / `issue:a694582dbb67`) still apply.
