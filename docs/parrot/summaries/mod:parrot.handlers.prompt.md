---
type: Wiki Summary
title: parrot.handlers.prompt
id: mod:parrot.handlers.prompt
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: HTTP handler for runtime system-prompt fine-tuning — ``/api/v1/agents/prompt``.
relates_to:
- concept: class:parrot.handlers.prompt.PromptTunerHandler
  rel: defines
- concept: mod:parrot.bots.abstract
  rel: references
- concept: mod:parrot.bots.dynamic_values
  rel: references
- concept: mod:parrot.bots.prompts
  rel: references
- concept: mod:parrot.bots.prompts.domain_layers
  rel: references
- concept: mod:parrot.bots.prompts.layers
  rel: references
- concept: mod:parrot.clients.factory
  rel: references
- concept: mod:parrot.manager
  rel: references
---

# `parrot.handlers.prompt`

HTTP handler for runtime system-prompt fine-tuning — ``/api/v1/agents/prompt``.

Lets an authenticated user load the *current* prompt definition of a live
agent, edit every layer of its ``PromptBuilder`` (semantic fields **and** raw
layer templates), request LLM-assisted suggestions driven by a meta-prompting
framework document, test the edits against an ephemeral clone, and finally
save them onto the live in-memory instance.

The changes are **in-memory only** — they live on the ``BotManager``'s bot
instance for the process lifetime and are lost on restart. This is a
fine-tuning / playground surface, not a persistence layer.

Workflow (mirrors the phases requested in FEAT prompt-tuner):
    1. The user picks an agent (``{agent_name}`` in the URL).
    2. ``GET`` resolves the live instance from the ``BotManager``.
    3. ``GET`` returns every part that constitutes the agent's prompt
       (semantic fields + layer templates + the fully-rendered prompt).
    4. ``PATCH`` records edits in a per-user **session draft** (the in-memory
       working copy) without touching the live bot.
    5. ``POST .../suggest`` asks a lightweight LLM (Claude Haiku by default)
       — primed with the meta-prompting doc — to propose concrete edits.
    6. ``POST .../test`` builds an ephemeral clone with the draft applied and
       runs a query against it.
    7. ``POST .../save`` applies the draft to the live instance.

Routes:
    GET    /api/v1/agents/prompt/{agent_name}          — load current definition + draft
    PATCH  /api/v1/agents/prompt/{agent_name}          — merge edits into the draft
    POST   /api/v1/agents/prompt/{agent_name}/suggest  — LLM meta-prompting suggestions
    POST   /api/v1/agents/prompt/{agent_name}/test     — test the draft on a clone
    POST   /api/v1/agents/prompt/{agent_name}/save     — apply the draft to the live bot
    DELETE /api/v1/agents/prompt/{agent_name}          — discard the draft + test clone

## Classes

- **`PromptTunerHandler(BaseView)`** — Runtime system-prompt fine-tuning console.
