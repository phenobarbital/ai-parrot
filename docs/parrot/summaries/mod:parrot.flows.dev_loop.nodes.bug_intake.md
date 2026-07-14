---
type: Wiki Summary
title: parrot.flows.dev_loop.nodes.bug_intake
id: mod:parrot.flows.dev_loop.nodes.bug_intake
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: BugIntakeNode — bug-specific intake hook for the dev-loop flow.
relates_to:
- concept: class:parrot.flows.dev_loop.nodes.bug_intake.BugIntakeNode
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

# `parrot.flows.dev_loop.nodes.bug_intake`

BugIntakeNode — bug-specific intake hook for the dev-loop flow.

FEAT-132 scope-down: universal validation (allowlist heads, path-traversal)
has moved to :class:`IntentClassifierNode`, which runs before this node on
the bug path. ``BugIntakeNode`` is now a thin extension hook reserved for
future bug-only enrichment (severity classification, stack-trace parsing,
etc.). For v1 it re-emits ``flow.bug_brief_validated`` so existing
downstream observers keep working, and returns the brief unchanged.

This node deliberately does NOT call the dispatcher; the most
expensive thing it does is one ``XADD`` to the flow event stream.

## Classes

- **`BugIntakeNode(DevLoopNode)`** — Bug-specific intake hook — emits ``flow.bug_brief_validated`` event.
