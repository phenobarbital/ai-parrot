---
type: Wiki Summary
title: parrot.tools.executors.runner
id: mod:parrot.tools.executors.runner
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: In-process envelope runner shared by LocalToolExecutor and the k8s/qworker
  worker entrypoints.
relates_to:
- concept: func:parrot.tools.executors.runner.run_envelope_inprocess
  rel: defines
- concept: mod:parrot.tools.executors.abstract
  rel: references
---

# `parrot.tools.executors.runner`

In-process envelope runner shared by LocalToolExecutor and the k8s/qworker worker entrypoints.

The runner takes a deserialized ``ToolExecutionEnvelope``, imports the
referenced class, instantiates it, and invokes the underlying
``_execute`` method (or the toolkit-bound method) returning a
:class:`ToolResult`. It is intentionally minimal: permission checks,
lifecycle events, and result-shape normalisation have already happened
on the caller side (or will, when the result returns).

## Functions

- `async def run_envelope_inprocess(envelope: ToolExecutionEnvelope) -> Any` — Execute *envelope* in the current Python process.
