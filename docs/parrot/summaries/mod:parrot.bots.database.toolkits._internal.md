---
type: Wiki Summary
title: parrot.bots.database.toolkits._internal
id: mod:parrot.bots.database.toolkits._internal
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: DatabaseAgentToolkit — internal helper tools for DatabaseAgent.
relates_to:
- concept: class:parrot.bots.database.toolkits._internal.DatabaseAgentToolkit
  rel: defines
- concept: mod:parrot.bots.database.models
  rel: references
- concept: mod:parrot.tools
  rel: references
- concept: mod:parrot.tools.toolkit
  rel: references
---

# `parrot.bots.database.toolkits._internal`

DatabaseAgentToolkit — internal helper tools for DatabaseAgent.

Ports 16 utility helpers from AbstractDBAgent into a standalone, LLM-callable
toolkit. Gating logic (OutputComponent / QueryIntent filtering) lives at the
agent layer (Module 5 / TASK-1128); this module is component-agnostic.

Module 3 of FEAT-164 (database-agent-homologation).

## Classes

- **`DatabaseAgentToolkit(AbstractToolkit)`** — Internal helper toolkit for DatabaseAgent.
