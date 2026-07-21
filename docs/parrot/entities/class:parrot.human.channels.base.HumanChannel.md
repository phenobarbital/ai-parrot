---
type: Wiki Entity
title: HumanChannel
id: class:parrot.human.channels.base.HumanChannel
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Abstraction over a communication channel with humans.
---

# HumanChannel

Defined in [`parrot.human.channels.base`](../summaries/mod:parrot.human.channels.base.md).

```python
class HumanChannel(ABC)
```

Abstraction over a communication channel with humans.

Concrete implementations handle channel-specific formatting
(Telegram inline buttons, Teams adaptive cards, CLI prompts, etc.)
and callback registration for incoming responses.

Lifecycle:
    Concrete channels may need to start/stop background workers
    (e.g. Telegram long-polling, websocket pumps). Override
    :meth:`start` and :meth:`stop`; the base implementations are
    no-ops so simple channels don't need to override anything.

Note on async ``register_*`` methods:
    Registration is currently a pure assignment in every concrete
    channel — these methods are kept ``async`` deliberately to leave
    room for channels that need to perform a remote handshake at
    registration time (e.g. subscribing to a webhook topic).

Note on ``render_reject_button``:
    When ``True`` the channel appends an "↑ Escalar" reject button
    to the rendered UI for policy-bound interactions.  Channels that
    do not have an interactive UI (CLI, etc.) should leave this as
    ``False`` — the text-based fallback is provided by
    :class:`~parrot.human.escalation_intent.RejectIntentDetector`.

## Methods

- `async def start(self) -> None` — Start background workers / open connections.
- `async def stop(self) -> None` — Stop background workers / close connections.
- `async def send_interaction(self, interaction: HumanInteraction, recipient: str) -> bool` — Send an interaction request to a human via this channel.
- `async def send_notification(self, recipient: str, message: str) -> None` — Send a one-way notification message to a human.
- `async def cancel_interaction(self, interaction_id: str, recipient: str) -> bool` — Cancel/withdraw a pending interaction from the channel.
- `async def register_response_handler(self, callback: ResponseCallback) -> None` — Register a callback invoked when a human responds.
- `async def register_cancel_handler(self, callback: CancelCallback) -> None` — Register a callback invoked when the human cancels from the channel.
