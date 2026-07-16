---
type: Wiki Summary
title: parrot.bots.flows.core.fsm
id: mod:parrot.bots.flows.core.fsm
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Flow Primitives — FSM Module.
relates_to:
- concept: class:parrot.bots.flows.core.fsm.AgentTaskMachine
  rel: defines
- concept: class:parrot.bots.flows.core.fsm.TransitionCondition
  rel: defines
---

# `parrot.bots.flows.core.fsm`

Flow Primitives — FSM Module.

Provides ``AgentTaskMachine`` (StateMachine subclass) and ``TransitionCondition``
enum for state-based agent lifecycle management.

Extracted from ``parrot.bots.flow.fsm`` to serve as the shared primitive
used by both AgentCrew and AgentsFlow engines.

## Classes

- **`TransitionCondition(str, Enum)`** — Predefined conditions that can trigger a flow transition.
- **`AgentTaskMachine(StateMachine)`** — Finite State Machine describing the lifecycle of a single node execution.
