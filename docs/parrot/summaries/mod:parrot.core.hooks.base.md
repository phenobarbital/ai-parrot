---
type: Wiki Summary
title: parrot.core.hooks.base
id: mod:parrot.core.hooks.base
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Abstract base class for all external hooks.
relates_to:
- concept: class:parrot.core.hooks.base.BaseHook
  rel: defines
- concept: class:parrot.core.hooks.base.HookRegistry
  rel: defines
- concept: class:parrot.core.hooks.base.MessagingHook
  rel: defines
- concept: mod:parrot.core.hooks.models
  rel: references
---

# `parrot.core.hooks.base`

Abstract base class for all external hooks.

## Classes

- **`MessagingHook(Protocol)`** — Interface for messaging-channel hooks (e.g. matrix, telegram).
- **`HookRegistry`** — Registry for external hook implementations.
- **`BaseHook(ABC)`** — Abstract base for all external hooks in AutonomousOrchestrator.
