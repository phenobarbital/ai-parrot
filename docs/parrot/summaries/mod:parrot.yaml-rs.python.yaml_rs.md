---
type: Wiki Summary
title: parrot.yaml-rs.python.yaml_rs
id: mod:parrot.yaml-rs.python.yaml_rs
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Module parrot.yaml-rs.python.yaml_rs
relates_to:
- concept: func:parrot.yaml-rs.python.yaml_rs.dumps
  rel: defines
- concept: func:parrot.yaml-rs.python.yaml_rs.loads
  rel: defines
- concept: mod:parrot
  rel: references
---

# `parrot.yaml-rs.python.yaml_rs`

## Functions

- `def dumps(obj: Any, indent: int=2, default_flow_style: bool=False, sort_keys: bool=False) -> str` — Serialize Python object to YAML string.
- `def loads(yaml_str: str, loader: Optional[Any]=None) -> Any` — Deserialize YAML string to Python object.
