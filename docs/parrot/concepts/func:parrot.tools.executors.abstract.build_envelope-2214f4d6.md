---
type: Concept
title: build_envelope_from_tool()
id: func:parrot.tools.executors.abstract.build_envelope_from_tool
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Construct a ToolExecutionEnvelope from a tool instance.
---

# build_envelope_from_tool

```python
def build_envelope_from_tool(tool: 'AbstractTool', arguments: Dict[str, Any], permission_context: 'PermissionContext | None'=None, trace_context: 'TraceContext | None'=None, timeout_seconds: int=300, webhook_callback_url: Optional[str]=None) -> ToolExecutionEnvelope
```

Construct a ToolExecutionEnvelope from a tool instance.

The tool's ``_init_kwargs`` (captured by ``AbstractTool.__init__``)
travel as ``tool_init_kwargs``. The ``executor`` kwarg is stripped
so the remote-side reconstruction runs the tool locally inside the
worker process.

For :class:`ToolkitTool` instances, the toolkit class is what gets
imported on the remote side, not ``ToolkitTool`` itself; the
``method_name`` field tells the worker which method to call on the
reconstructed toolkit. ``tool_init_kwargs`` then carries the
toolkit's constructor arguments (not the ToolkitTool's).

Raises:
    ValueError: When the tool's class cannot be imported by path
        (e.g. defined in ``__main__``). Such tools cannot be
        executed remotely; fix the test by moving the class into
        an importable module.
