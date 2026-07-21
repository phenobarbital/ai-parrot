---
type: Concept
title: loads()
id: func:parrot.yaml-rs.python.yaml_rs.loads
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Deserialize YAML string to Python object.
---

# loads

```python
def loads(yaml_str: str, loader: Optional[Any]=None) -> Any
```

Deserialize YAML string to Python object.

Args:
    yaml_str: YAML formatted string

Returns:
    Python object (dict, list, etc.)

Performance:
    - Rust implementation: 5-20x faster than PyYAML
    - Falls back to PyYAML if Rust extension not available
