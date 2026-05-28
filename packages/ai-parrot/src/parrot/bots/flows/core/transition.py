"""Flow Primitives — FlowTransition.

Extracted from ``parrot.bots.flow.fsm.FlowTransition`` into the shared
core module so both ``AgentCrew`` and ``AgentsFlow`` can use the same
transition semantics.

Key changes from the original:
  - ``metadata`` field type changed from ``AgentExecutionInfo`` to
    ``NodeExecutionInfo`` (from ``core.result``).
  - ``build_prompt()`` first argument is ``Any`` (not ``AgentContext``)
    to avoid importing the engine-specific context class.  The method
    still uses ``context.original_query`` via duck-typing.

All activation and prompt-building logic is preserved exactly.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional, Set, Union

from .fsm import TransitionCondition
from .result import NodeExecutionInfo
from .types import DependencyResults, PromptBuilder


@dataclass
class FlowTransition:
    """Conditional edge between two nodes in a flow/crew DAG.

    Defines what triggers the transition (``condition``), where it goes
    (``targets``), how to prepare the downstream prompt
    (``instruction`` / ``prompt_builder``), and optional metadata about
    the source node's execution.

    Fields:
        source: The ``node_id`` (or agent name) of the originating node.
        targets: Set of ``node_id`` values to activate when this
            transition fires.
        condition: Activation condition (default: ``ON_SUCCESS``).
        instruction: Optional static prompt string for target nodes.
        prompt_builder: Optional async-capable callable
            ``(context, dependencies) -> str`` for dynamic prompts.
        predicate: Required when ``condition == ON_CONDITION``; called
            with the source node's result.  May be async.
        priority: Higher priority transitions are evaluated first.
        metadata: Optional ``NodeExecutionInfo`` attached to this
            transition (replaces ``AgentExecutionInfo`` from the
            original ``parrot.bots.flow.fsm.FlowTransition``).

    Example::

        t = FlowTransition(
            source="researcher",
            targets={"writer"},
            condition=TransitionCondition.ON_SUCCESS,
        )
        if await t.should_activate(result="findings"):
            prompt = await t.build_prompt(ctx, deps)
    """

    source: str
    """Source node_id / agent name."""

    targets: Set[str]
    """Target node_ids to activate when this transition fires."""

    condition: TransitionCondition = TransitionCondition.ON_SUCCESS
    """Activation condition (default: fire on successful source completion)."""

    instruction: Optional[str] = None
    """Static prompt string forwarded to target nodes (lower priority than prompt_builder)."""

    prompt_builder: Optional[PromptBuilder] = None
    """Dynamic prompt builder callable (higher priority than instruction)."""

    predicate: Optional[Callable[[Any], Union[bool, Awaitable[bool]]]] = None
    """Custom condition callable used when ``condition == ON_CONDITION``."""

    priority: int = 0
    """Evaluation priority — higher values are tested first."""

    metadata: Optional[NodeExecutionInfo] = None
    """Optional execution metadata attached to this transition."""

    # ── Activation logic ─────────────────────────────────────────────────

    async def should_activate(
        self,
        result: Any,
        error: Optional[Exception] = None,
    ) -> bool:
        """Determine whether this transition should fire.

        Args:
            result: The result produced by the source node.
            error: Exception raised by the source node (``None`` on success).

        Returns:
            ``True`` if the transition should fire.
        """
        if self.condition == TransitionCondition.ALWAYS:
            return True

        if self.condition == TransitionCondition.ON_SUCCESS:
            return error is None

        if self.condition == TransitionCondition.ON_ERROR:
            return error is not None

        if self.condition == TransitionCondition.ON_CONDITION and self.predicate:
            pred_result = self.predicate(result)
            if asyncio.iscoroutine(pred_result):
                return await pred_result
            return bool(pred_result)

        if self.condition == TransitionCondition.ON_TIMEOUT:
            # Fires when the source node timed out (error is a TimeoutError).
            return isinstance(error, (asyncio.TimeoutError, TimeoutError))

        return False

    # ── Prompt building ───────────────────────────────────────────────────

    async def build_prompt(
        self,
        context: Any,
        dependencies: DependencyResults,
    ) -> str:
        """Build the prompt string for target nodes.

        Priority order:
        1. ``prompt_builder`` callable (sync or async).
        2. ``instruction`` static string.
        3. Default: ``"Task: {context.original_query}"`` with dependency context.

        Args:
            context: Execution context object with an ``original_query``
                attribute (duck-typed — not bound to ``AgentContext`` to
                avoid engine coupling).
            dependencies: Mapping of dependency node_id → result string.

        Returns:
            The constructed prompt string.
        """
        if self.prompt_builder:
            prompt = self.prompt_builder(context, dependencies)
            return await prompt if asyncio.iscoroutine(prompt) else prompt

        if self.instruction:
            return self.instruction

        # Default fallback: original query + dependency summaries
        parts = [f"Task: {context.original_query}"]

        if dependencies:
            parts.append("\nContext from previous agents:")
            for node_name, result in dependencies.items():
                parts.extend((f"\n--- {node_name} ---", str(result)))

        return "\n".join(parts)
