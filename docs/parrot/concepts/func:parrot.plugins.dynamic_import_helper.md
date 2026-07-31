---
type: Concept
title: dynamic_import_helper()
id: func:parrot.plugins.dynamic_import_helper
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Helper for __getattr__ to dynamically import plugin modules.
---

# dynamic_import_helper

```python
def dynamic_import_helper(package_name: str, attr_name: str)
```

Helper for __getattr__ to dynamically import plugin modules.

Args:
    package_name: Package name (e.g., 'parrot.agents')
    attr_name: Attribute being accessed (e.g., 'HRAgent')

Returns:
    The imported class/module if found

Raises:
    AttributeError: If the attribute cannot be found

Example:
    # In parrot/agents/__init__.py:
    def __getattr__(name):
        from parrot.plugins import dynamic_import_helper
        return dynamic_import_helper(__name__, name)
