---
type: Wiki Entity
title: ToolCallSpec
id: class:parrot.knowledge.ontology.schema.ToolCallSpec
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Specification for a tool invocation after graph traversal.
---

# ToolCallSpec

Defined in [`parrot.knowledge.ontology.schema`](../summaries/mod:parrot.knowledge.ontology.schema.md).

```python
class ToolCallSpec(BaseModel)
```

Specification for a tool invocation after graph traversal.

Args:
    toolkit: Toolkit class name (e.g., ``"JiraToolkit"``).
    method: Method name on the toolkit (e.g., ``"jira_search_issues"``).
    credential_mode: How credentials are resolved for the call.
    parameters: Jinja2-templated parameters rendered with
        ``(graph, ctx, extras)`` namespaces.
    result_binding: Key under which the result is stored in
        ``ContextEnvelope.tool_result``.
    empty_team_behavior: What to do when the graph result is empty.
