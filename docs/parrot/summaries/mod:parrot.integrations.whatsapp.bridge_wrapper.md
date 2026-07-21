---
type: Wiki Summary
title: parrot.integrations.whatsapp.bridge_wrapper
id: mod:parrot.integrations.whatsapp.bridge_wrapper
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: WhatsApp Bridge Agent Wrapper.
relates_to:
- concept: class:parrot.integrations.whatsapp.bridge_wrapper.WhatsAppBridgeWrapper
  rel: defines
- concept: mod:parrot.bots.abstract
  rel: references
- concept: mod:parrot.integrations.parser
  rel: references
- concept: mod:parrot.integrations.whatsapp.bridge_config
  rel: references
- concept: mod:parrot.integrations.whatsapp.handler
  rel: references
- concept: mod:parrot.integrations.whatsapp.utils
  rel: references
- concept: mod:parrot.memory
  rel: references
- concept: mod:parrot.models.outputs
  rel: references
---

# `parrot.integrations.whatsapp.bridge_wrapper`

WhatsApp Bridge Agent Wrapper.

Connects AI-Parrot agents to WhatsApp via the Go whatsmeow bridge.
The bridge POSTs incoming messages to a webhook; this wrapper processes
them through the agent and replies via the bridge's /send endpoint.

Architecture::

    WhatsApp ─► Go Bridge ─(HTTP POST)─► WhatsAppBridgeWrapper
                                               │
                                          agent.ask()
                                               │
    WhatsApp ◄─ Go Bridge ◄─(POST /send)──────┘

## Classes

- **`WhatsAppBridgeWrapper`** — Wraps an AI-Parrot Agent for WhatsApp Bridge integration.
