---
type: Wiki Summary
title: parrot.integrations.msagentsdk.semantic
id: mod:parrot.integrations.msagentsdk.semantic
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Semantic UI Model for custom engine Copilot agents (FEAT-303).
relates_to:
- concept: class:parrot.integrations.msagentsdk.semantic.DetailPayload
  rel: defines
- concept: class:parrot.integrations.msagentsdk.semantic.MetricsPayload
  rel: defines
- concept: class:parrot.integrations.msagentsdk.semantic.SemanticUIResult
  rel: defines
- concept: class:parrot.integrations.msagentsdk.semantic.StatusPayload
  rel: defines
- concept: class:parrot.integrations.msagentsdk.semantic.TablePayload
  rel: defines
- concept: class:parrot.integrations.msagentsdk.semantic.UIAction
  rel: defines
- concept: class:parrot.integrations.msagentsdk.semantic.UIField
  rel: defines
- concept: class:parrot.integrations.msagentsdk.semantic.UIMetric
  rel: defines
---

# `parrot.integrations.msagentsdk.semantic`

Semantic UI Model for custom engine Copilot agents (FEAT-303).

This module defines the channel-neutral, card-oriented contract that domain
agents return as explicit structured output so that the ``msagentsdk`` bridge
can render rich Adaptive Cards for Microsoft 365 Copilot and Teams instead of
flat text.

The models here are pure Pydantic — this module MUST be importable without
``microsoft_agents.*`` installed, and it imports nothing from the rest of
``parrot`` so that import isolation always holds.

## Classes

- **`UIAction(BaseModel)`** — A card action button.
- **`UIField(BaseModel)`** — A single labeled field, used by :class:`DetailPayload`.
- **`UIMetric(BaseModel)`** — A single KPI/metric entry, used by :class:`MetricsPayload`.
- **`TablePayload(BaseModel)`** — A tabular result payload.
- **`MetricsPayload(BaseModel)`** — A metrics/KPI result payload.
- **`DetailPayload(BaseModel)`** — An entity-detail result payload.
- **`StatusPayload(BaseModel)`** — A status/error result payload.
- **`SemanticUIResult(BaseModel)`** — Card-oriented semantic description of an agent result.
