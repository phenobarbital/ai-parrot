---
type: Wiki Entity
title: TraversalPattern
id: class:parrot.knowledge.ontology.schema.TraversalPattern
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Predefined graph traversal pattern for a known query type.
---

# TraversalPattern

Defined in [`parrot.knowledge.ontology.schema`](../summaries/mod:parrot.knowledge.ontology.schema.md).

```python
class TraversalPattern(BaseModel)
```

Predefined graph traversal pattern for a known query type.

Traversal patterns are the "fast path" — when the user's query matches
a trigger_intent keyword, the system skips LLM intent detection and
executes the AQL template directly.

New optional sections (FEAT-158):
- ``entity_extraction``: Named entity rules keyed by rule name.
- ``authorization``: Declarative access rules for this pattern.
- ``tool_call``: Tool invocation spec run after graph traversal.

Patterns without new sections load unchanged (backwards compatible).

Args:
    description: Human-readable description of what this pattern does.
    trigger_intents: Keywords for fast-path matching.
    query_template: AQL with bind variables.
    post_action: What happens after graph traversal.
    post_query: Field name to use as vector query (for vector_search).
    entity_extraction: Named entity extraction rules (FEAT-158).
    authorization: Declarative authorization spec (FEAT-158).
    tool_call: Tool invocation spec (FEAT-158).
