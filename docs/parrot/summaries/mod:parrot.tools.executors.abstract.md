---
type: Wiki Summary
title: parrot.tools.executors.abstract
id: mod:parrot.tools.executors.abstract
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Abstract executor interface and serializable envelope.
relates_to:
- concept: class:parrot.tools.executors.abstract.AbstractToolExecutor
  rel: defines
- concept: class:parrot.tools.executors.abstract.ToolExecutionEnvelope
  rel: defines
- concept: func:parrot.tools.executors.abstract.build_envelope_from_tool
  rel: defines
- concept: func:parrot.tools.executors.abstract.project_permission_context
  rel: defines
- concept: func:parrot.tools.executors.abstract.project_trace_context
  rel: defines
- concept: mod:parrot.auth.permission
  rel: references
- concept: mod:parrot.core.events.lifecycle.trace
  rel: references
- concept: mod:parrot.tools.abstract
  rel: references
---

# `parrot.tools.executors.abstract`

Abstract executor interface and serializable envelope.

The envelope is the contract that crosses the process boundary. Anything
inside it must be JSON-serializable; anything not in it cannot be relied
on by the remote runtime.

## Classes

- **`ToolExecutionEnvelope(BaseModel)`** — The wire-format payload describing a single remote tool invocation.
- **`AbstractToolExecutor(ABC)`** — Pluggable transport that runs a tool somewhere other than here.

## Functions

- `def project_trace_context(tc: 'TraceContext | None') -> Optional[Dict[str, Any]]` — Project a TraceContext into a JSON-safe dict.
- `def project_permission_context(pctx: 'PermissionContext | None') -> Optional[Dict[str, Any]]` — Project a PermissionContext into a JSON-safe dict.
- `def build_envelope_from_tool(tool: 'AbstractTool', arguments: Dict[str, Any], permission_context: 'PermissionContext | None'=None, trace_context: 'TraceContext | None'=None, timeout_seconds: int=300, webhook_callback_url: Optional[str]=None) -> ToolExecutionEnvelope` — Construct a ToolExecutionEnvelope from a tool instance.
