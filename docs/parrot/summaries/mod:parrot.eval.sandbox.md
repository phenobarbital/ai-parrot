---
type: Wiki Summary
title: parrot.eval.sandbox
id: mod:parrot.eval.sandbox
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Sandbox subpackage for the Generic Agent Evaluation Harness.
relates_to:
- concept: mod:parrot.eval.sandbox.base
  rel: references
---

# `parrot.eval.sandbox`

Sandbox subpackage for the Generic Agent Evaluation Harness.

FEAT-217. Execution-environment abstractions:
- ``Sandbox`` / ``SandboxProvider`` ABCs (base.py)
- ``NoopSandbox`` / ``NoopSandboxProvider`` (base.py)
- ``StateBackend`` / ``DictStateBackend`` (state.py — TASK-1418)
- ``InMemoryStateSandbox`` / ``ToolkitBinder`` (state.py — TASK-1419)
- ``FakeAsyncDBConnection`` / ``FakeJiraClient`` (fakes.py — TASK-1419/1420)
