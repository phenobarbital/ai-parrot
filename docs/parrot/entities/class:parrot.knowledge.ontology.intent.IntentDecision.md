---
type: Wiki Entity
title: IntentDecision
id: class:parrot.knowledge.ontology.intent.IntentDecision
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Structured output from LLM intent classification.
---

# IntentDecision

Defined in [`parrot.knowledge.ontology.intent`](../summaries/mod:parrot.knowledge.ontology.intent.md).

```python
class IntentDecision(BaseModel)
```

Structured output from LLM intent classification.

Args:
    action: Whether graph traversal is needed.
    pattern: Known pattern name, "dynamic", or None.
    aql: Dynamic AQL query (only when pattern="dynamic").
    suggested_post_action: Post-action hint from LLM.
