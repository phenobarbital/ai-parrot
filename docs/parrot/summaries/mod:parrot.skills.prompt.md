---
type: Wiki Summary
title: parrot.skills.prompt
id: mod:parrot.skills.prompt
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Skills Prompt Layer Factory.
relates_to:
- concept: func:parrot.skills.prompt.render_skills_prompt_layer
  rel: defines
- concept: mod:parrot.bots.prompts
  rel: references
- concept: mod:parrot.skills.file_registry
  rel: references
---

# `parrot.skills.prompt`

Skills Prompt Layer Factory.

Provides :func:`render_skills_prompt_layer` — a factory function that builds
a static ``<available_skills>`` XML block from a
:class:`~parrot.skills.file_registry.SkillFileRegistry` and returns it as an
immutable :class:`~parrot.bots.prompts.PromptLayer` with
``phase=RenderPhase.CONFIGURE``.

The layer is resolved once at ``configure()`` time and cached, incurring zero
per-turn cost (Tier 1 of the two-tier skills system).

Usage::

    from parrot.skills.prompt import render_skills_prompt_layer

    layer = render_skills_prompt_layer(registry)
    self._prompt_builder.add(layer)

## Functions

- `def render_skills_prompt_layer(registry: SkillFileRegistry, max_skills: Optional[int]=None, priority: int=45) -> PromptLayer` — Build a static ``<available_skills>`` XML PromptLayer from the registry.
