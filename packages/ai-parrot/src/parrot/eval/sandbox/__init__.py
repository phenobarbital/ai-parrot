"""Sandbox subpackage for the Generic Agent Evaluation Harness.

FEAT-217. Execution-environment abstractions:
- ``Sandbox`` / ``SandboxProvider`` ABCs (base.py)
- ``NoopSandbox`` / ``NoopSandboxProvider`` (base.py)
- ``StateBackend`` / ``DictStateBackend`` (state.py — TASK-1418)
- ``InMemoryStateSandbox`` / ``ToolkitBinder`` (state.py — TASK-1419)
- ``FakeAsyncDBConnection`` / ``FakeJiraClient`` (fakes.py — TASK-1419/1420)
"""
from parrot.eval.sandbox.base import (
    AgentFactory,
    ExecResult,
    NoopSandbox,
    NoopSandboxProvider,
    Sandbox,
    SandboxProvider,
    SandboxSpec,
)

__all__ = [
    "SandboxSpec",
    "ExecResult",
    "Sandbox",
    "SandboxProvider",
    "AgentFactory",
    "NoopSandbox",
    "NoopSandboxProvider",
]
