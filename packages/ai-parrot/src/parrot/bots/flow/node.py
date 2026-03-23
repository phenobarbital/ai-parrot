"""Abstract Node base class for all flow nodes."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Callable, List, Union, Awaitable
import asyncio
from navconfig.logging import logging


# Type alias for action callbacks
ActionCallback = Callable[..., Union[None, Awaitable[None]]]


class Node(ABC):
    """Abstract base for FlowNode, StartNode, and DecisionFlowNode.

    Provides lifecycle hooks (pre/post actions) and a configured logger
    scoped to ``parrot.node.{name}``.

    Subclasses must implement the ``name`` property and call
    ``_init_node()`` during their own initialisation (either in
    ``__init__`` or ``__post_init__`` for dataclasses).

    Pre-actions receive ``(node_name, prompt, **ctx)`` and run
    *before* the node executes.  Post-actions receive
    ``(node_name, result, **ctx)`` and run *after* execution.

    Example::

        class MyNode(Node):
            def __init__(self, name: str):
                self._name = name
                self._init_node(name)

            @property
            def name(self) -> str:
                return self._name

        node = MyNode("classifier")
        node.add_pre_action(lambda n, p, **kw: print(f"{n}: about to run"))
        node.add_post_action(lambda n, r, **kw: print(f"{n}: got {r}"))
    """

    logger: logging.Logger
    _pre_actions: List[ActionCallback]
    _post_actions: List[ActionCallback]

    def _init_node(self, name: str) -> None:
        """Initialize node infrastructure.

        Must be called by subclasses during construction.
        """
        self.logger = logging.getLogger(f"parrot.node.{name}")
        self._pre_actions = []
        self._post_actions = []

    # --- name contract ---

    @property
    @abstractmethod
    def name(self) -> str:
        """Node identifier."""

    # --- action registration ---

    def add_pre_action(self, action: ActionCallback) -> None:
        """Register a callback to run before node execution."""
        self._pre_actions.append(action)

    def add_post_action(self, action: ActionCallback) -> None:
        """Register a callback to run after node execution."""
        self._post_actions.append(action)

    # --- action runners ---

    async def run_pre_actions(
        self,
        prompt: str = "",
        **ctx: Any,
    ) -> None:
        """Execute all registered pre-actions in order.

        Args:
            prompt: The input prompt/question about to be processed.
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
            result: The output produced by the node.
            **ctx: Additional context forwarded to each callback.
        """
        for action in self._post_actions:
            res = action(self.name, result, **ctx)
            if asyncio.iscoroutine(res):
                await res
