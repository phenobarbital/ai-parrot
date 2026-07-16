---
type: Wiki Summary
title: parrot.bots.flows.flow.actions
id: mod:parrot.bots.flows.flow.actions
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Action Registry — Lifecycle hooks for AgentsFlow nodes.
relates_to:
- concept: class:parrot.bots.flows.flow.actions.BaseAction
  rel: defines
- concept: class:parrot.bots.flows.flow.actions.LogAction
  rel: defines
- concept: class:parrot.bots.flows.flow.actions.MetricAction
  rel: defines
- concept: class:parrot.bots.flows.flow.actions.NotifyAction
  rel: defines
- concept: class:parrot.bots.flows.flow.actions.SetContextAction
  rel: defines
- concept: class:parrot.bots.flows.flow.actions.TransformAction
  rel: defines
- concept: class:parrot.bots.flows.flow.actions.ValidateAction
  rel: defines
- concept: class:parrot.bots.flows.flow.actions.WebhookAction
  rel: defines
- concept: func:parrot.bots.flows.flow.actions.create_action
  rel: defines
- concept: func:parrot.bots.flows.flow.actions.register_action
  rel: defines
- concept: mod:parrot.bots.flows.flow.definition
  rel: references
---

# `parrot.bots.flows.flow.actions`

Action Registry — Lifecycle hooks for AgentsFlow nodes.

This module defines the ACTION_REGISTRY and all built-in action implementations.
Actions are executed as pre/post hooks on flow nodes and can:
- Log messages with template variables
- Send notifications to external channels
- Make HTTP webhook calls
- Emit metrics
- Extract and set context values
- Validate results against JSON schemas
- Transform results

Example:
    >>> from parrot.bots.flows.flow.actions import ACTION_REGISTRY, LogAction
    >>> from parrot.bots.flows.flow.definition import LogActionDef
    >>>
    >>> config = LogActionDef(level="info", message="Node {node_name} completed")
    >>> action = LogAction(config)
    >>> await action("my_node", "result_payload")

## Classes

- **`BaseAction(ABC)`** — Abstract base class for all flow lifecycle actions.
- **`LogAction(BaseAction)`** — Log a message with template variables.
- **`NotifyAction(BaseAction)`** — Send a notification to a channel.
- **`WebhookAction(BaseAction)`** — Make an HTTP webhook call.
- **`MetricAction(BaseAction)`** — Emit a metric.
- **`SetContextAction(BaseAction)`** — Extract a value from the result and set it in the shared context.
- **`ValidateAction(BaseAction)`** — Validate the result against a JSON schema.
- **`TransformAction(BaseAction)`** — Transform the result using a safe expression.

## Functions

- `def register_action(action_type: str)` — Decorator to register an action class in the ACTION_REGISTRY.
- `def create_action(config: ActionDefinition) -> BaseAction` — Create an action instance from a configuration.
