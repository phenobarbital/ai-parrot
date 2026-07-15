---
type: Wiki Summary
title: parrot.flows.dev_loop.nodes.close
id: mod:parrot.flows.dev_loop.nodes.close
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: DevLoopCloseNode — terminal node that records a run's final state.
relates_to:
- concept: class:parrot.flows.dev_loop.nodes.close.DevLoopCloseNode
  rel: defines
- concept: mod:parrot
  rel: references
- concept: mod:parrot.bots.flows.core.context
  rel: references
- concept: mod:parrot.bots.flows.core.types
  rel: references
- concept: mod:parrot.conf
  rel: references
- concept: mod:parrot.flows.dev_loop.models
  rel: references
- concept: mod:parrot.flows.dev_loop.nodes.base
  rel: references
---

# `parrot.flows.dev_loop.nodes.close`

DevLoopCloseNode — terminal node that records a run's final state.

Implements **Module 10** of the FEAT-250 dev-loop refactor (G7). A pure
AI-Parrot node (no Claude Code dispatch) that posts a Jira summary comment
and transitions the ticket, then returns a terminal status dict. Used on
both the **initial** path (after ``DeploymentHandoffNode``) and the
**revision** path (after ``RevisionHandoffNode``); the transition label
branches on a ``shared["mode"]`` flag set by the runner (defaults to
``"initial"`` when absent).

Like the other terminal nodes (``FailureHandlerNode``), it MUST NOT raise:
Jira-side errors are logged and surfaced as a degraded status dict.

## Classes

- **`DevLoopCloseNode(DevLoopNode)`** — Terminal node — Jira summary comment + transition, then end the flow.
