---
type: Wiki Entity
title: CELPredicateEvaluator
id: class:parrot.bots.flows.flow.cel_evaluator.CELPredicateEvaluator
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Evaluate CEL expression strings as flow transition predicates.
---

# CELPredicateEvaluator

Defined in [`parrot.bots.flows.flow.cel_evaluator`](../summaries/mod:parrot.bots.flows.flow.cel_evaluator.md).

```python
class CELPredicateEvaluator
```

Evaluate CEL expression strings as flow transition predicates.

CEL (Common Expression Language) provides safe, sandboxed evaluation
without arbitrary code execution risks. Expressions are compiled once
on construction and can be evaluated many times with different inputs.

Supported variables in expressions:
    - ``result``: Output from the source node (dict or Pydantic model)
    - ``error``: Exception message string (empty if no error)
    - ``ctx``: Shared flow context dict

Example::

    >>> evaluator = CELPredicateEvaluator('result.confidence > 0.8')
    >>> evaluator({"confidence": 0.95})
    True
    >>> evaluator({"confidence": 0.5})
    False
