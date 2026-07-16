---
type: Wiki Overview
title: 'TASK-1501: Bind agent identity around bot invocations'
id: doc:sdd-tasks-active-task-1501-bot-invocation-wrapping-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Spec §2 Overview, §3 Module 3. The ContextVar from TASK-1499 must be SET
  for the
relates_to:
- concept: mod:parrot.observability.context
  rel: mentions
---

# TASK-1501: Bind agent identity around bot invocations

**Feature**: FEAT-228 — Per-Agent Cost & Usage Metrics
**Spec**: `sdd/specs/per-agent-cost-usage-metrics.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1499
**Assigned-to**: unassigned

---

## Context

Spec §2 Overview, §3 Module 3. The ContextVar from TASK-1499 must be SET for the
duration of every bot invocation, so any LLM client call made within observes
the correct agent name. This wraps the four public invocation entry points on
`AbstractBot` (and any `Agent` override paths that bypass them).

---

## Scope

- In `bots/base.py`, wrap the body of the four public invocation methods with
  `with agent_identity(self.name):` — `conversation` (line 123), `invoke`
  (line 501), `ask` (line 727), `ask_stream` (line 1310).
- For `ask_stream` (an async generator), ensure the `with` scope encloses the
  full generator body so the ContextVar stays bound while chunks are produced
  and the After event is emitted.
- Inspect `bots/agent.py`: if its invoke paths (which emit `BeforeInvokeEvent`
  at lines 364, 586) do NOT delegate to `bots/base.py`'s wrapped methods, apply
  `agent_identity(self.name)` there too. If they DO delegate, no change needed —
  document which in the Completion Note.

**NOT in scope**: the ContextVar definition (TASK-1499), reading it in the
client (TASK-1502).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/base.py` | MODIFY | Wrap `conversation`/`invoke`/`ask`/`ask_stream` bodies |
| `packages/ai-parrot/src/parrot/bots/agent.py` | MODIFY (if needed) | Wrap invoke paths that bypass base |
| `packages/ai-parrot/tests/.../test_agent_identity_binding.py` | CREATE | Assert the var is bound to `self.name` during a call |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.observability.context import agent_identity  # created by TASK-1499
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/abstract.py
class AbstractBot(...):
    name: str   # line 321: self.name = name  (ctor arg default 'Nav' line 249)

# packages/ai-parrot/src/parrot/bots/base.py  — wrap these four:
async def conversation(self, ...)  # line 123  (emits BeforeInvokeEvent(agent_name=self.name) ~line 197)
async def invoke(self, ...)        # line 501
async def ask(self, ...)           # line 727
async def ask_stream(self, ...)    # line 1310  (async generator)

# packages/ai-parrot/src/parrot/bots/agent.py
#   emits BeforeInvokeEvent(agent_name=self.name) at lines 364, 586 — check
#   whether these run inside a base.py wrapped method or a separate path.
```

### Does NOT Exist
- ~~a global/instance attribute already holding the active agent name~~ — must
  use the ContextVar from TASK-1499.
- ~~`self.agent_name`~~ — the attribute is `self.name`, not `agent_name`.

---

## Implementation Notes

### Pattern to Follow
```python
async def ask(self, question, ...):
    with agent_identity(self.name):
        ...  # entire existing body, including the LLM client call(s)

async def ask_stream(self, question, ...):
    with agent_identity(self.name):
        ...
        async for chunk in ...:
            yield chunk
```

### Key Constraints
- The `with` block must enclose ALL LLM client calls and event emission, not
  just the prologue. Place it as the outermost statement of the method body.
- Nested invocations (a bot that calls another bot) are safe: each pushes its
  own token; TASK-1499's reset restores the parent's value.
- ContextVars copy into tasks spawned by `asyncio.create_task`, so fire-and-forget
  emission inside the scope still captures the value.
- Do not change method signatures or behavior — purely additive wrapping.

---

## Acceptance Criteria

- [ ] During `ask`/`ask_stream`/`invoke`/`conversation`, `current_agent_name.get()` equals `self.name`.
- [ ] After the call returns (or the stream is exhausted), the var reverts to its prior value.
- [ ] `Agent` subclass invocations are covered (either via base delegation or explicit wrap — documented).
- [ ] No change to method signatures or return values; existing bot tests still pass.
- [ ] `ruff check` passes.

---

## Test Specification

```python
async def test_ask_binds_agent_name(stub_bot):
    # stub_bot.name == "porygon"; patch the LLM client to assert inside the call
    seen = {}
    async def fake_completion(*a, **k):
        from parrot.observability.context import current_agent_name
        seen["name"] = current_agent_name.get()
        return ...  # minimal response
    stub_bot._client.completion = fake_completion
    await stub_bot.ask("hi")
    assert seen["name"] == "porygon"
    from parrot.observability.context import current_agent_name
    assert current_agent_name.get() is None  # reverted
```

---

## Agent Instructions

Standard SDD flow. Read the spec §7 (gotchas re: `emit_nowait`, streaming, and
agent.py emit sites) before implementing. Move to `completed/` and update index.

---

## Completion Note

**Completed by**:
**Date**:
**Notes**: (state whether agent.py needed an explicit wrap or delegates to base)
**Deviations from spec**: none
