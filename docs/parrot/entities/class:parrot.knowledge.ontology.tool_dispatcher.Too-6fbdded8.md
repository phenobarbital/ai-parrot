---
type: Wiki Entity
title: ToolCallDispatcher
id: class:parrot.knowledge.ontology.tool_dispatcher.ToolCallDispatcher
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Renders and invokes a tool call specified by a ``ToolCallSpec``.
---

# ToolCallDispatcher

Defined in [`parrot.knowledge.ontology.tool_dispatcher`](../summaries/mod:parrot.knowledge.ontology.tool_dispatcher.md).

```python
class ToolCallDispatcher
```

Renders and invokes a tool call specified by a ``ToolCallSpec``.

Uses a single shared ``jinja2.Environment`` with ``StrictUndefined`` and
the following registered safety filters:

- ``jql_quote``: escape a value for JQL string literals.
- ``jira_accounts``: validate and join Jira accountIds.
- ``join_ids``: join ``_id`` values from a list of dicts.
- ``map_attr``: extract an attribute from each dict in a list.
- ``json``: serialize a value to a JSON string.

**autoescape=False** is intentional. Outputs are non-HTML query strings;
safety lives in the per-filter escapers above.

Args:
    tool_manager: The ``ToolManager`` instance used for tool resolution.

## Methods

- `async def dispatch(self, spec: ToolCallSpec, graph_result: list[dict[str, Any]], user_context: dict[str, Any], extras: dict[str, Any] | None=None) -> dict[str, Any]` — Render parameters and invoke the tool specified by ``spec``.
