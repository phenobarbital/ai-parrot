---
type: Wiki Summary
title: parrot.bots.dynamic_values
id: mod:parrot.bots.dynamic_values
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Dynamic Value Provider Registry.
relates_to:
- concept: class:parrot.bots.dynamic_values.DynamicValueProvider
  rel: defines
- concept: func:parrot.bots.dynamic_values.get_user_name
  rel: defines
---

# `parrot.bots.dynamic_values`

Dynamic Value Provider Registry.

This module provides a registry for dynamic values that can be injected into system prompts
during runtime. It allows for registered functions to be called and their return values
used for template substitution in prompts.

## Classes

- **`DynamicValueProvider`** — Registry for dynamic value functions

## Functions

- `async def get_user_name(context)` — This one needs context to determine the user
