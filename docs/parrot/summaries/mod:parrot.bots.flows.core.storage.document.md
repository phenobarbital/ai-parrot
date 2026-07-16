---
type: Wiki Summary
title: parrot.bots.flows.core.storage.document
id: mod:parrot.bots.flows.core.storage.document
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: CrewExecutionDocument — deterministic, LLM-free consolidated execution record.
relates_to:
- concept: class:parrot.bots.flows.core.storage.document.CrewExecutionDocument
  rel: defines
- concept: mod:parrot.bots.flows.core.result
  rel: references
- concept: mod:parrot.bots.flows.core.storage.backends
  rel: references
- concept: mod:parrot.bots.flows.core.storage.memory
  rel: references
- concept: mod:parrot.bots.flows.core.types
  rel: references
---

# `parrot.bots.flows.core.storage.document`

CrewExecutionDocument — deterministic, LLM-free consolidated execution record.

Assembles every agent's result + the final crew output + the (already
generated) synthesis summary into one consistent document, buildable from
in-process state (``from_memory``) or reconstructed from the storage
backend (``from_storage``). Both ``to_dict()`` and ``to_markdown()`` make
ZERO LLM calls — pure, deterministic data transformation.

This module MUST NOT import from ``parrot.clients`` or any LLM SDK.

## Classes

- **`CrewExecutionDocument`** — Deterministic, LLM-free consolidated record of one crew execution.
