---
type: Wiki Summary
title: parrot.flows.dev_loop.nodes.qa
id: mod:parrot.flows.dev_loop.nodes.qa
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: QANode — sdd-qa dispatch in plan mode + pluggable code-review gate.
relates_to:
- concept: class:parrot.flows.dev_loop.nodes.qa.QANode
  rel: defines
- concept: mod:parrot.bots.flows.core.context
  rel: references
- concept: mod:parrot.bots.flows.core.types
  rel: references
- concept: mod:parrot.flows.dev_loop.code_review
  rel: references
- concept: mod:parrot.flows.dev_loop.dispatcher
  rel: references
- concept: mod:parrot.flows.dev_loop.models
  rel: references
- concept: mod:parrot.flows.dev_loop.nodes.base
  rel: references
---

# `parrot.flows.dev_loop.nodes.qa`

QANode — sdd-qa dispatch in plan mode + pluggable code-review gate.

Implements **Module 7** (FEAT-129/132) and its FEAT-270 extension. Dispatches
the ``sdd-qa`` subagent under ``permission_mode="plan"`` with no edit/write
tools so the deterministic QA pass is strictly read-only. The subagent runs
each acceptance criterion as a subprocess (deterministic — exit code is the
source of truth, not LLM judgement; spec G6) and runs lint, then returns a
:class:`QAReport`.

The code-review gate (FEAT-250, extended by FEAT-270) is additive and
pluggable: it delegates to an :class:`AbstractCodeReviewDispatcher` (Claude,
Codex, or Gemini) which is allowed to fix issues it finds and commit the
fixes to the worktree branch. When the reviewer reports modified files, the
deterministic QA pass re-runs to confirm the fix didn't regress anything.

The node returns the report regardless of ``passed`` — the flow factory
(TASK-886) decides routing via a :class:`FlowTransition`.

## Classes

- **`QANode(DevLoopNode)`** — Fourth node — runs deterministic acceptance verification.
