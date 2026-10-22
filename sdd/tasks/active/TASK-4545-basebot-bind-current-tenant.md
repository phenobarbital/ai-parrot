# TASK-4545: Bind current_tenant on every ask()/ask_stream()

**Feature**: FEAT-710 — Parrot telemetry event fan-out
**Spec**: `sdd/specs/parrot-telemetry-event-fanout.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M
**Depends-on**: TASK-4544
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 1. Today the tenant is bound only by the skill mixin and only for `tenant_based` bots (`bots/base.py:1118-1120`, `:1874-1876`). Telemetry needs the tenant for every bot, so `BaseBot.ask()` and `ask_stream()` bind `current_tenant` themselves.

---

## Scope

- In `BaseBot.ask()` and `BaseBot.ask_stream()`, before the `_enter_skill_tenant` call, bind `current_tenant` from `tenant` → `ctx.kwargs["tenant"]`; when both are `None`, leave the outer value untouched (no set).
- Reset it in the matching `finally`, AFTER the skill-tenant reset (reverse order of binding).
- Write tests: plain (non-skill) bot, nested asks, and a FEAT-707 regression (non-`tenant_based` skill bot ignores the tenant for skill views).

**NOT in scope**: putting the tenant on events (TASK-4549/TASK-4548); `conversation()` / `invoke()` (they inherit the ContextVar).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/base.py` | MODIFY | Bind/reset current_tenant in ask and ask_stream |
| `packages/ai-parrot/tests/unit/bots/test_current_tenant_binding.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

Verified against `origin/dev` @ `cf1888270` (2026-10-21). Re-run every `grep -c` before editing.

### Verified Imports
```python
from parrot.observability.context import current_tenant  # created by TASK-4544
from parrot.observability.context import (current_agent_name, current_user_id, ...)  # verified: bots/base.py:61-65
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/base.py
async def ask(self, question, ..., tenant=..., ctx=..., **kwargs)          # :1037
_tenant_token = None                                                        # :1101 (ask)
_enter = getattr(self, "_enter_skill_tenant", None)                        # :1118 (ask), :1874 (ask_stream)
_tenant_token = _enter(tenant, ctx)                                         # :1120 (ask), :1876 (ask_stream)
# finally (ask :1808-1813, ask_stream :2289-2294):
_exit = getattr(self, "_exit_skill_tenant", None)
if _exit is not None and _tenant_token is not None:
    _exit(_tenant_token)
async def ask_stream(self, ...)                                             # :1826
# packages/ai-parrot/src/parrot/skills/mixin.py:135  _resolve_tenant(explicit, ctx) — returns None when not tenant_based (:152)
```

### Does NOT Exist
- ~~`BaseBot._bind_tenant`~~ — no such helper; add a private one only if both methods share it
- ~~`RequestContext.tenant`~~ — the tenant lives in `ctx.kwargs["tenant"]`

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/bots/base.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/unit/bots/test_current_tenant_binding.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/bots/base.py#BaseBot.ask",
    "sym:packages/ai-parrot/src/parrot/bots/base.py#BaseBot.ask_stream",
    "sym:packages/ai-parrot/src/parrot/skills/mixin.py#SkillRegistryMixin._resolve_tenant"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Async-first; never block the event loop; `self.logger`, never `print`.
- Telemetry must never raise into the request path.
- Touch only the files listed above.

---

## Implementation Blueprint

### Steps (in order)
1. Add a module-level helper `_resolve_call_tenant(tenant, ctx)` — *why*: ask and ask_stream must resolve identically.
2. In both methods, declare `_generic_tenant_token = None` next to `_tenant_token = None`, then bind before the `_enter = getattr(self, "_enter_skill_tenant", None)` line — *why*: the skill mixin's validated bind runs after and wins for `tenant_based` bots.
3. In both `finally` blocks, reset the generic token right after the skill-tenant reset — *why*: tokens must be reset in reverse order.

### `packages/ai-parrot/src/parrot/bots/base.py` (MODIFY)
```python
# occurrences: 2 (verified: grep -c '_enter = getattr(self, "_enter_skill_tenant", None)' packages/ai-parrot/src/parrot/bots/base.py)
# FILL IN: disambiguate — apply once in ask() (≈:1116-1120, after `ctx = _current_ctx.get()`) and once in
#          ask_stream() (≈:1872-1876); quote the surrounding `if ctx is None:` lines to anchor each.
_generic_tenant_token = None
_call_tenant = _resolve_call_tenant(tenant, ctx)
if _call_tenant is not None:
    _generic_tenant_token = current_tenant.set(_call_tenant)
