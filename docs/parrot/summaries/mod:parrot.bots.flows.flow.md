---
type: Wiki Summary
title: parrot.bots.flows.flow
id: mod:parrot.bots.flows.flow
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: parrot.bots.flows.flow -- AgentsFlow sub-package.
relates_to:
- concept: mod:parrot.bots.flows
  rel: references
---

# `parrot.bots.flows.flow`

parrot.bots.flows.flow -- AgentsFlow sub-package.

Exports the AgentsFlow executor and its registry utilities.
Mirrors the layout of parrot.bots.flows.crew.

Node types from flow.py (@register_node decorated):
  DecisionNode, InteractiveDecisionNode, SynthesisNode
  -- these are the DAG-executor node wrappers (use NODE_REGISTRY keys).

Decision primitive types from nodes.py (canonical decision logic):
  DecisionFlowNode, InteractiveDecisionNode (canonical), plus config/result types.

Note: InteractiveDecisionNode exported here is from flow.py
(the @register_node('interactive_decision') wrapper). The canonical
InteractiveDecisionNode from nodes.py is available as:
  from parrot.bots.flows.flow.nodes import InteractiveDecisionNode
