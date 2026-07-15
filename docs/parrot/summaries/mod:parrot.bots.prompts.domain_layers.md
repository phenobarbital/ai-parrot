---
type: Wiki Summary
title: parrot.bots.prompts.domain_layers
id: mod:parrot.bots.prompts.domain_layers
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Domain-specific prompt layers.
relates_to:
- concept: func:parrot.bots.prompts.domain_layers.get_domain_layer
  rel: defines
- concept: mod:parrot.bots.prompts.layers
  rel: references
---

# `parrot.bots.prompts.domain_layers`

Domain-specific prompt layers.

Reusable layers for specialized bot types (PandasAgent, SQL agents,
company bots, crew orchestration). These extend the built-in layers
without modifying them.

See spec: sdd/specs/composable-prompt-layer.spec.md (Section 3.5)

## Functions

- `def get_domain_layer(name: str) -> PromptLayer` — Look up a registered domain layer by name.
