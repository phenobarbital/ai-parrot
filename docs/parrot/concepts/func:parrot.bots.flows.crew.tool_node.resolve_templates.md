---
type: Concept
title: resolve_templates()
id: func:parrot.bots.flows.crew.tool_node.resolve_templates
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Recursively resolve template placeholders inside a value.
---

# resolve_templates

```python
def resolve_templates(value: Any, *, input_text: str, results: Mapping[str, Any]) -> Any
```

Recursively resolve template placeholders inside a value.

Walks nested dicts/lists/tuples and substitutes placeholders found in
string values. Non-string leaves pass through unchanged.

Args:
    value: The value to resolve (str, dict, list, tuple, or any leaf).
    input_text: Replacement for the ``{input}`` placeholder.
    results: Mapping of node_id → stored output, used to resolve
        ``{nodes.<node_name>.output}`` placeholders.

Returns:
    The value with all placeholders resolved. A string that is exactly
    one placeholder returns the referenced value with native type
    preserved; embedded placeholders are substituted via ``str()``.

Raises:
    TemplateResolutionError: If a ``{nodes.<name>.output}`` placeholder
        references a node absent from ``results``.
