---
type: Wiki Summary
title: parrot.human.channels.base
id: mod:parrot.human.channels.base
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Abstract base class for human communication channels.
relates_to:
- concept: class:parrot.human.channels.base.HumanChannel
  rel: defines
- concept: func:parrot.human.channels.base.escalate_option
  rel: defines
- concept: mod:parrot.human.models
  rel: references
---

# `parrot.human.channels.base`

Abstract base class for human communication channels.

## Classes

- **`HumanChannel(ABC)`** — Abstraction over a communication channel with humans.

## Functions

- `def escalate_option() -> 'ChoiceOption'` — Return the standardised "↑ Escalar" choice option.
