---
type: Concept
title: load_tool_class()
id: func:parrot.mcp.wrapper.load_tool_class
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Dynamic loading of a tool class by its class name.
---

# load_tool_class

```python
def load_tool_class(tool_name: str)
```

Dynamic loading of a tool class by its class name.

Resolution order:
1. parrot.tools.<lowercase_name>           (top-level module)
2. parrot.tools.<lowercase_name>.bundle     (bundle convention)
3. parrot.tools.<lowercase_name>.<lowercase_name>
4. parrot.tools.<subpackage>                (sub-package __init__ re-exports)
5. parrot.tools  (top-level __getattr__ / re-exports)
