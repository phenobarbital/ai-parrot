---
type: Wiki Summary
title: parrot.tools.working_memory.tests.test_answer_memory_bridge
id: mod:parrot.tools.working_memory.tests.test_answer_memory_bridge
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Tests for the AnswerMemory bridge in WorkingMemoryToolkit.
relates_to:
- concept: class:parrot.tools.working_memory.tests.test_answer_memory_bridge.TestAutoInjection
  rel: defines
- concept: class:parrot.tools.working_memory.tests.test_answer_memory_bridge.TestRecallByQuery
  rel: defines
- concept: class:parrot.tools.working_memory.tests.test_answer_memory_bridge.TestRecallByTurnId
  rel: defines
- concept: class:parrot.tools.working_memory.tests.test_answer_memory_bridge.TestRecallValidation
  rel: defines
- concept: class:parrot.tools.working_memory.tests.test_answer_memory_bridge.TestSaveInteraction
  rel: defines
- concept: mod:parrot.memory
  rel: references
- concept: mod:parrot.tools.working_memory
  rel: references
---

# `parrot.tools.working_memory.tests.test_answer_memory_bridge`

Tests for the AnswerMemory bridge in WorkingMemoryToolkit.

Covers:
- save_interaction() with / without AnswerMemory
- recall_interaction() by exact turn_id
- recall_interaction() by query (fuzzy/substring)
- recall_interaction() with import_as
- recall_interaction() validation (neither turn_id nor query)
- BasicAgent auto-injection of answer_memory

## Classes

- **`TestSaveInteraction`** — save_interaction() tool method.
- **`TestRecallByTurnId`** — recall_interaction() with exact turn_id lookup.
- **`TestRecallByQuery`** — recall_interaction() with substring query lookup.
- **`TestRecallValidation`** — recall_interaction() must require at least one of turn_id or query.
- **`TestAutoInjection`** — BasicAgent._inject_answer_memory_into_toolkits auto-wires answer_memory.
