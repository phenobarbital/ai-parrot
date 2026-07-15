---
type: Wiki Summary
title: parrot.bots.flows.flow.nodes
id: mod:parrot.bots.flows.flow.nodes
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: flows/flow/nodes.py — Decision + Interactive node types (FEAT-196 / TASK-1311).
relates_to:
- concept: class:parrot.bots.flows.flow.nodes.ApprovalDecision
  rel: defines
- concept: class:parrot.bots.flows.flow.nodes.BinaryDecision
  rel: defines
- concept: class:parrot.bots.flows.flow.nodes.DecisionFlowNode
  rel: defines
- concept: class:parrot.bots.flows.flow.nodes.DecisionMode
  rel: defines
- concept: class:parrot.bots.flows.flow.nodes.DecisionNodeConfig
  rel: defines
- concept: class:parrot.bots.flows.flow.nodes.DecisionResult
  rel: defines
- concept: class:parrot.bots.flows.flow.nodes.DecisionType
  rel: defines
- concept: class:parrot.bots.flows.flow.nodes.EscalationPolicy
  rel: defines
- concept: class:parrot.bots.flows.flow.nodes.InteractiveDecisionNode
  rel: defines
- concept: class:parrot.bots.flows.flow.nodes.MultiChoiceDecision
  rel: defines
- concept: class:parrot.bots.flows.flow.nodes.VoteWeight
  rel: defines
- concept: mod:parrot.bots
  rel: references
- concept: mod:parrot.bots.flows.core.context
  rel: references
- concept: mod:parrot.bots.flows.core.fsm
  rel: references
- concept: mod:parrot.bots.flows.core.node
  rel: references
- concept: mod:parrot.bots.flows.core.result
  rel: references
- concept: mod:parrot.bots.flows.core.types
  rel: references
---

# `parrot.bots.flows.flow.nodes`

flows/flow/nodes.py — Decision + Interactive node types (FEAT-196 / TASK-1311).

Rewrites DecisionFlowNode, InteractiveDecisionNode, and all related types
as subclasses of parrot.bots.flows.core.node.Node (frozen Pydantic).

Public symbol names and attribute shapes are preserved exactly from the
legacy parrot/bots/flow/decision_node.py and interactive_node.py.
Internal implementation adopts NodeResult, FlowContext.shared_data, and
build_node_metadata from the canonical parrot.bots.flows.core package.

Mirrors the layout of parrot/bots/flows/crew/nodes.py — single file
containing all decision + interactive node types for this subpackage.

Classes:
    DecisionMode — Enum: CIO, BALLOT, CONSENSUS
    DecisionType — Enum: BINARY, APPROVAL, MULTI_CHOICE, CUSTOM
    VoteWeight — Enum: EQUAL, SENIORITY, CONFIDENCE, CUSTOM
    BinaryDecision — Pydantic model for YES/NO decisions
    ApprovalDecision — Pydantic model for APPROVE/REJECT/ESCALATE decisions
    MultiChoiceDecision — Pydantic model for multi-option decisions
    DecisionResult — Structured result from a decision node
    EscalationPolicy — Configuration for HITL escalation
    DecisionNodeConfig — Configuration for DecisionFlowNode
    DecisionFlowNode — Multi-agent decision orchestrator (subclasses Node)
    InteractiveDecisionNode — CLI interactive decision node (subclasses Node)

## Classes

- **`DecisionMode(str, Enum)`** — Operating mode for decision-making process.
- **`DecisionType(str, Enum)`** — Types of decisions the node can make.
- **`VoteWeight(str, Enum)`** — Pre-defined vote weighting strategies.
- **`BinaryDecision(BaseModel)`** — Binary YES/NO decision schema.
- **`ApprovalDecision(BaseModel)`** — Approval gate decision schema.
- **`MultiChoiceDecision(BaseModel)`** — Multi-option choice decision schema.
- **`DecisionResult(BaseModel)`** — Structured result from a decision node.
- **`EscalationPolicy(BaseModel)`** — Defines when and how to escalate to HITL.
- **`DecisionNodeConfig(BaseModel)`** — Configuration for DecisionFlowNode.
- **`DecisionFlowNode(Node)`** — Decision orchestrator node for AgentsFlow workflows.
- **`InteractiveDecisionNode(Node)`** — A Flow node that asks the user a multiple-choice question in the CLI.
