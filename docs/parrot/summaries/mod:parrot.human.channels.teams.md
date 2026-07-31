---
type: Wiki Summary
title: parrot.human.channels.teams
id: mod:parrot.human.channels.teams
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Teams HITL Human Channel for AI-Parrot.
relates_to:
- concept: class:parrot.human.channels.teams.TeamsHitlConfig
  rel: defines
- concept: class:parrot.human.channels.teams.TeamsHumanChannel
  rel: defines
- concept: func:parrot.human.channels.teams.setup_teams_hitl
  rel: defines
- concept: mod:parrot.human.channels
  rel: references
- concept: mod:parrot.human.channels.base
  rel: references
- concept: mod:parrot.human.models
  rel: references
- concept: mod:parrot.integrations.msteams.graph
  rel: references
- concept: mod:parrot.integrations.msteams.hitl_adapter
  rel: references
- concept: mod:parrot.integrations.msteams.hitl_cards
  rel: references
- concept: mod:parrot.integrations.msteams.proactive
  rel: references
---

# `parrot.human.channels.teams`

Teams HITL Human Channel for AI-Parrot.

Implements the full :class:`~parrot.human.channels.base.HumanChannel` contract
for Microsoft Teams, enabling the Human-in-the-Loop engine to deliver
interactions (approvals, free-text questions, forms, polls, etc.) to
managers/humans via Teams private 1:1 chats.

The channel uses a dedicated HITL bot identity (separate from the
conversational MSTeamsAgentWrapper identity) and relies on:

- :class:`~parrot.integrations.msteams.graph.GraphClient` — email→AAD resolution.
- :class:`~parrot.integrations.msteams.proactive.ProactiveMessenger` — warm/cold
  proactive 1:1 bootstrap.
- :class:`~parrot.integrations.msteams.hitl_cards.TeamsCardRenderer` — per-
  InteractionType Adaptive Card rendering.
- Redis — ConversationReference + sent-activity maps.

See ``parrot/human/channels/telegram.py`` for the reference implementation
and ``sdd/specs/hitl-teams-channel.spec.md`` for the full spec.

Inbound demux:
    The channel's :meth:`TeamsHumanChannel.on_turn` webhook handler inspects
    every incoming activity.  When ``activity.value.get("hitl") is True`` the
    activity is treated as a card-submit response; ``respondent`` is taken from
    the BF-validated ``activity.from_property.aad_object_id`` (never from the
    card payload) and a :class:`~parrot.human.models.HumanResponse` is built
    and dispatched to the stored ``_response_callback``.

Security:
    ``respondent`` identity always comes from the Bot Framework validated
    activity ``from_property.aad_object_id`` — the card payload is untrusted.

Late-reply handling:
    If a ``hitl:result:{interaction_id}`` tombstone key exists in Redis, the
    card submit was received after the interaction expired; the channel sends
    an in-thread acknowledgment and does NOT invoke the response callback.

## Classes

- **`TeamsHumanChannel(HumanChannel)`** — Teams Human Channel for HITL interactions.
- **`TeamsHitlConfig(BaseModel)`** — Boot configuration for the shared HITL bot identity.

## Functions

- `async def setup_teams_hitl(app: Any, manager: Any, config: TeamsHitlConfig, channel_name: str='teams') -> 'TeamsHumanChannel'` — Wire the shared HITL bot in one call.
