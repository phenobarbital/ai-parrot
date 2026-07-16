---
type: Wiki Entity
title: InteractiveToolkit
id: class:parrot.tools.interactive_toolkit.InteractiveToolkit
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Toolkit producing self-contained interactive HTML artifacts.
relates_to:
- concept: class:parrot.tools.toolkit.AbstractToolkit
  rel: extends
---

# InteractiveToolkit

Defined in [`parrot.tools.interactive_toolkit`](../summaries/mod:parrot.tools.interactive_toolkit.md).

```python
class InteractiveToolkit(AbstractToolkit)
```

Toolkit producing self-contained interactive HTML artifacts.

Usage::

    toolkit = InteractiveToolkit(artifact_store=store)
    tools = toolkit.get_tools()
    toolkit.set_bot(agent)   # enables enhance mode + prompt guidance

## Methods

- `def get_tools(self, **kwargs)` — Return generated tools; only ``interactive_render`` is terminal.
- `def set_bot(self, bot: Any) -> None` — Bind a bot for enhance-mode support and inject prompt guidance.
- `async def list_templates(self) -> List[Dict[str, Any]]` — Return available scaffold templates with their slots and libraries.
- `async def list_libraries(self) -> List[Dict[str, Any]]` — Return available JS libraries the LLM may use in artifacts.
- `async def get_scaffold(self, template_name: str) -> Dict[str, Any]` — Return one template's raw skeleton plus its allowed library details.
- `async def render(self, template_name: str, brief: str, libraries: Optional[List[str]]=None, mode: Literal['deterministic', 'enhance']='enhance', theme: Optional[str]=None, title: Optional[str]=None, data_context: Optional[Dict[str, Any]]=None) -> InteractiveRenderResult` — Build, (optionally) enhance, validate, and persist an interactive artifact.
