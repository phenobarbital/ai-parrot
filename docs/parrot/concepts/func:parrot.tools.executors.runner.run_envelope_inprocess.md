---
type: Concept
title: run_envelope_inprocess()
id: func:parrot.tools.executors.runner.run_envelope_inprocess
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Execute *envelope* in the current Python process.
---

# run_envelope_inprocess

```python
async def run_envelope_inprocess(envelope: ToolExecutionEnvelope) -> Any
```

Execute *envelope* in the current Python process.

Returns the :class:`ToolResult` produced by the tool's underlying
``_execute`` implementation (or by the toolkit-bound method). The
caller is responsible for any further normalisation — typically
``AbstractTool.execute`` does that wrapping.

Layered behaviour:

* Plain ``AbstractTool`` subclasses are instantiated and
  ``await tool._execute(**arguments)`` is called.
* Toolkit-bound envelopes (``method_name is not None``) instantiate
  the toolkit, look up the named method, and call it with
  ``arguments``. This mirrors what :meth:`ToolkitTool._execute`
  would do, minus the ``_pre_execute`` / ``_post_execute`` hooks
  because we want the remote runtime to behave like a pure worker.
