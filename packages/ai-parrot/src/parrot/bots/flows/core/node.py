"""Flow Primitives — Node Hierarchy.

Provides the shared Node ABC and concrete node types used by both
``AgentCrew`` and ``AgentsFlow`` orchestration engines.

**Architecture (FEAT-163 / B-lite shape):**

Nodes are frozen Pydantic ``BaseModel`` subclasses
(``model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)``).
This means:

- Field reassignment (``node.node_id = x``) raises ``ValidationError``.
- *Nested* object mutation is allowed: ``node.fsm.start()`` works because
  it mutates the FSM's internal state without reassigning the ``fsm`` field.
- ``_pre_actions`` / ``_post_actions`` are ``PrivateAttr`` lists, also
  mutable (appending does not reassign the field — frozen-safe).

**Concurrent-run safety:**

The scheduler (``AgentsFlow.run_flow``) materializes a *fresh* set of Node
instances per invocation via ``_materialize_nodes()``.  Each concurrent
``run_flow()`` call gets its own independent FSM state.

**Execute signature (changed in FEAT-163):**

``AgentNode.execute(ctx, deps, **kwargs) -> Any``

The old signature ``(prompt, *, timeout, **ctx)`` is gone.  Prompt
derivation now lives in the overridable ``_build_prompt(ctx, deps)`` helper.

Key difference from ``parrot.bots.flow.node``:
  ``Node`` carries a ``node_id`` field (unique per graph instance)
  separate from the ``name`` property (agent identity).

Classes:
    Node — abstract base with ``node_id``, logger, and action hooks.
    AgentNode — wraps an ``AgentLike`` agent + ``AgentTaskMachine`` FSM.
    StartNode — virtual entry-point node (name defaults to ``'__start__'``).
    EndNode — virtual exit-point node (name defaults to ``'__end__'``).

See also:
    ``sdd/specs/agentsflow-refactor-spec3.spec.md`` §2-3 for the full
    architectural rationale (B-lite approach).
    ``sdd/proposals/agentsflow-refactor-spec3.brainstorm.md`` for
    option comparison.
"""
from __future__ import annotations

import asyncio
from abc import abstractmethod
from typing import TYPE_CHECKING, Any, Dict, Optional, Set

from navconfig.logging import logging
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr

from .fsm import AgentTaskMachine
from .types import ActionCallback, AgentLike, DependencyResults

if TYPE_CHECKING:
    from .context import FlowContext


# ---------------------------------------------------------------------------
# Node ABC
# ---------------------------------------------------------------------------


