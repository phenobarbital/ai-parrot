---
type: Wiki Summary
title: parrot.handlers.models.users_prompts
id: mod:parrot.handlers.models.users_prompts
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Database model for per-user prompts (``navigator.users_prompts``).
relates_to:
- concept: class:parrot.handlers.models.users_prompts.UserPrompts
  rel: defines
- concept: mod:parrot.conf
  rel: references
- concept: mod:parrot.handlers.models.bots
  rel: references
---

# `parrot.handlers.models.users_prompts`

Database model for per-user prompts (``navigator.users_prompts``).

Mirrors :class:`parrot.handlers.models.bots.PromptLibrary` but is keyed
by ``(user_id, prompt_id)`` so each user owns their own private prompt
collection. ``chatbot_id`` is typed as a plain string so it can hold
either a DB-backed chatbot UUID (stringified) or a registry agent slug
(e.g. ``"web_search_agent"``).

## Classes

- **`UserPrompts(Model)`** — Per-user prompt definition.
