---
type: Wiki Entity
title: ConfirmationGuard
id: class:parrot.auth.confirmation.ConfirmationGuard
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'The Governor: asks a human to confirm each marked tool call.'
---

# ConfirmationGuard

Defined in [`parrot.auth.confirmation`](../summaries/mod:parrot.auth.confirmation.md).

```python
class ConfirmationGuard
```

The Governor: asks a human to confirm each marked tool call.

Mirrors :class:`GrantGuard` (grants.py:338) in structure.  Wired into
``ToolManager`` via ``set_confirmation_guard()`` and invoked in
``execute_tool()`` **after** the grant check and **before**
``tool.execute()``.

Lifecycle for each call:
  1. Non-confirmation tool → allow immediately (``not_required``).
  2. Within ``confirm_window_seconds`` for same args_hash → allow (window hit).
  3. No ``human_manager`` → deny (fail-closed, ``cancelled``).
  4. Build briefing → ask HITL (APPROVAL or FORM × BLOCK or SUSPEND).
  5. Map result → decision (confirm/cancel/timeout).

Args:
    store: Window store to consult and write confirmed calls.
    human_manager: Optional HITL manager.  ``None`` → fail-closed mode.
    config: Optional configuration overrides (uses defaults if None).

## Methods

- `async def confirm(self, *, tool: 'AbstractTool', parameters: dict, permission_context: Optional['PermissionContext']=None) -> ConfirmationDecision` — Decide whether this specific tool call may proceed.
