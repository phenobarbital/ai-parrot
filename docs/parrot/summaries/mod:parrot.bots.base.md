---
type: Wiki Summary
title: parrot.bots.base
id: mod:parrot.bots.base
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: BaseBot - Concrete implementation of AbstractBot.
relates_to:
- concept: class:parrot.bots.base.BaseBot
  rel: defines
- concept: mod:parrot.bots.abstract
  rel: references
- concept: mod:parrot.bots.prompts
  rel: references
- concept: mod:parrot.core.events.lifecycle.events
  rel: references
- concept: mod:parrot.core.events.lifecycle.trace
  rel: references
- concept: mod:parrot.memory
  rel: references
- concept: mod:parrot.models
  rel: references
- concept: mod:parrot.models.interactive
  rel: references
- concept: mod:parrot.models.outputs
  rel: references
- concept: mod:parrot.models.status
  rel: references
- concept: mod:parrot.observability.context
  rel: references
- concept: mod:parrot.outputs.a2ui.emission
  rel: references
- concept: mod:parrot.security
  rel: references
- concept: mod:parrot.security.redaction
  rel: references
- concept: mod:parrot.tools.infographic_toolkit
  rel: references
- concept: mod:parrot.utils.helpers
  rel: references
---

# `parrot.bots.base`

BaseBot - Concrete implementation of AbstractBot.

This module provides BaseBot, a concrete implementation of the AbstractBot
abstract base class. It implements all required abstract methods.

## Classes

- **`BaseBot(AbstractBot)`** — Base Bot implementation providing concrete implementations of
