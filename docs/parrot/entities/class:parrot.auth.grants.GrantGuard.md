---
type: Wiki Entity
title: GrantGuard
id: class:parrot.auth.grants.GrantGuard
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'The Governor: decides allow / approve / deny for a tool call.'
---

# GrantGuard

Defined in [`parrot.auth.grants`](../summaries/mod:parrot.auth.grants.md).

```python
class GrantGuard
```

The Governor: decides allow / approve / deny for a tool call.

Integrates with ToolManager via ``set_grant_guard()`` (FEAT-211, TASK-1405).
The guard is invoked inside ``execute_tool()`` **before** the dispatch to
``AbstractTool.execute()``.

Decision logic:
  1. Tool has no ``requires_grant`` meta → allow immediately.
  2. Active grant covers (owner, scope) → allow.
  3. No grant + human_manager present → request HITL approval.
     - Approved → create bounded window grant → allow.
     - Rejected / timeout → deny (fail-closed).
  4. No grant + no human_manager → deny (fail-closed).

Args:
    store: The GrantStore to consult and write to.
    human_manager: Optional HITL manager for approval requests.
        If None, the guard operates in fail-closed mode.
    config: Optional configuration overrides.

## Methods

- `async def authorize(self, *, tool: 'AbstractTool', parameters: dict, permission_context: Optional['PermissionContext']=None) -> GuardDecision` — Decide whether a tool call is allowed.
