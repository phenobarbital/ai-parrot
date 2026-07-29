---
type: Wiki Entity
title: ParrotM365Agent
id: class:parrot.integrations.msagentsdk.agent.ParrotM365Agent
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Bridges ai-parrot AbstractBot to the Microsoft 365 Agent protocol.
---

# ParrotM365Agent

Defined in [`parrot.integrations.msagentsdk.agent`](../summaries/mod:parrot.integrations.msagentsdk.agent.md).

```python
class ParrotM365Agent
```

Bridges ai-parrot AbstractBot to the Microsoft 365 Agent protocol.

Implements the ``Agent`` protocol from ``microsoft_agents.hosting.core``
(a single ``on_turn(context: TurnContext)`` coroutine). This class is
intentionally thin: it extracts the message text, sender identity, and
conversation ID from the inbound Activity envelope, delegates to
``parrot_agent.ask()``, and sends the reply back via
``context.send_activity()``.

All ``microsoft_agents.*`` imports are lazy (inside methods) so the
package can be imported without the SDK installed.

Identity extraction prefers the Entra ``aad_object_id`` (stable across
sessions and surfaces) over the channel-level ``from_property.id``, so
the Bot Framework Token Service can key per-user tokens correctly.

Attributes:
    parrot_agent: The ai-parrot bot instance to delegate to.
    welcome_message: Text sent when a new member joins a conversation.
    _resolver: Optional credential resolver for per-user token acquisition.
    _audit_ledger: Optional audit ledger for credential usage recording.
    logger: Logger instance scoped to this bridge.

## Methods

- `async def on_turn(self, context) -> None` — Handle an incoming Activity from the Microsoft 365 Agents SDK.
- `async def resume_by_nonce(self, nonce: str) -> bool` — Attempt proactive resume for a static-key capture callback.
