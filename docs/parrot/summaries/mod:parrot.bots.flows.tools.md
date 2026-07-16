---
type: Wiki Summary
title: parrot.bots.flows.tools
id: mod:parrot.bots.flows.tools
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Flow Tools — ResultRetrievalTool.
relates_to:
- concept: class:parrot.bots.flows.tools.ResultRetrievalTool
  rel: defines
- concept: mod:parrot.bots.flows.core.storage.memory
  rel: references
- concept: mod:parrot.tools.abstract
  rel: references
---

# `parrot.bots.flows.tools`

Flow Tools — ResultRetrievalTool.

Moved from ``parrot.bots.flow.tools`` to the canonical ``flows/`` location.
Updated to import ``ExecutionMemory`` from the shared ``flows.core.storage``
rather than the old ``bots/flow/storage``.

The original ``bots/flow/tools.py`` is NOT modified — it remains for any
remaining consumers until they are migrated.

## Classes

- **`ResultRetrievalTool(AbstractTool)`** — Retrieval Tool for flows (AgentCrew, AgentsFlow).
