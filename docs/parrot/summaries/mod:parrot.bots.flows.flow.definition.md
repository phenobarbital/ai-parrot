---
type: Wiki Summary
title: parrot.bots.flows.flow.definition
id: mod:parrot.bots.flows.flow.definition
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: FlowDefinition — Pydantic models for AgentsFlow JSON serialization.
relates_to:
- concept: class:parrot.bots.flows.flow.definition.EdgeDefinition
  rel: defines
- concept: class:parrot.bots.flows.flow.definition.FlowDefinition
  rel: defines
- concept: class:parrot.bots.flows.flow.definition.FlowMetadata
  rel: defines
- concept: class:parrot.bots.flows.flow.definition.LogActionDef
  rel: defines
- concept: class:parrot.bots.flows.flow.definition.MetricActionDef
  rel: defines
- concept: class:parrot.bots.flows.flow.definition.NodeDefinition
  rel: defines
- concept: class:parrot.bots.flows.flow.definition.NodePosition
  rel: defines
- concept: class:parrot.bots.flows.flow.definition.NotifyActionDef
  rel: defines
- concept: class:parrot.bots.flows.flow.definition.SetContextActionDef
  rel: defines
- concept: class:parrot.bots.flows.flow.definition.TransformActionDef
  rel: defines
- concept: class:parrot.bots.flows.flow.definition.ValidateActionDef
  rel: defines
- concept: class:parrot.bots.flows.flow.definition.WebhookActionDef
  rel: defines
---

# `parrot.bots.flows.flow.definition`

FlowDefinition — Pydantic models for AgentsFlow JSON serialization.

This module defines the complete schema for persisting and loading AgentsFlow
workflows as JSON. The schema supports:
- Node definitions (start, end, agent, decision, interactive_decision, human)
- Edge definitions with conditional transitions
- Pre/post lifecycle actions
- SvelteFlow-compatible position data

Example:
    >>> from parrot.bots.flows.flow.definition import FlowDefinition
    >>> definition = FlowDefinition.model_validate(json_data)
    >>> json_str = definition.model_dump_json(by_alias=True)

## Classes

- **`LogActionDef(BaseModel)`** — Log a message with template variables.
- **`NotifyActionDef(BaseModel)`** — Send a notification to a channel.
- **`WebhookActionDef(BaseModel)`** — Make an HTTP webhook call.
- **`MetricActionDef(BaseModel)`** — Emit a metric.
- **`SetContextActionDef(BaseModel)`** — Extract a value from result and set in shared context.
- **`ValidateActionDef(BaseModel)`** — Validate result against a JSON schema.
- **`TransformActionDef(BaseModel)`** — Transform result using a safe expression.
- **`NodePosition(BaseModel)`** — UI position hint for visual flow builders (SvelteFlow compatible).
- **`NodeDefinition(BaseModel)`** — Definition of a node in the flow.
- **`EdgeDefinition(BaseModel)`** — Definition of an edge (transition) between nodes.
- **`FlowMetadata(BaseModel)`** — Flow-level configuration and defaults.
- **`FlowDefinition(BaseModel)`** — Complete definition of an AgentsFlow workflow.
