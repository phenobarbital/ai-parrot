---
type: Wiki Summary
title: parrot.human.models
id: mod:parrot.human.models
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Core data models for the Human-in-the-Loop system.
relates_to:
- concept: class:parrot.human.models.BusinessHours
  rel: defines
- concept: class:parrot.human.models.ChoiceOption
  rel: defines
- concept: class:parrot.human.models.ConsensusMode
  rel: defines
- concept: class:parrot.human.models.EscalationActionType
  rel: defines
- concept: class:parrot.human.models.EscalationPolicy
  rel: defines
- concept: class:parrot.human.models.EscalationTier
  rel: defines
- concept: class:parrot.human.models.HumanInteraction
  rel: defines
- concept: class:parrot.human.models.HumanResponse
  rel: defines
- concept: class:parrot.human.models.InteractionResult
  rel: defines
- concept: class:parrot.human.models.InteractionStatus
  rel: defines
- concept: class:parrot.human.models.InteractionType
  rel: defines
- concept: class:parrot.human.models.Severity
  rel: defines
- concept: class:parrot.human.models.TimeoutAction
  rel: defines
- concept: class:parrot.human.models.WaitStrategy
  rel: defines
---

# `parrot.human.models`

Core data models for the Human-in-the-Loop system.

## Classes

- **`WaitStrategy(str, Enum)`** — Strategy that controls how HumanTool waits for the human response.
- **`InteractionType(str, Enum)`** — Type of interaction requested from the human.
- **`InteractionStatus(str, Enum)`** — Lifecycle status of a human interaction.
- **`TimeoutAction(str, Enum)`** — Action to take when an interaction times out.
- **`ConsensusMode(str, Enum)`** — How to consolidate responses when multiple humans are involved.
- **`ChoiceOption(BaseModel)`** — A selectable option presented to the human.
- **`Severity(str, Enum)`** — Declared criticality of a human-interaction request.
- **`BusinessHours(BaseModel)`** — Defines a business-hours window for an escalation tier.
- **`EscalationActionType(str, Enum)`** — Actions performed when escalating to a tier.
- **`EscalationTier(BaseModel)`** — Definition of a single level in an escalation policy.
- **`EscalationPolicy(BaseModel)`** — A series of tiered levels for escalating human-in-the-loop requests.
- **`HumanInteraction(BaseModel)`** — Represents a request for human input.
- **`HumanResponse(BaseModel)`** — Response from a human to an interaction.
- **`InteractionResult(BaseModel)`** — Consolidated result of an interaction after consensus evaluation.
