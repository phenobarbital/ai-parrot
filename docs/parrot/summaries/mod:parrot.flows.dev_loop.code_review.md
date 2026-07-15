---
type: Wiki Summary
title: parrot.flows.dev_loop.code_review
id: mod:parrot.flows.dev_loop.code_review
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: AbstractCodeReviewDispatcher ABC + factory (FEAT-270).
relates_to:
- concept: class:parrot.flows.dev_loop.code_review.AbstractCodeReviewDispatcher
  rel: defines
- concept: class:parrot.flows.dev_loop.code_review.ClaudeCodeReviewDispatcher
  rel: defines
- concept: class:parrot.flows.dev_loop.code_review.CodeReviewDispatcherFactory
  rel: defines
- concept: class:parrot.flows.dev_loop.code_review.CodexCodeReviewDispatcher
  rel: defines
- concept: class:parrot.flows.dev_loop.code_review.GeminiCodeReviewDispatcher
  rel: defines
- concept: mod:parrot
  rel: references
- concept: mod:parrot.conf
  rel: references
- concept: mod:parrot.flows.dev_loop.dispatcher
  rel: references
- concept: mod:parrot.flows.dev_loop.models
  rel: references
---

# `parrot.flows.dev_loop.code_review`

AbstractCodeReviewDispatcher ABC + factory (FEAT-270).

Decouples the QA node's code-review gate from any specific development
dispatcher. Concrete review dispatchers wrap the existing Claude/Codex/Gemini
development dispatchers with a write-enabled review profile, allowing the
reviewer to fix issues it discovers and commit fixes to the worktree branch.

See ``sdd/specs/new-codereviewers.spec.md`` for the full design.

## Classes

- **`AbstractCodeReviewDispatcher(ABC)`** — ABC for all code review dispatchers.
- **`CodeReviewDispatcherFactory`** — Factory for creating code review dispatchers.
- **`ClaudeCodeReviewDispatcher(AbstractCodeReviewDispatcher)`** — Wraps :class:`ClaudeCodeDispatcher` with a write-enabled review profile.
- **`CodexCodeReviewDispatcher(AbstractCodeReviewDispatcher)`** — Wraps :class:`CodexCodeDispatcher` with a write-enabled sandbox profile.
- **`GeminiCodeReviewDispatcher(AbstractCodeReviewDispatcher)`** — Wraps :class:`GeminiCodeDispatcher` with sandbox disabled + auto-edit.
