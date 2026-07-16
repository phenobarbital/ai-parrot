---
type: Wiki Summary
title: parrot.flows.dev_loop.nodes.failure_handler
id: mod:parrot.flows.dev_loop.nodes.failure_handler
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: FailureHandlerNode — Jira escalation on flow failure.
relates_to:
- concept: class:parrot.flows.dev_loop.nodes.failure_handler.FailureHandlerNode
  rel: defines
- concept: mod:parrot.bots.flows.core.context
  rel: references
- concept: mod:parrot.bots.flows.core.types
  rel: references
- concept: mod:parrot.flows.dev_loop.models
  rel: references
- concept: mod:parrot.flows.dev_loop.nodes.base
  rel: references
---

# `parrot.flows.dev_loop.nodes.failure_handler`

FailureHandlerNode — Jira escalation on flow failure.

Implements **Module 9** of the dev-loop spec. Terminal failure node
routed to either by:

* The QA pass/fail transition when ``QAReport.passed is False``.
* A global error transition when any earlier node raises a
  ``DispatchExecutionError``, ``DispatchOutputValidationError``, or
  ``RuntimeError``.

Behavior: post a structured Jira comment, transition the ticket to
*Needs Human Review*, and reassign to ``BugBrief.escalation_assignee``.
The node MUST NOT raise — Jira-side errors are logged and the node
returns a structured ``dict`` describing the outcome.

## Classes

- **`FailureHandlerNode(DevLoopNode)`** — Terminal failure node — comment + transition + reassign on Jira.
