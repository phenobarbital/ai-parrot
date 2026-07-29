---
type: Wiki Summary
title: parrot.bots.flows.flow.svelteflow
id: mod:parrot.bots.flows.flow.svelteflow
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: SvelteFlow Adapter — bidirectional conversion for visual flow builders.
relates_to:
- concept: func:parrot.bots.flows.flow.svelteflow.from_svelteflow
  rel: defines
- concept: func:parrot.bots.flows.flow.svelteflow.to_svelteflow
  rel: defines
- concept: mod:parrot.bots.flows.flow.definition
  rel: references
---

# `parrot.bots.flows.flow.svelteflow`

SvelteFlow Adapter — bidirectional conversion for visual flow builders.

Converts between ``FlowDefinition`` Pydantic models and the node/edge
format used by SvelteFlow / ReactFlow, enabling browser-based visual
editing of agent workflows.

Field mapping
-------------
=================  ==========================
FlowDefinition     SvelteFlow
=================  ==========================
node.id            node.id
node.label         node.data.label
node.type          node.type
node.position.x/y  node.position.x/y
node.agent_ref     node.data.agent_ref
node.config        node.data.config
edge.from_         edge.source
edge.to            edge.target
edge.condition     edge.data.condition
edge.predicate     edge.data.predicate
=================  ==========================

## Functions

- `def to_svelteflow(definition: FlowDefinition) -> Dict[str, Any]` — Convert a ``FlowDefinition`` to SvelteFlow node/edge format.
- `def from_svelteflow(sf_data: Dict[str, Any], flow_name: str) -> FlowDefinition` — Convert SvelteFlow node/edge data into a ``FlowDefinition``.
