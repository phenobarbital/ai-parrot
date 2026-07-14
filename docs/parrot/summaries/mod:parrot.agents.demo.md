---
type: Wiki Summary
title: parrot.agents.demo
id: mod:parrot.agents.demo
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: HITL Demo Agent — Travel Concierge.
relates_to:
- concept: class:parrot.agents.demo.BookFlightSchema
  rel: defines
- concept: class:parrot.agents.demo.BookFlightTool
  rel: defines
- concept: class:parrot.agents.demo.HITLDemoAgent
  rel: defines
- concept: mod:parrot.bots.agent
  rel: references
- concept: mod:parrot.core.exceptions
  rel: references
- concept: mod:parrot.core.tools.handoff
  rel: references
- concept: mod:parrot.handlers.web_hitl
  rel: references
- concept: mod:parrot.registry
  rel: references
- concept: mod:parrot.tools.abstract
  rel: references
---

# `parrot.agents.demo`

HITL Demo Agent — Travel Concierge.

This module defines the ``HITLDemoAgent`` ("Travel Concierge") registered as
``hitl_demo`` in the agent registry. It demonstrates the full web HITL flow:

1. Uses :class:`~parrot.handlers.web_hitl.WebHumanTool` (single_choice) to
   ask the user to pick a travel destination.
2. Uses :class:`~parrot.handlers.web_hitl.WebHumanTool` (free_text) to ask
   for the desired travel date.
3. Calls :class:`BookFlightTool` with the supplied destination and date.
   - If the date is malformed, ``BookFlightTool`` raises
     :class:`~parrot.core.exceptions.HumanInteractionInterrupt`, exercising
     the ``HandoffTool`` resume path.
   - If the date is valid, a fake confirmation string is returned.
4. Summarises the trip for the user.

Usage (via the web HITL stack)::

    POST /api/v1/agents/chat/hitl_demo
    {
        "query": "I want to book a flight",
        "session_id": "my-session-id",
        "ws_channel_id": "my-session-id"
    }

## Classes

- **`BookFlightSchema(AbstractToolArgsSchema)`** — Arguments for the BookFlightTool.
- **`BookFlightTool(AbstractTool)`** — Demo tool that books a flight — or raises an interrupt on invalid input.
- **`HITLDemoAgent(BasicAgent)`** — Travel Concierge — demonstrates the web HITL (Human-in-the-Loop) flow.
