---
type: Wiki Summary
title: parrot.flows.dev_loop.nodes.development
id: mod:parrot.flows.dev_loop.nodes.development
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: DevelopmentNode — sdd-worker dispatch.
relates_to:
- concept: class:parrot.flows.dev_loop.nodes.development.DevelopmentNode
  rel: defines
- concept: mod:parrot.bots.flows.core.context
  rel: references
- concept: mod:parrot.bots.flows.core.types
  rel: references
- concept: mod:parrot.flows.dev_loop.dispatcher
  rel: references
- concept: mod:parrot.flows.dev_loop.models
  rel: references
- concept: mod:parrot.flows.dev_loop.nodes.base
  rel: references
---

# `parrot.flows.dev_loop.nodes.development`

DevelopmentNode — sdd-worker dispatch.

Implements **Module 6**. A thin node that hands the worktree off to the
``sdd-worker`` subagent under ``permission_mode="acceptEdits"``. The
subagent reads the spec and implements all unblocked tasks in
dependency order, committing after each one.

The dispatcher's R4 cwd-safety check verifies that
``ResearchOutput.worktree_path`` lives under
``conf.WORKTREE_BASE_PATH``. This node trusts that check and does not
duplicate it.

## Classes

- **`DevelopmentNode(DevLoopNode)`** — Third node — dispatches the implementation phase to ``sdd-worker``.
