---
type: Wiki Summary
title: parrot.cli.tool_worker
id: mod:parrot.cli.tool_worker
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Worker-side entrypoint for remote tool execution.
relates_to:
- concept: mod:parrot.tools.abstract
  rel: references
- concept: mod:parrot.tools.executors.abstract
  rel: references
- concept: mod:parrot.tools.executors.runner
  rel: references
---

# `parrot.cli.tool_worker`

Worker-side entrypoint for remote tool execution.

This module is what the ``parrot-tools`` Docker image invokes:
``python -m parrot.cli.tool_worker --envelope -`` reads a
:class:`~parrot.tools.executors.ToolExecutionEnvelope` (JSON) from
stdin (or from a file when ``--envelope`` is a path) and prints the
resulting :class:`~parrot.tools.abstract.ToolResult` (JSON) to stdout
between sentinel markers so the executor that owns the worker can
extract the payload from the surrounding logs.

The worker is intentionally minimal:

* Permission checks have already happened on the caller side. We do not
  re-enforce them here — the envelope is treated as authoritative.
* Lifecycle events fire on the caller, not in the worker.
* The exit code is ``0`` on a well-formed ToolResult (even one with
  ``status="error"``) and non-zero only when the worker itself fails
  (invalid envelope, import error, unhandled exception).

## Functions

- `def main(argv: list[str] | None=None) -> int`
