---
type: Concept
title: resolve_config_value()
id: func:parrot.mcp.wrapper.resolve_config_value
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Resolve a configuration value against navconfig / os.environ.
---

# resolve_config_value

```python
def resolve_config_value(tool_name: str, key: str, value: Any) -> Any
```

Resolve a configuration value against navconfig / os.environ.

Resolution priority:

1. If *value* is a string that looks like an env-var name (all-uppercase +
   underscores), resolve it via :func:`_resolve_env_value`.
2. If *value* is ``None``, attempt the ``{TOOL_NAME}_{KEY}`` convention.
3. Return the original value unchanged otherwise.

Args:
    tool_name: Logical name of the tool/server (used for convention fallback).
    key: Configuration key name (used for convention fallback).
    value: Raw value from YAML.

Returns:
    Resolved value, or the original value when no resolution is found.
