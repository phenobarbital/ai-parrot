---
type: Wiki Summary
title: parrot.bots.flows.flow.cel_evaluator
id: mod:parrot.bots.flows.flow.cel_evaluator
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: CEL Predicate Evaluator for AgentsFlow transition conditions.
relates_to:
- concept: class:parrot.bots.flows.flow.cel_evaluator.CELPredicateEvaluator
  rel: defines
---

# `parrot.bots.flows.flow.cel_evaluator`

CEL Predicate Evaluator for AgentsFlow transition conditions.

Uses cel-python to compile and evaluate Common Expression Language (CEL)
expressions as flow transition predicates. CEL provides safe, sandboxed
evaluation without arbitrary code execution risks.

Example::

    >>> evaluator = CELPredicateEvaluator('result.decision == "pizza"')
    >>> evaluator({"decision": "pizza"})
    True
    >>> evaluator({"decision": "sushi"})
    False

## Classes

- **`CELPredicateEvaluator`** — Evaluate CEL expression strings as flow transition predicates.
