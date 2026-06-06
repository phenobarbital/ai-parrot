"""Sandbox ABCs and NoopSandbox for the Generic Agent Evaluation Harness.

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
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from parrot.bots.abstract import AbstractBot

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


class SandboxSpec(BaseModel):
    """Configuration for a sandbox instance.

    Attributes:
        kind: Sandbox implementation selector.
        image: Docker image tag (only used by ``DockerSandbox``).
        setup: Shell commands to run after the sandbox starts.
        seed_state: Initial world state to load into state-based sandboxes.
        git_truncate_after: Git ref to truncate history to (SWE-bench use).
    """

    kind: Literal["docker", "in_memory_state", "mock_api", "noop"] = "noop"
    image: str | None = None
    setup: list[str] = Field(default_factory=list)
    seed_state: dict[str, Any] | None = None
    git_truncate_after: str | None = None


class ExecResult(BaseModel):
    """Result of a command executed inside a sandbox.

    Attributes:
        exit_code: Process exit code (0 = success).
        stdout: Standard output captured from the command.
        stderr: Standard error captured from the command.
    """

    exit_code: int
    stdout: str = ""
    stderr: str = ""


# ---------------------------------------------------------------------------
# Sandbox ABC
# ---------------------------------------------------------------------------


class Sandbox(ABC):
    """Abstract execution environment for agent evaluation.

    Sandboxes are used as async context managers so the runner can bracket
    the lifecycle cleanly:

        async with sandbox:
            await sandbox.reset(seed_state)
            bot = await agent_factory(sandbox)
            trajectory = await rollout.run(bot, task, sandbox)
            state = await sandbox.snapshot()

    Subclasses provide concrete isolation strategies (in-memory, Docker, …).
    """

    @abstractmethod
    async def __aenter__(self) -> "Sandbox":
        """Enter the sandbox context.

        Returns:
            The sandbox instance itself.
        """
        ...

    @abstractmethod
    async def __aexit__(self, *exc: Any) -> None:
        """Exit the sandbox context and release resources.

        Args:
            exc: Exception information (if any).
        """
        ...

    @abstractmethod
    async def reset(self, seed_state: dict[str, Any] | None) -> None:
        """Reset the sandbox to a known state.

        Args:
            seed_state: Initial state to load.  ``None`` empties the store.
        """
        ...

    @abstractmethod
    async def health_check(self) -> bool:
        """Check whether the sandbox is operational.

        Returns:
            ``True`` if the sandbox is healthy.
        """
        ...

    @abstractmethod
    async def snapshot(self) -> dict[str, Any]:
        """Capture a deterministic snapshot of the current world state.

        Returns:
            A deep copy of the current state, sorted for stable diffs.
        """
        ...

    async def exec(self, cmd: list[str]) -> ExecResult:
        """Execute a shell command inside the sandbox.

        Concrete implementations (e.g. ``DockerSandbox``) override this.
        State-based sandboxes raise ``NotImplementedError``.

        Args:
            cmd: Command and arguments to execute.

        Returns:
            ``ExecResult`` with exit code, stdout, stderr.

        Raises:
            NotImplementedError: If this sandbox type does not support
                command execution.
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not support exec(); "
            "use a DockerSandbox for code-execution tasks."
        )


# ---------------------------------------------------------------------------
# SandboxProvider ABC
# ---------------------------------------------------------------------------


class SandboxProvider(ABC):
    """Factory that acquires and releases ``Sandbox`` instances.

    Implementations may pool sandboxes (Docker) or provision fresh per
    attempt (``InMemoryStateSandboxProvider``).
    """

    @abstractmethod
    async def acquire(self, spec: SandboxSpec) -> Sandbox:
        """Acquire a sandbox configured according to *spec*.

        Args:
            spec: Sandbox configuration.

        Returns:
            A ready-to-use ``Sandbox`` instance.
        """
        ...

    @abstractmethod
    async def release(self, sandbox: Sandbox) -> None:
        """Return a sandbox to the pool (or GC it for fresh-per-attempt).

        Args:
            sandbox: The sandbox to release.
        """
        ...


# ---------------------------------------------------------------------------
# AgentFactory type alias
# ---------------------------------------------------------------------------

#: Callable that produces a fresh ``AbstractBot`` bound to a given sandbox.
#: Signature: ``async def agent_factory(sandbox: Sandbox) -> AbstractBot``
AgentFactory = Callable[["Sandbox"], Awaitable["AbstractBot"]]


# ---------------------------------------------------------------------------
# NoopSandbox (conversational / RAG path)
# ---------------------------------------------------------------------------


class NoopSandbox(Sandbox):
    """No-operation sandbox for agents that do not mutate external state.

    Suitable for conversational and RAG agents.  All lifecycle methods are
    trivial: ``reset`` and ``snapshot`` do nothing / return empty dicts;
    ``health_check`` always returns ``True``; ``exec`` raises
    ``NotImplementedError``.
    """

    async def __aenter__(self) -> "NoopSandbox":
        """Enter the noop sandbox context.

        Returns:
            Self.
        """
        return self

    async def __aexit__(self, *exc: Any) -> None:
        """Exit the noop sandbox context (no-op).

        Args:
            exc: Exception information (ignored).
        """
        pass

    async def reset(self, seed_state: dict[str, Any] | None) -> None:
        """No-op reset (NoopSandbox has no state).

        Args:
            seed_state: Ignored.
        """
        pass

    async def health_check(self) -> bool:
        """Always healthy.

        Returns:
            ``True``.
        """
        return True

    async def snapshot(self) -> dict[str, Any]:
        """Return an empty state dict.

        Returns:
            Empty ``dict``.
        """
        return {}


class NoopSandboxProvider(SandboxProvider):
    """Provider that always returns a fresh ``NoopSandbox``.

    Suitable for conversational / RAG evaluation where no real sandbox
    isolation is required.
    """

    async def acquire(self, spec: SandboxSpec) -> NoopSandbox:
        """Return a new ``NoopSandbox`` (ignoring *spec*).

        Args:
            spec: Ignored.

        Returns:
            A fresh ``NoopSandbox``.
        """
        return NoopSandbox()

    async def release(self, sandbox: Sandbox) -> None:
        """GC the sandbox (no pool).

        Args:
            sandbox: Ignored.
        """
        pass
