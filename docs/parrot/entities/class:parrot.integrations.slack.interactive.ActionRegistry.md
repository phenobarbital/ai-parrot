---
type: Wiki Entity
title: ActionRegistry
id: class:parrot.integrations.slack.interactive.ActionRegistry
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Registry for Block Kit action handlers.
---

# ActionRegistry

Defined in [`parrot.integrations.slack.interactive`](../summaries/mod:parrot.integrations.slack.interactive.md).

```python
class ActionRegistry
```

Registry for Block Kit action handlers.

Maps action_id patterns to async handler functions.
Supports both exact matching and prefix matching.

Examples:
    registry = ActionRegistry()
    registry.register("approve_request", handle_approve)
    registry.register_prefix("feedback_", handle_feedback)

## Methods

- `def register(self, action_id: str, handler: Callable) -> None` — Register handler for exact action_id match.
- `def register_prefix(self, prefix: str, handler: Callable) -> None` — Register handler for action_id prefix match.
- `def get_handler(self, action_id: str) -> Optional[Callable]` — Find handler for action_id.
- `def unregister(self, action_id: str) -> None` — Remove an exact match handler.
- `def unregister_prefix(self, prefix: str) -> None` — Remove a prefix match handler.
