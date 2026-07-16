---
type: Wiki Summary
title: parrot.flows.dev_loop.nodes.intent_classifier
id: mod:parrot.flows.dev_loop.nodes.intent_classifier
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: IntentClassifierNode — first node of the dev-loop flow (FEAT-132).
relates_to:
- concept: class:parrot.flows.dev_loop.nodes.intent_classifier.IntentClassifierNode
  rel: defines
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

# `parrot.flows.dev_loop.nodes.intent_classifier`

IntentClassifierNode — first node of the dev-loop flow (FEAT-132).

Absorbs the universal validation logic previously in ``BugIntakeNode``
(allowlist heads, path-traversal checks on FlowtaskCriterion).

After validation it emits a ``flow.intake_validated`` event to Redis
and returns the ``WorkBrief`` so that the flow factory's
``on_condition`` predicates can route on ``result.kind``.

Both ``ctx['bug_brief']`` (legacy key) and ``ctx['work_brief']`` (forward-
compat) are populated so Development / QA / Failure nodes that already
read ``bug_brief`` keep working without modification.

## Classes

- **`IntentClassifierNode(DevLoopNode)`** — Validates a :class:`WorkBrief` and routes by ``kind``.
