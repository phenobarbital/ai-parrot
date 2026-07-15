---
type: Wiki Entity
title: ToolExecutionEnvelope
id: class:parrot.tools.executors.abstract.ToolExecutionEnvelope
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: The wire-format payload describing a single remote tool invocation.
---

# ToolExecutionEnvelope

Defined in [`parrot.tools.executors.abstract`](../summaries/mod:parrot.tools.executors.abstract.md).

```python
class ToolExecutionEnvelope(BaseModel)
```

The wire-format payload describing a single remote tool invocation.

Attributes:
    tool_import_path: Dotted Python path of the tool class, formatted
        as ``"<module>:<qualname>"`` so the remote worker can do
        ``importlib.import_module(module)`` and ``getattr(cls)``.
    tool_init_kwargs: Constructor arguments captured from the caller's
        instance. Forwarded as ``cls(**tool_init_kwargs)`` on the
        remote side. The ``executor`` kwarg is stripped before
        transit so the remote tool runs locally.
    method_name: For ``ToolkitTool`` envelopes, the name of the bound
        method to invoke on the reconstructed toolkit. ``None`` for
        plain ``AbstractTool`` subclasses.
    arguments: Validated tool arguments (the kwargs that would
        normally be passed to ``_execute``).
    permission_context: JSON projection of the caller's
        ``PermissionContext``. The remote side does NOT re-run
        permission checks — Layer 2 enforcement happens on the
        caller before the envelope is sent. This is informational.
    trace_context: JSON projection of the parent span so the remote
        runtime can mint a child span and keep the trace connected.
    timeout_seconds: Maximum wall-clock seconds to wait for the
        remote runtime to return a result.
    webhook_callback_url: When set, the executor returns immediately
        with a ``"pending"`` ToolResult; the remote runtime POSTs the
        final ToolResult to this URL when it completes. The webhook
        handler is registered separately.
    envelope_version: Schema version. Bumped when the contract
        changes in a backwards-incompatible way.
