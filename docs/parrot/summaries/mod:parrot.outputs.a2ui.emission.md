---
type: Wiki Summary
title: parrot.outputs.a2ui.emission
id: mod:parrot.outputs.a2ui.emission
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: A2UI emission helper (Module 10).
relates_to:
- concept: func:parrot.outputs.a2ui.emission.finalize_a2ui_response
  rel: defines
- concept: mod:parrot.models.outputs
  rel: references
- concept: mod:parrot.outputs.a2ui.models
  rel: references
- concept: mod:parrot.outputs.a2ui.serialization
  rel: references
---

# `parrot.outputs.a2ui.emission`

A2UI emission helper (Module 10).

The pure routing logic that sends an ``OutputMode.A2UI`` response around the legacy
``OutputFormatter``. It lives in the a2ui package (no heavy bot/client deps) so it is
unit-testable in isolation; ``parrot.bots.base`` imports and calls it at both formatter
call sites.

## Functions

- `def finalize_a2ui_response(response: Any) -> None` — Route an ``OutputMode.A2UI`` response around the legacy formatter (FEAT-273).
