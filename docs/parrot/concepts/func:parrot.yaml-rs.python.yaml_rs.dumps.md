---
type: Concept
title: dumps()
id: func:parrot.yaml-rs.python.yaml_rs.dumps
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Serialize Python object to YAML string.
---

# dumps

```python
def dumps(obj: Any, indent: int=2, default_flow_style: bool=False, sort_keys: bool=False) -> str
```

Serialize Python object to YAML string.
Args:
    obj: Python object (dict, list, BaseModel, dataclass)
    indent: Indentation spaces (default: 2)
    default_flow_style: Use flow style (default: False)
    sort_keys: Sort dictionary keys (default: False)

Returns:
    YAML string

Performance:
    - Rust implementation: 10-50x faster than PyYAML
    - Falls back to PyYAML if Rust extension not available
