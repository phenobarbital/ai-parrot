"""Flow Primitives — Node Hierarchy.

Provides the shared Node ABC and concrete node types used by both
``AgentCrew`` and ``AgentsFlow`` orchestration engines.

Key difference from ``parrot.bots.flow.node``:
  ``Node`` now carries a ``node_id`` field (unique per graph instance)
  separate from the ``name`` property (agent identity).

Classes:
    Node — abstract base with ``node_id``, logger, and action hooks.
    AgentNode — wraps an ``AgentLike`` agent + ``AgentTaskMachine`` FSM.
    StartNode — virtual entry-point node (name defaults to ``'__start__'``).
    EndNode — virtual exit-point node (name defaults to ``'__end__'``).
"""
from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional, Dict, Set

from navconfig.logging import logging

from .fsm import AgentTaskMachine
from .types import ActionCallback, AgentLike


# ---------------------------------------------------------------------------
# Node ABC
# ---------------------------------------------------------------------------


class Node(ABC):
    """Abstract base for all flow/crew nodes.

    Extends the pattern in ``parrot.bots.flow.node.Node`` by adding a
    ``node_id`` field so each graph instance can be uniquely addressed
    independently from the underlying agent's name.

    Subclasses must:
    - Implement the abstract ``name`` property.
    - Call ``_init_node(node_id, name)`` during construction.

    Pre-actions receive ``(node_name, prompt, **ctx)`` and run before
    the node executes.  Post-actions receive ``(node_name, result, **ctx)``
    and run after execution.

    Example::

        class MyNode(Node):
            def __init__(self, node_id: str, name: str):
                self._name = name
                self._init_node(node_id, name)

            @property
            def name(self) -> str:
                return self._name
    """

    node_id: str
    logger: logging.Logger
    _pre_actions: list
    _post_actions: list

    def _init_node(self, node_id: str, name: str) -> None:
        """Initialise node infrastructure.

        Args:
            node_id: Unique identifier for this node instance in the graph.
            name: Human-readable name used for logging and identification.
        """
        self.node_id = node_id
        self.logger = logging.getLogger(f"parrot.node.{name}")
        self._pre_actions = []
        self._post_actions = []

    # ── Abstract interface ────────────────────────────────────────────────

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable agent/node name."""

    # ── Action registration ───────────────────────────────────────────────

    def add_pre_action(self, action: ActionCallback) -> None:
        """Register a callback to run before node execution.

        Args:
            action: Callable that accepts ``(node_name, prompt, **ctx)``.
        """
        self._pre_actions.append(action)

    def add_post_action(self, action: ActionCallback) -> None:
        """Register a callback to run after node execution.

        Args:
            action: Callable that accepts ``(node_name, result, **ctx)``.
        """
        self._post_actions.append(action)

    # ── Action runners ────────────────────────────────────────────────────

    async def run_pre_actions(
        self,
        prompt: str = "",
        **ctx: Any,
    ) -> None:
        """Execute all registered pre-actions in order.

        Args:
            prompt: Input prompt about to be processed.
            **ctx: Additional context forwarded to each callback.
        """
        for action in self._pre_actions:
            result = action(self.name, prompt, **ctx)
            if asyncio.iscoroutine(result):
                await result

    async def run_post_actions(
        self,
        result: Any = None,
        **ctx: Any,
    ) -> None:
        """Execute all registered post-actions in order.

        Args:
            result: Output produced by the node.
            **ctx: Additional context forwarded to each callback.
        """
        for action in self._post_actions:
            res = action(self.name, result, **ctx)
            if asyncio.iscoroutine(res):
                await res


# ---------------------------------------------------------------------------
# AgentNode
# ---------------------------------------------------------------------------


@dataclass
class AgentNode(Node):
    """A graph node that wraps an ``AgentLike`` agent and an FSM.

    ``node_id`` is unique per graph instance (e.g., ``"researcher-1"``).
    ``name`` delegates to the wrapped agent (e.g., ``"researcher"``).

    The embedded ``AgentTaskMachine`` tracks this node's execution
    lifecycle (idle → ready → running → completed/failed).

    Args:
        agent: The agent object conforming to ``AgentLike``.
        node_id: Unique identifier for this node instance in the DAG.
        dependencies: Set of ``node_id`` values that must complete first.
        successors: Set of ``node_id`` values triggered after this node.
        fsm: Optional pre-constructed FSM (auto-created if ``None``).
    """

    agent: AgentLike
    node_id: str
    dependencies: Set[str] = field(default_factory=set)
    successors: Set[str] = field(default_factory=set)
    fsm: Optional[AgentTaskMachine] = field(default=None)

    def __post_init__(self) -> None:
        """Finish initialisation after dataclass __init__."""
        if self.fsm is None:
            self.fsm = AgentTaskMachine(agent_name=self.agent.name)
        self._init_node(self.node_id, self.agent.name)

    @property
    def name(self) -> str:
        """Agent identity (delegates to ``agent.name``)."""
        return self.agent.name

    async def execute(
        self,
        prompt: str,
        *,
        timeout: Optional[float] = None,
        **ctx: Any,
    ) -> Dict[str, Any]:
        """Execute the agent with pre/post hooks, timeout, and time tracking.

        Calls ``run_pre_actions`` before execution, invokes the agent via
        ``agent.ask()``, then calls ``run_post_actions``.  Optionally wraps
        the agent call in ``asyncio.wait_for`` when *timeout* is provided.

        On timeout or any other exception, transitions the FSM to ``failed``
        (if an FSM is attached) before propagating the error.

        Args:
            prompt: Input prompt for the agent.
            timeout: Optional timeout in seconds for the agent call.
            **ctx: Additional context forwarded to hooks and the agent.

        Returns:
            Dict with keys ``'response'``, ``'output'``,
            ``'execution_time'``, and ``'prompt'``.

        Raises:
            TimeoutError: If the agent call exceeds *timeout*.
        """
        await self.run_pre_actions(prompt=prompt, **ctx)
        start_time = asyncio.get_running_loop().time()
        try:
            if timeout:
                response = await asyncio.wait_for(
                    self.agent.ask(prompt=prompt, **ctx),
                    timeout=timeout,
                )
            else:
                response = await self.agent.ask(prompt=prompt, **ctx)
            end_time = asyncio.get_running_loop().time()
            output = (
                response.content
                if hasattr(response, "content")
                else str(
                    response.output
                    if hasattr(response, "output")
                    else response
                )
            )
            await self.run_post_actions(result=response, **ctx)
            return {
                "response": response,
                "output": output,
                "execution_time": end_time - start_time,
                "prompt": prompt,
            }
        except asyncio.TimeoutError:
            if self.fsm:
                self.fsm.fail()
            raise TimeoutError(
                f"Agent {self.name} timed out after {timeout}s"
            ) from None
        except Exception:
            if self.fsm:
                self.fsm.fail()
            raise


# ---------------------------------------------------------------------------
# StartNode
# ---------------------------------------------------------------------------


class StartNode(Node):
    """Virtual entry-point node for flow/crew DAGs.

    Carries no agent — completes instantly and forwards the initial
    prompt to all downstream successors.

    Duck-typing attributes (``is_configured``, ``configure``, ``ask``)
    let engine code treat it uniformly with agent nodes.

    Args:
        name: Identifier (default: ``'__start__'``).
        metadata: Optional arbitrary metadata dict.
    """

    is_configured: bool = True

    def __init__(
        self,
        name: str = "__start__",
        *,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        self._name = name
        self.metadata = metadata or {}
        self._init_node(name, name)

    @property
    def name(self) -> str:
        """Node identifier."""
        return self._name

    async def ask(self, question: str = "", **ctx: Any) -> str:
        """No-op execution — passes the prompt through unchanged.

        Args:
            question: The prompt/question to forward.
            **ctx: Additional context.

        Returns:
            The unmodified ``question`` string.
        """
        await self.run_pre_actions(prompt=question, **ctx)
        result = question
        await self.run_post_actions(result=result, **ctx)
        return result

    async def configure(self) -> None:
        """No-op — nothing to configure."""


# ---------------------------------------------------------------------------
# EndNode
# ---------------------------------------------------------------------------


class EndNode(Node):
    """Virtual exit-point node for flow/crew DAGs.

    Marks the successful completion of a DAG flow.  Completes instantly,
    returning whatever result is passed to it.

    Args:
        name: Identifier (default: ``'__end__'``).
        metadata: Optional arbitrary metadata dict.
    """

    is_configured: bool = True

    def __init__(
        self,
        name: str = "__end__",
        *,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        self._name = name
        self.metadata = metadata or {}
        self._init_node(name, name)

    @property
    def name(self) -> str:
        """Node identifier."""
        return self._name

    async def ask(self, question: str = "", **ctx: Any) -> str:
        """No-op execution — passes the prompt through unchanged.

        Args:
            question: The prompt/question to forward.
            **ctx: Additional context.

        Returns:
            The unmodified ``question`` string.
        """
        await self.run_pre_actions(prompt=question, **ctx)
        result = question
        await self.run_post_actions(result=result, **ctx)
        return result

    async def configure(self) -> None:
        """No-op — nothing to configure."""