class Node(BaseModel):
    """Abstract base for all flow/crew nodes (frozen Pydantic).

    Extends the pattern in ``parrot.bots.flow.node.Node`` by adding a
    ``node_id`` field so each graph instance can be uniquely addressed
    independently from the underlying agent's name.

    Frozen-model contract:
    - ``node.field = value`` raises ``ValidationError`` (Pydantic v2 frozen).
    - ``node._pre_actions.append(cb)`` is allowed (mutating list, not
      reassigning the private attr).
    - Nested object mutation (e.g., ``node.fsm.start()``) is allowed because
      the ``fsm`` field itself is not being reassigned.

    Subclasses must implement the abstract ``name`` property.

    Pre-actions receive ``(node_name, prompt, **ctx)`` and run before the
    node executes.  Post-actions receive ``(node_name, result, **ctx)`` and
    run after execution.

    Example::

        class MyNode(Node):
            my_field: str

            @property
            def name(self) -> str:
                return self.my_field
    """

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    node_id: str

    # Private mutable state (survives frozen=True because PrivateAttr is
    # initialised via __init__ and not subject to the frozen constraint).
    _pre_actions: list = PrivateAttr(default_factory=list)
    _post_actions: list = PrivateAttr(default_factory=list)
    _logger: Any = PrivateAttr(default=None)

    def model_post_init(self, __context: Any) -> None:
        """Initialise private attrs that require post-construction logic."""
        self._logger = logging.getLogger(f"parrot.node.{self.name}")

    # ── Abstract interface ────────────────────────────────────────────────

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable agent/node name."""

    @property
    def logger(self) -> logging.Logger:
        """Per-node logger (lazy-initialised in model_post_init)."""
        return self._logger

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


class AgentNode(Node):
    """A graph node that wraps an ``AgentLike`` agent and an FSM.

    ``node_id`` is unique per graph instance (e.g., ``"researcher-1"``).
    ``name`` delegates to the wrapped agent (e.g., ``"researcher"``).

    The embedded ``AgentTaskMachine`` tracks this node's execution
    lifecycle (idle -> ready -> running -> completed/failed).

    **FEAT-163 execute signature change:**

    The old signature ``execute(prompt, *, timeout, **ctx)`` has been
    replaced with ``execute(ctx, deps, **kwargs)`` where:

    - ``ctx``: ``FlowContext`` -- the running flow's execution state.
    - ``deps``: ``DependencyResults`` -- mapping of dep node_id -> result.
    - ``**kwargs``: forwarded to ``agent.ask()``.

    Prompt derivation now lives in the overridable ``_build_prompt(ctx, deps)``
    method.  The default reads ``ctx.get_input_for_agent(self.agent.name,
    self.dependencies)`` and returns it as a string.

    **FSM lifecycle is managed by the scheduler (AgentsFlow.run_flow), NOT
    inside execute().**  Do not call ``self.fsm.start()`` / ``.succeed()`` /
    ``.fail()`` here.

    Args:
        agent: The agent object conforming to ``AgentLike``.
        node_id: Unique identifier for this node instance in the DAG.
        dependencies: Set of ``node_id`` values that must complete first.
        successors: Set of ``node_id`` values triggered after this node.
        fsm: Optional pre-constructed FSM (auto-created in model_post_init
             when ``None``).
    """

    agent: AgentLike
    node_id: str
    dependencies: Set[str] = Field(default_factory=set)
    successors: Set[str] = Field(default_factory=set)
    fsm: Optional[AgentTaskMachine] = None

    def model_post_init(self, __context: Any) -> None:
        """Auto-create the FSM if not provided; initialise logger."""
        super().model_post_init(__context)
        if self.fsm is None:
            # object.__setattr__ is the frozen-Pydantic escape hatch for
            # setting a field inside model_post_init.  Use sparingly.
            object.__setattr__(
                self, "fsm", AgentTaskMachine(agent_name=self.agent.name)
            )

    @property
    def name(self) -> str:
        """Agent identity (delegates to ``agent.name``)."""
        return self.agent.name

    def _build_prompt(
        self,
        ctx: "FlowContext",
        deps: DependencyResults,
    ) -> str:
        """Derive the prompt from flow context and dependency results.

        Default implementation calls ``ctx.get_input_for_agent()``.
        Subclasses (e.g., ``CrewAgentNode``) may override to format the
        returned dict into a string suitable for their agent.

        Args:
            ctx: The current flow execution context.
            deps: Dependency results (mapping of dep node_id -> result).

        Returns:
            Prompt string to pass to the agent.
        """
        input_data = ctx.get_input_for_agent(self.agent.name, self.dependencies)
        # Stringify the dict if it is not already a plain string.
        if isinstance(input_data, str):
            return input_data
        # Build a minimal text representation for dict-shaped input.
        task = input_data.get("task", "")
        dependency_results = input_data.get("dependencies", {})
        if not dependency_results:
            return task
        parts = [f"Task: {task}\n", "\nContext from previous agents:\n"]
        for dep_id, dep_result in dependency_results.items():
            parts.extend((f"\n--- From {dep_id} ---", str(dep_result), ""))
        return "\n".join(parts)

    async def execute(
        self,
        ctx: "FlowContext",
        deps: DependencyResults,
        **kwargs: Any,
    ) -> Any:
        """Execute the agent with pre/post hooks.

        Derives the prompt via ``_build_prompt(ctx, deps)``, calls
        ``run_pre_actions``, invokes the underlying agent via
        ``agent.ask(question=prompt, _trusted_source=True, **kwargs)``,
        calls ``run_post_actions``, and returns a result dict.

        **The FSM lifecycle (start/succeed/fail) is managed externally
        by the scheduler -- do NOT call it here.**

        Args:
            ctx: The current flow execution context.
            deps: Mapping of completed dependency node_id -> result string.
            **kwargs: Additional keyword arguments forwarded to the agent.

        Returns:
            Dict with keys ``'response'``, ``'output'``,
            ``'execution_time'``, and ``'prompt'``.
        """
        prompt = self._build_prompt(ctx, deps)
        await self.run_pre_actions(prompt=prompt, **kwargs)
        start_time = asyncio.get_running_loop().time()
        response = await self.agent.ask(
            question=prompt, _trusted_source=True, **kwargs
        )
        end_time = asyncio.get_running_loop().time()
        output = (
            response.content
            if hasattr(response, "content")
            else str(
                response.output if hasattr(response, "output") else response
            )
        )
        await self.run_post_actions(result=response, **kwargs)
        return {
            "response": response,
            "output": output,
            "execution_time": end_time - start_time,
            "prompt": prompt,
        }


# ---------------------------------------------------------------------------
# StartNode
# ---------------------------------------------------------------------------


class StartNode(Node):
    """Virtual entry-point node for flow/crew DAGs.

    Carries no agent -- completes instantly and forwards the initial
    prompt to all downstream successors.

    Duck-typing attributes (``is_configured``, ``configure``, ``ask``)
    let engine code treat it uniformly with agent nodes.

    The ``node_id`` doubles as the node's display name (accessed via the
    abstract ``name`` property).  Constructors that accept a positional
    ``name`` string set ``node_id`` to that value.

    Args:
        node_id: Node identifier / display name (default: ``'__start__'``).
        metadata: Optional arbitrary metadata dict.
    """

    node_id: str = Field(default="__start__")
    is_configured: bool = True
    metadata: Dict[str, Any] = Field(default_factory=dict)
    dependencies: Set[str] = Field(default_factory=set)
    """Node IDs that must complete before this node can run."""
    successors: Set[str] = Field(default_factory=set)
    """Node IDs to dispatch after this node completes."""

    # Allow StartNode(name="entry") for backward compat with the old
    # __init__(self, name="__start__", ...) signature.  The value is stored
    # inside node_id via model_post_init.
    _init_name: Optional[str] = PrivateAttr(default=None)

    def __init__(self, **data: Any) -> None:
        # Accept positional-ish "name" kwarg and re-route it to node_id.
        if "name" in data and "node_id" not in data:
            data["node_id"] = data.pop("name")
        elif "name" in data:
            data.pop("name")  # node_id takes precedence
        super().__init__(**data)

    @property
    def name(self) -> str:
        """Node identifier (same as ``node_id`` for start/end nodes)."""
        return self.node_id

    async def ask(self, question: str = "", **ctx: Any) -> str:
        """No-op execution -- passes the prompt through unchanged.

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

    async def execute(self, ctx: Any, deps: Any, **kwargs: Any) -> Any:
        """Execute start node -- forwards initial task from context.

        Returns the initial task as a plain string so CEL predicates on
        outgoing edges can compare ``result == "..."`` directly.

        Args:
            ctx: FlowContext or any context object.
            deps: Dependency results (empty for start nodes).
            **kwargs: Additional keyword arguments.

        Returns:
            The initial task string from ctx, or empty string.
        """
        task = getattr(ctx, "initial_task", "") or ""
        return task

    async def configure(self) -> None:
        """No-op -- nothing to configure."""


