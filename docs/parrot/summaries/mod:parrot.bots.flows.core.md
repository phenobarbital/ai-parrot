---
type: Wiki Summary
title: parrot.bots.flows.core
id: mod:parrot.bots.flows.core
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: parrot.bots.flows.core — canonical public API for flow primitives.
relates_to:
- concept: mod:parrot.bots.flows
  rel: references
---

# `parrot.bots.flows.core`

parrot.bots.flows.core — canonical public API for flow primitives.

All shared types, FSM, node hierarchy, result models, context, transitions,
and storage mixins are available from this single import path.

Usage::

    from parrot.bots.flows.core import (
        AgentLike, FlowStatus,
        AgentTaskMachine, TransitionCondition,
        Node, AgentNode, StartNode, EndNode,
        FlowResult, NodeExecutionInfo, FlowContext, FlowTransition,
        ExecutionMemory, PersistenceMixin, SynthesisMixin,
    )
