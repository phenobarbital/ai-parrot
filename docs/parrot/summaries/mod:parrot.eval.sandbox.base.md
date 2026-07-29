---
type: Wiki Summary
title: parrot.eval.sandbox.base
id: mod:parrot.eval.sandbox.base
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Sandbox ABCs and NoopSandbox for the Generic Agent Evaluation Harness.
relates_to:
- concept: class:parrot.eval.sandbox.base.ExecResult
  rel: defines
- concept: class:parrot.eval.sandbox.base.NoopSandbox
  rel: defines
- concept: class:parrot.eval.sandbox.base.NoopSandboxProvider
  rel: defines
- concept: class:parrot.eval.sandbox.base.Sandbox
  rel: defines
- concept: class:parrot.eval.sandbox.base.SandboxProvider
  rel: defines
- concept: class:parrot.eval.sandbox.base.SandboxSpec
  rel: defines
- concept: mod:parrot.bots.abstract
  rel: references
---

# `parrot.eval.sandbox.base`

Sandbox ABCs and NoopSandbox for the Generic Agent Evaluation Harness.

FEAT-217 — Module 3.  Defines the execution-environment contract used by
every rollout and the runner.

Key types
---------
``SandboxSpec``
    Pydantic configuration for a sandbox instance.
``Sandbox``
    Async context manager + lifecycle ABC.
``SandboxProvider``
    Factory ABC that acquires and releases ``Sandbox`` instances.
``AgentFactory``
    Type alias: ``Callable[[Sandbox], Awaitable[AbstractBot]]``.
``NoopSandbox`` / ``NoopSandboxProvider``
    Trivial implementation for conversational / RAG agents that do not
    interact with a stateful environment.
``ExecResult``
    Small model returned by ``Sandbox.exec()``.

## Classes

- **`SandboxSpec(BaseModel)`** — Configuration for a sandbox instance.
- **`ExecResult(BaseModel)`** — Result of a command executed inside a sandbox.
- **`Sandbox(ABC)`** — Abstract execution environment for agent evaluation.
- **`SandboxProvider(ABC)`** — Factory that acquires and releases ``Sandbox`` instances.
- **`NoopSandbox(Sandbox)`** — No-operation sandbox for agents that do not mutate external state.
- **`NoopSandboxProvider(SandboxProvider)`** — Provider that always returns a fresh ``NoopSandbox``.
