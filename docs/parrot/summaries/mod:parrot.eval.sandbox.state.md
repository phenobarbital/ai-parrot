---
type: Wiki Summary
title: parrot.eval.sandbox.state
id: mod:parrot.eval.sandbox.state
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: State-based sandbox components for the Generic Agent Evaluation Harness.
relates_to:
- concept: class:parrot.eval.sandbox.state.DatabaseToolkitBinder
  rel: defines
- concept: class:parrot.eval.sandbox.state.DictStateBackend
  rel: defines
- concept: class:parrot.eval.sandbox.state.InMemoryStateSandbox
  rel: defines
- concept: class:parrot.eval.sandbox.state.InMemoryStateSandboxProvider
  rel: defines
- concept: class:parrot.eval.sandbox.state.JiraToolkitBinder
  rel: defines
- concept: class:parrot.eval.sandbox.state.StateBackend
  rel: defines
- concept: class:parrot.eval.sandbox.state.ToolkitBinder
  rel: defines
- concept: mod:parrot.eval.sandbox.fakes
  rel: references
---

# `parrot.eval.sandbox.state`

State-based sandbox components for the Generic Agent Evaluation Harness.

FEAT-217 — Module 4.

TASK-1418: ``StateBackend`` + ``DictStateBackend``
TASK-1419: ``ToolkitBinder``, ``InMemoryStateSandbox``,
           ``InMemoryStateSandboxProvider``, ``DatabaseToolkitBinder``
TASK-1420: ``JiraToolkitBinder`` (added later)

``DictStateBackend`` is the resettable, in-memory world state owned by the
sandbox.  It is keyed as ``{collection: {entity_id: {field: value}}}``
and produces deterministic snapshots (sorted collections and entity keys)
so diffs and baselines are stable.

## Classes

- **`StateBackend(ABC)`** — Abstract resettable world-state store.
- **`DictStateBackend(StateBackend)`** — In-memory ``{collection: {entity_id: {field: value}}}`` store.
- **`ToolkitBinder(ABC)`** — Abstract binder that wires a StateBackend into a concrete toolkit.
- **`InMemoryStateSandbox`** — State-based sandbox that owns a ``DictStateBackend``.
- **`InMemoryStateSandboxProvider`** — Provider that provisions a fresh ``InMemoryStateSandbox`` per attempt.
- **`DatabaseToolkitBinder(ToolkitBinder)`** — Binder for ``DatabaseToolkit`` (``PostgresToolkit``) subclasses.
- **`JiraToolkitBinder(ToolkitBinder)`** — Binder for ``JiraToolkit``.
