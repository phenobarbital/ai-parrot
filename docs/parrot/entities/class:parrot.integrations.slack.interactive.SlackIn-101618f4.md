---
type: Wiki Entity
title: SlackInteractiveHandler
id: class:parrot.integrations.slack.interactive.SlackInteractiveHandler
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Handles all interactive payloads from Slack Block Kit.
---

# SlackInteractiveHandler

Defined in [`parrot.integrations.slack.interactive`](../summaries/mod:parrot.integrations.slack.interactive.md).

```python
class SlackInteractiveHandler
```

Handles all interactive payloads from Slack Block Kit.

Routes different payload types to appropriate handlers:
- block_actions: Button clicks, menu selections
- view_submission: Modal form submissions
- shortcut/message_action: Global and message shortcuts

Attributes:
    wrapper: The parent SlackAgentWrapper instance.
    action_registry: Registry for custom action handlers.

## Methods

- `async def handle(self, request_or_payload: web.Request | dict) -> Optional[web.Response]` — Entry point for interactive payloads.
- `async def open_modal(self, trigger_id: str, form_definition: dict) -> bool` — Open a Slack modal dialog.
- `async def update_modal(self, view_id: str, form_definition: dict) -> bool` — Update an existing modal.
- `def extract_form_values(self, payload: dict) -> Dict[str, Any]` — Extract form values from a view_submission payload.
