---
type: Wiki Entity
title: ResolvedIntent
id: class:parrot.knowledge.ontology.schema.ResolvedIntent
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Result of intent resolution.
---

# ResolvedIntent

Defined in [`parrot.knowledge.ontology.schema`](../summaries/mod:parrot.knowledge.ontology.schema.md).

```python
class ResolvedIntent(BaseModel)
```

Result of intent resolution.

New optional fields (FEAT-158):
- ``resolved_entities``: Mapping from rule name to resolved ``_id``.
- ``tool_call``: Tool invocation spec from the matched pattern.
- ``denial_reason``: Human-readable reason for authorization denial.

Args:
    action: Whether the query needs graph traversal or vector-only.
    pattern: Name of the matched traversal pattern (if any).
    aql: AQL query to execute (if graph_query).
    params: Bind variables for the AQL query.
    collection_binds: @@collection resolutions for AQL.
    post_action: What to do after graph traversal.
    post_query: Field to use as vector search query.
    source: How the intent was resolved.
    resolved_entities: Rule name → resolved graph ``_id`` (FEAT-158).
    tool_call: Tool invocation spec linked to this intent (FEAT-158).
    denial_reason: Reason for authorization denial, if applicable (FEAT-158).
