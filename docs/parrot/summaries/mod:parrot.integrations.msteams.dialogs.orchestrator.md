---
type: Wiki Summary
title: parrot.integrations.msteams.dialogs.orchestrator
id: mod:parrot.integrations.msteams.dialogs.orchestrator
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Form Orchestrator - Coordinates form generation, display, and tool execution.
relates_to:
- concept: class:parrot.integrations.msteams.dialogs.orchestrator.FormOrchestrator
  rel: defines
- concept: class:parrot.integrations.msteams.dialogs.orchestrator.PendingExecution
  rel: defines
- concept: class:parrot.integrations.msteams.dialogs.orchestrator.ProcessResult
  rel: defines
- concept: mod:parrot.bots.abstract
  rel: references
- concept: mod:parrot.forms
  rel: references
- concept: mod:parrot.forms.extractors.tool
  rel: references
- concept: mod:parrot.forms.tools
  rel: references
- concept: mod:parrot.integrations.msteams.dialogs.factory
  rel: references
- concept: mod:parrot.models.outputs
  rel: references
- concept: mod:parrot.tools.abstract
  rel: references
---

# `parrot.integrations.msteams.dialogs.orchestrator`

Form Orchestrator - Coordinates form generation, display, and tool execution.

Integrates:
- RequestFormTool for LLM-initiated forms
- Form dialog management
- Post-form tool execution

## Classes

- **`PendingExecution`** — Tracks a pending tool execution after form completion.
- **`ProcessResult`** — Result of processing a message.
- **`FormOrchestrator`** — Orchestrates the form-based interaction flow.
