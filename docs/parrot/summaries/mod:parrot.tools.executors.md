---
type: Wiki Summary
title: parrot.tools.executors
id: mod:parrot.tools.executors
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Remote tool executors for AI-Parrot.
relates_to:
- concept: mod:parrot.tools
  rel: references
- concept: mod:parrot.tools.abstract
  rel: references
---

# `parrot.tools.executors`

Remote tool executors for AI-Parrot.

Tools can be marked for off-process execution by passing an
``executor=`` kwarg when constructing an ``AbstractTool`` or
``AbstractToolkit``. The executor takes the validated tool arguments and
returns a ``ToolResult`` from somewhere else — an ephemeral Kubernetes
pod, the Qworker service over HTTP, or a Redis Stream consumer — while
the agent loop keeps its existing in-process contract.

Public API:

* :class:`AbstractToolExecutor` — the interface every executor implements
* :class:`LocalToolExecutor` — reference implementation that runs the
  tool in-process (mostly used for tests and as the default behaviour)
* :class:`K8sToolExecutor` — runs the tool in an ephemeral
  ``batch/v1 Job`` against a Kubernetes cluster
* :class:`QworkerToolExecutor` — dispatches the tool to the Qworker
  service via its HTTP client or via Redis Streams
* :class:`ToolExecutionEnvelope` — the serializable contract that
  travels over the wire to the remote runtime
