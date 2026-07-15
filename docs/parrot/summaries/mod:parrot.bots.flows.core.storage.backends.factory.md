---
type: Wiki Summary
title: parrot.bots.flows.core.storage.backends.factory
id: mod:parrot.bots.flows.core.storage.backends.factory
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Factory for resolving ResultStorage backends by name, instance, or env var.
relates_to:
- concept: func:parrot.bots.flows.core.storage.backends.factory.get_result_storage
  rel: defines
- concept: mod:parrot.bots.flows.core.storage.backends.base
  rel: references
- concept: mod:parrot.conf
  rel: references
---

# `parrot.bots.flows.core.storage.backends.factory`

Factory for resolving ResultStorage backends by name, instance, or env var.

## Functions

- `def get_result_storage(name_or_instance: Union[str, 'ResultStorage', None]=None) -> 'ResultStorage'` — Resolve a ``ResultStorage`` instance.
