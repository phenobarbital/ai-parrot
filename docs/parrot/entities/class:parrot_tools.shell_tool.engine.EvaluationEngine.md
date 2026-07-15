---
type: Wiki Entity
title: EvaluationEngine
id: class:parrot_tools.shell_tool.engine.EvaluationEngine
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: 'Supports:'
---

# EvaluationEngine

Defined in [`parrot_tools.shell_tool.engine`](../summaries/mod:parrot_tools.shell_tool.engine.md).

```python
class EvaluationEngine
```

Supports:
    - regex: {"eval_type": "regex", "expr": "pattern", "group": 1}
    - jsonpath (lite): {"eval_type": "jsonpath", "expr": "$.a.b[0]"}
    - jq (requires 'jq' in PATH): {"eval_type": "jq", "expr": ".items[] | .name"}

## Methods

- `def eval_regex(text: str, expr: str, group: Optional[Union[int, str]]=None) -> str`
- `def eval_jsonpath(src: Union[str, Any], expr: str, as_json: bool=False) -> str`
- `def eval_jq(src: Union[str, Any], expr: str, as_json: bool=False) -> str`
