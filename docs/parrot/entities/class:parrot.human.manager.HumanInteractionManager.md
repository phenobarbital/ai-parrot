---
type: Wiki Entity
title: HumanInteractionManager
id: class:parrot.human.manager.HumanInteractionManager
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Orchestrates the full lifecycle of human interactions.
---

# HumanInteractionManager

Defined in [`parrot.human.manager`](../summaries/mod:parrot.human.manager.md).

```python
class HumanInteractionManager
```

Orchestrates the full lifecycle of human interactions.

Responsibilities:
- Persist pending interactions in Redis
- Dispatch questions to the correct channel
- Receive and validate responses
- Apply consensus logic
- Handle timeouts and escalation
- Resolve the caller's future (long-polling) or trigger rehydration (suspend/resume)

## Methods

- `def register_policy(self, policy: EscalationPolicy) -> None` — Register an escalation policy by its ``policy_id``.
- `def set_action(self, action_type: EscalationActionType, action: Any) -> None` — Set (or replace) the handler for *action_type*.
- `async def is_valid_respondent(self, interaction_id: str, respondent: str) -> bool` — Check whether *respondent* is an intended recipient of the interaction.
- `def register_channel(self, name: str, channel: HumanChannel) -> None` — Register a communication channel.
- `async def startup(self) -> None` — Register response + cancel handlers on all channels.
- `async def request_human_input(self, interaction: HumanInteraction, channel: str='telegram') -> InteractionResult` — Send an interaction and block until a result is available.
- `async def register_and_send(self, interaction: HumanInteraction, channel: str='telegram') -> asyncio.Future` — Register an interaction and return a Future.
- `async def request_human_input_async(self, interaction: HumanInteraction, channel: str='telegram', schedule_timeout: bool=True) -> str` — Non-blocking variant that returns the interaction_id immediately.
- `async def get_result(self, interaction_id: str) -> Optional[InteractionResult]` — Poll Redis for a completed interaction result.
- `async def advance_chain(self, interaction_id: str, cause: Literal['timeout', 'reject', 'business_hours_off', 'action_failed']='timeout') -> None` — Public entry point for advancing a tiered escalation chain.
- `async def receive_response(self, response: HumanResponse) -> None` — Process an incoming human response.
- `async def cancel_pending(self, interaction_id: str, reason: str='user_cancelled') -> bool` — Resolve a pending interaction with CANCELLED status.
- `def has_pending(self, interaction_id: str) -> bool` — Return True if there is an active pending future for this interaction.
- `async def close(self) -> None` — Release resources.