# ---------------------------------------------------------------------------
# EndNode
# ---------------------------------------------------------------------------


class EndNode(Node):
    """Virtual exit-point node for flow/crew DAGs.

    Marks the successful completion of a DAG flow.  Completes instantly,
    returning whatever result is passed to it.

    The ``node_id`` doubles as the node's display name (accessed via the
    abstract ``name`` property).  Constructors that accept a positional
    ``name`` string set ``node_id`` to that value.

    Args:
        node_id: Node identifier / display name (default: ``'__end__'``).
        metadata: Optional arbitrary metadata dict.
    """

    node_id: str = Field(default="__end__")
    is_configured: bool = True
    metadata: Dict[str, Any] = Field(default_factory=dict)
    dependencies: Set[str] = Field(default_factory=set)
    """Node IDs that must complete before this node can run."""
    successors: Set[str] = Field(default_factory=set)
    """Node IDs to dispatch after this node completes (typically empty)."""

    def __init__(self, **data: Any) -> None:
        # Accept positional-ish "name" kwarg and re-route it to node_id.
        if "name" in data and "node_id" not in data:
            data["node_id"] = data.pop("name")
        elif "name" in data:
            data.pop("name")  # node_id takes precedence
        super().__init__(**data)

    @property
    def name(self) -> str:
        """Node identifier (same as ``node_id`` for start/end nodes)."""
        return self.node_id

    async def ask(self, question: str = "", **ctx: Any) -> str:
        """No-op execution -- passes the prompt through unchanged.

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

    async def execute(self, ctx: Any, deps: Any, **kwargs: Any) -> Any:
        """Execute end node -- collects final output from dependencies.

        Args:
            ctx: FlowContext or any context object.
            deps: Dependency results from upstream nodes.
            **kwargs: Additional keyword arguments.

        Returns:
            The last dependency result or empty string.
        """
        dep_values = list(deps.values())
        if dep_values:
            last = dep_values[-1]
            # Unwrap dict results from AgentNode.execute()
            if isinstance(last, dict) and "output" in last:
                return last["output"]
            return last
        return ""

    async def configure(self) -> None:
        """No-op -- nothing to configure."""
