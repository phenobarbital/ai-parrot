---
type: Wiki Summary
title: parrot.tools.working_memory.tests.test_integration_workflow
id: mod:parrot.tools.working_memory.tests.test_integration_workflow
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Integration tests for WorkingMemoryToolkit FEAT-074 changes.
relates_to:
- concept: class:parrot.tools.working_memory.tests.test_integration_workflow.TestAnswerMemoryRoundtrip
  rel: defines
- concept: class:parrot.tools.working_memory.tests.test_integration_workflow.TestBackwardCompatFull
  rel: defines
- concept: class:parrot.tools.working_memory.tests.test_integration_workflow.TestFuzzyRecallRoundtrip
  rel: defines
- concept: class:parrot.tools.working_memory.tests.test_integration_workflow.TestMixedWorkflow
  rel: defines
- concept: mod:parrot.memory
  rel: references
- concept: mod:parrot.tools.working_memory
  rel: references
- concept: mod:parrot.tools.working_memory.models
  rel: references
---

# `parrot.tools.working_memory.tests.test_integration_workflow`

Integration tests for WorkingMemoryToolkit FEAT-074 changes.

Covers end-to-end workflows mixing DataFrames and generic entries,
the full AnswerMemory bridge roundtrip, and backward compatibility.

## Classes

- **`TestMixedWorkflow`** — Store DataFrame + generic entries together, list, retrieve, drop.
- **`TestBackwardCompatFull`** — Existing TestFullWorkflow-style operations must be unaffected.
- **`TestAnswerMemoryRoundtrip`** — Save interaction → recall → import → get_result → verify content.
- **`TestFuzzyRecallRoundtrip`** — Save 3 interactions → query by substring → import → verify.