```
```python
# module-level helper (near the other module helpers)
def _resolve_call_tenant(tenant: Optional[str], ctx: Any) -> Optional[str]:
    """FEAT-710: explicit ``tenant`` wins, else ``ctx.kwargs["tenant"]``, else None (keep outer binding)."""
    if tenant is not None:
        return tenant
    ctx_kwargs = getattr(ctx, "kwargs", None) if ctx is not None else None
    if isinstance(ctx_kwargs, dict):
        return ctx_kwargs.get("tenant")
    return None
```
```python
# occurrences: 2 (verified: grep -c '_exit(_tenant_token)' packages/ai-parrot/src/parrot/bots/base.py)
# AFTER each `_exit(_tenant_token)` (ask ≈:1811, ask_stream ≈:2292):
if _generic_tenant_token is not None:
    current_tenant.reset(_generic_tenant_token)
```
**Why**: `_generic_tenant_token` must be declared before the `try` (like `_tenant_token`) so the `finally` never hits an unbound name. `# FILL IN: place the declaration next to `_tenant_token = None` in each method` — bounded by AC-3.

### `packages/ai-parrot/tests/unit/bots/test_current_tenant_binding.py` (CREATE)
```python
"""FEAT-710 TASK-4545 — BaseBot binds current_tenant on every call."""
import pytest

from parrot.observability.context import current_tenant


@pytest.mark.asyncio
async def test_plain_bot_sees_tenant_inside_ask() -> None:
    # FILL IN: build a minimal BaseBot double (see tests/unit/bots/test_agent_identity_binding.py for the pattern)
    #          whose LLM call records current_tenant.get(); assert "t1" inside, None after — AC-1
    raise NotImplementedError


@pytest.mark.asyncio
async def test_nested_ask_restores_outer_tenant() -> None:
    # FILL IN: outer tenant "a", inner ask(tenant="b"), outer value restored — AC-2
    raise NotImplementedError


def test_resolve_call_tenant_precedence() -> None:
    from parrot.bots.base import _resolve_call_tenant

    class _Ctx:
        kwargs = {"tenant": "from-ctx"}

    assert _resolve_call_tenant("explicit", _Ctx()) == "explicit"
    assert _resolve_call_tenant(None, _Ctx()) == "from-ctx"
    assert _resolve_call_tenant(None, None) is None
```

### FILL IN checklist
- [ ] Disambiguated insertion in ask and ask_stream — AC-1
- [ ] Declarations before `try` — AC-3
- [ ] Two async test bodies — AC-1, AC-2

---

## Acceptance Criteria

- [ ] A non-`tenant_based` bot sees `current_tenant == tenant` inside `ask()` and `ask_stream()`, and `None` after.
- [ ] Nested calls restore the outer tenant.
- [ ] No `UnboundLocalError` when the call fails before binding.
- [ ] FEAT-707 skill-view tests still pass.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/unit/bots/test_current_tenant_binding.py -q`
- `pytest packages/ai-parrot/tests/unit/bots/test_agent_identity_binding.py -q`

---

## Test Specification

See the test-file block in the Implementation Blueprint; every `FILL IN` test must pass.

---

## Agent Instructions

1. Work in the feature worktree, never on `dev`:
   `python -m scripts.sdd.ensure_worktree --slug parrot-telemetry-event-fanout --feature-id FEAT-710`
2. Read the spec `sdd/specs/parrot-telemetry-event-fanout.spec.md` (rev 0.4) for context.
3. Check that every `Depends-on` task is `done` in `sdd/tasks/index/parrot-telemetry-event-fanout.json`.
4. Verify the Codebase Contract before writing code (re-run `grep -c` on every anchor); fix the contract first if it drifted.
5. Set this task `in-progress` in the index and commit only that file.
6. Implement from the Blueprint, completing every `# FILL IN:`; never change a fixed signature or path.
7. Run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-server/src`.
8. Commit only the files listed in this task.
9. Close with `scripts/sdd/close_task.sh TASK-4545 parrot-telemetry-event-fanout verified`.
10. Fill in the Completion Note and commit the staged SDD state.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
