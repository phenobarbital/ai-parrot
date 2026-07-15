---
type: Wiki Summary
title: parrot.bots.flows
id: mod:parrot.bots.flows
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: parrot.bots.flows — shared orchestration primitives for AgentCrew & AgentsFlow.
relates_to:
- concept: mod:parrot.bots
  rel: references
---

# `parrot.bots.flows`

parrot.bots.flows — shared orchestration primitives for AgentCrew & AgentsFlow.

All public symbols are re-exported from sub-packages:

- ``core``: shared types, FSM, nodes, result models, context, storage
- ``crew``: ``AgentCrew``, ``CrewAgentNode``
- ``agents``: orchestrator agents
- ``tools``: ``ResultRetrievalTool``
- ``flow``: ``AgentsFlow``, flow definition models, decision nodes

Usage::

    from parrot.bots.flows import (
        AgentLike, FlowStatus,
        Node, AgentNode, FlowResult, FlowContext, FlowTransition,
        AgentCrew, CrewAgentNode,
        OrchestratorAgent,
        ResultRetrievalTool,
        AgentsFlow,
        FlowDefinition, NodeDefinition, EdgeDefinition,
        DecisionFlowNode, BinaryDecision,
    )

Demoted (submodule-only — not exported at root):
- ``CELPredicateEvaluator``  → ``parrot.bots.flows.flow.cel_evaluator``
- ``ACTION_REGISTRY``, action classes → ``parrot.bots.flows.flow.actions``
- ``FlowLoader`` → ``parrot.bots.flows.flow.loader``
- ``from_svelteflow``, ``to_svelteflow`` → ``parrot.bots.flows.flow.svelteflow``
