---
type: Wiki Summary
title: parrot.bots.database.prompts
id: mod:parrot.bots.database.prompts
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Database agent prompt layers and builder factory.
relates_to:
- concept: mod:parrot.bots.prompts
  rel: references
- concept: mod:parrot.bots.prompts.domain_layers
  rel: references
- concept: mod:parrot.bots.prompts.layers
  rel: references
---

# `parrot.bots.database.prompts`

Database agent prompt layers and builder factory.

Replaces the legacy string.Template constants with composable PromptLayer
instances that integrate with the PromptBuilder machinery used by PandasAgent.

Module 2 of FEAT-164 (database-agent-homologation).
