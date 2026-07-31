---
type: Wiki Entity
title: BaseRenderer
id: class:parrot.outputs.formats.base.BaseRenderer
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Base class for output renderers.
---

# BaseRenderer

Defined in [`parrot.outputs.formats.base`](../summaries/mod:parrot.outputs.formats.base.md).

```python
class BaseRenderer(ABC)
```

Base class for output renderers.

## Methods

- `def get_expected_content_type(cls) -> Type` — Define what type of content this renderer expects.
- `def execute_code(self, code: str, pandas_tool: 'PythonPandasTool | None'=None, execution_state: Optional[Dict[str, Any]]=None, extra_namespace: Optional[Dict[str, Any]]=None, **kwargs) -> Tuple[Optional[Dict[str, Any]], Optional[str]]` — Execute code within the PythonPandasTool or fallback namespace.
- `async def render(self, response: Any, environment: str='terminal', export_format: str='html', include_code: bool=False, **kwargs) -> Tuple[Any, Optional[Any]]` — Render response in the appropriate format.
