---
type: Wiki Overview
title: 'TASK-1381: SuspendingWebHumanTool (REST suspend tool)'
id: doc:sdd-tasks-completed-task-1381-suspending-web-human-tool-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'Spec §3 Module 3 + the resolved SUSPEND-selection decision (§8): a deployment
  opts'
relates_to:
- concept: mod:parrot.handlers.web_hitl
  rel: mentions
- concept: mod:parrot.human
  rel: mentions
---

# TASK-1381: SuspendingWebHumanTool (REST suspend tool)

**Feature**: FEAT-204 — HITL over Stateless Web Request/Response (AgentTalk HTTP)
**Spec**: `sdd/specs/hitl_web.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1379
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3 + the resolved SUSPEND-selection decision (§8): a deployment opts
into suspend mode via an **explicit dedicated tool**, not a global flag or magic
auto-detect. This task adds `SuspendingWebHumanTool` — a `WebHumanTool` subclass
that wires `wait_strategy=SUSPEND` — sibling to the existing blocking
`WebHumanTool` (WebSocket long-poll). Both coexist; agents are wired with one or
the other at construction.

---

## Scope

- Add `SuspendingWebHumanTool(WebHumanTool)` in
  `packages/ai-parrot-server/src/parrot/handlers/web_hitl.py`.
- It sets `wait_strategy=WaitStrategy.SUSPEND` (passed to / set on the base
  `HumanTool`) and otherwise reuses `WebHumanTool`'s lazy manager resolution and
  `current_web_session`-based target resolution.
- Export it from the module's public surface (and any `__all__` if present).
- Unit test that the tool reports `SUSPEND` and reuses target resolution.

**NOT in scope**: the enum/field/SUSPEND branch (TASK-1379 — this task consumes
it); the handler catch (TASK-1382); the store (TASK-1380).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/web_hitl.py` | MODIFY | Add `SuspendingWebHumanTool` subclass + export |
| `packages/ai-parrot-server/tests/test_suspending_web_human_tool.py` | CREATE | Unit test |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.human import WaitStrategy          # added by TASK-1379 (verify it exists before use)
from parrot.human import HumanTool             # human/__init__.py
# within web_hitl.py module scope:
#   class WebHumanTool(HumanTool)  is already defined in this same file
```

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/handlers/web_hitl.py
current_web_session: ContextVar[Optional[str]]            # 53
def get_current_web_session() -> Optional[str]            # 58
class WebHumanTool(HumanTool):                            # 100-197
    def __init__(self, *, default_targets=None, source_agent=None, **kwargs):  # 121-135
        super().__init__(manager=None, default_channel="web",
                         default_targets=default_targets or [],
                         source_agent=source_agent, **kwargs)
    async def _execute(self, **kwargs) -> Any: ...        # 137-197  (lazy manager + target resolution,
                                                          #   then calls super()._execute())
```

### Does NOT Exist
- ~~`SuspendingWebHumanTool`~~ — you are creating it.
- ~~a `wait_strategy` kwarg before TASK-1379 lands~~ — depends on TASK-1379;
  verify `WaitStrategy` imports and `HumanTool.wait_strategy` exists first.
- ~~a separate "web suspend channel"~~ — SUSPEND skips dispatch via the manager's
  existing channel guard; no new channel needed.

---

## Implementation Notes

### Pattern to Follow
```python
class SuspendingWebHumanTool(WebHumanTool):
    """WebHumanTool wired for stateless REST: registers the interaction and
    raises HumanInteractionInterrupt instead of blocking."""
    def __init__(self, *, default_targets=None, source_agent=None, **kwargs):
        super().__init__(default_targets=default_targets,
                         source_agent=source_agent, **kwargs)
        self.wait_strategy = WaitStrategy.SUSPEND
```
`WebHumanTool._execute` already resolves manager + targets then calls
`super()._execute()` — which (after TASK-1379) honours `self.wait_strategy`.
Confirm no override is needed; if `__init__` cannot forward `wait_strategy`, set
the attribute after `super().__init__`.

### Key Constraints
- Do not duplicate target-resolution logic — inherit it.
- `self.logger` already set by `WebHumanTool.__init__`.

### References in Codebase
- `web_hitl.py:100` — `WebHumanTool` to subclass.
- `parrot/human/tool.py` — `_execute` SUSPEND branch (TASK-1379).

---

## Acceptance Criteria

- [ ] `SuspendingWebHumanTool` subclasses `WebHumanTool` and has
      `wait_strategy == WaitStrategy.SUSPEND`.
- [ ] It inherits lazy manager + `current_web_session` target resolution
      (no re-implementation).
- [ ] Importable from `parrot.handlers.web_hitl`.
- [ ] The blocking `WebHumanTool` is unchanged.
- [ ] Tests pass: `pytest packages/ai-parrot-server/tests/test_suspending_web_human_tool.py -v`
- [ ] No lint errors: `ruff check packages/ai-parrot-server/src/parrot/handlers/web_hitl.py`

---

## Test Specification

```python
# packages/ai-parrot-server/tests/test_suspending_web_human_tool.py
from parrot.handlers.web_hitl import SuspendingWebHumanTool, WebHumanTool
from parrot.human import WaitStrategy

def test_suspend_strategy():
    tool = SuspendingWebHumanTool()
    assert isinstance(tool, WebHumanTool)
    assert tool.wait_strategy == WaitStrategy.SUSPEND

def test_block_tool_unchanged():
    assert WebHumanTool().wait_strategy == WaitStrategy.BLOCK
```

---

## Agent Instructions

Standard flow: verify TASK-1379 landed (`WaitStrategy` + `HumanTool.wait_strategy`
exist), implement, test, move to `sdd/tasks/completed/`, update
`sdd/tasks/index/hitl_web.json` to `done`, fill the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**: none | describe if any
