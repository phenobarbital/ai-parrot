---
type: Concept
title: jql_quote()
id: func:parrot.knowledge.ontology.tool_dispatcher.jql_quote
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Escape a value for safe inclusion as a JQL string literal.
---

# jql_quote

```python
def jql_quote(value: Any) -> str
```

Escape a value for safe inclusion as a JQL string literal.

Wraps the value in double quotes and escapes embedded double quotes and
backslashes (adversarial input mitigation).

Args:
    value: Any value to escape.

Returns:
    A safely double-quoted string for use in a JQL expression.

Example::

    >>> jql_quote('Jesús" OR project="OTHER')
    '"Jesús\" OR project=\"OTHER"'
