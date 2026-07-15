---
type: Wiki Entity
title: TeamsHumanChannel
id: class:parrot.human.channels.teams.TeamsHumanChannel
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Teams Human Channel for HITL interactions.
relates_to:
- concept: class:parrot.human.channels.base.HumanChannel
  rel: extends
---

# TeamsHumanChannel

Defined in [`parrot.human.channels.teams`](../summaries/mod:parrot.human.channels.teams.md).

```python
class TeamsHumanChannel(HumanChannel)
```

Teams Human Channel for HITL interactions.

Delivers :class:`~parrot.human.models.HumanInteraction` objects to
Microsoft Teams users via proactive 1:1 Adaptive Card messages, and
captures card-submit responses back to the HITL engine.

Lifecycle::

    channel = TeamsHumanChannel(adapter, graph_client, redis, config)
    await channel.register_response_handler(manager.receive_response)
    await channel.start()          # registers webhook route on the app
    # … manager handles interactions …
    await channel.stop()

Args:
    adapter: :class:`~.hitl_adapter.HitlCloudAdapter` for this HITL bot.
    graph_client: :class:`~.graph.GraphClient` for email→AAD resolution.
    redis: Async Redis client for convref + sent-activity stores.
    config: :class:`~.teams_setup.TeamsHitlConfig` boot configuration.
    app: Optional aiohttp ``web.Application``; required when
        :meth:`start` should register the webhook route.

## Methods

- `async def start(self) -> None` — Register the inbound webhook route on the aiohttp app.
- `async def stop(self) -> None` — Shut down the channel and release underlying resources.
- `async def messages_handler(self, request: web.Request) -> web.Response` — aiohttp handler for ``POST /api/teams-hitl/messages``.
- `async def on_turn(self, turn_context: TurnContext) -> None` — Bot Framework on_turn handler — inbound demux.
- `async def send_interaction(self, interaction: HumanInteraction, recipient: str) -> bool` — Send an HITL interaction card to a Teams user.
- `async def send_notification(self, recipient: str, message: str) -> None` — Send a one-way notification to a Teams user (no reply expected).
- `async def cancel_interaction(self, interaction_id: str, recipient: str) -> bool` — Cancel/withdraw a pending interaction by updating its card to a disabled state.
- `async def register_response_handler(self, callback: ResponseCallback) -> None` — Store the manager's response callback.
- `async def register_cancel_handler(self, callback: CancelCallback) -> None` — Store the manager's cancel callback.
