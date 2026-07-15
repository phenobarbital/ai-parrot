---
type: Wiki Summary
title: parrot.bots.prompts.agent_context
id: mod:parrot.bots.prompts.agent_context
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: AgentContextLoader and AGENT_CONTEXT_LAYER for provider-agnostic prompt caching.
relates_to:
- concept: func:parrot.bots.prompts.agent_context.load_agent_context
  rel: defines
- concept: mod:parrot.bots.prompts.layers
  rel: references
- concept: mod:parrot.conf
  rel: references
---

# `parrot.bots.prompts.agent_context`

AgentContextLoader and AGENT_CONTEXT_LAYER for provider-agnostic prompt caching.

FEAT-181 — Provider-Agnostic Prompt Caching (Module 3).

Provides:
- ``load_agent_context(agent_id)`` — sync function with mtime-based LRU cache.
- ``AGENT_CONTEXT_LAYER`` — CONFIGURE-phase, cacheable=True PromptLayer that
  renders per-agent context files into the system prompt prefix.

Usage pattern in AbstractBot (TASK-1220):
    1. During configure(), call ``load_agent_context(self.name)`` and put the
       result in the context dict as ``agent_context_content``.
    2. The AGENT_CONTEXT_LAYER condition skips rendering when the value is empty.

## Functions

- `def load_agent_context(agent_id: str) -> str` — Load the per-agent context file for the given agent ID.
