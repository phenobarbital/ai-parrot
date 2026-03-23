from typing import Optional, Dict, Any
from parrot.bots.flow.node import Node
from parrot.tools.manager import ToolManager


class EndNode(Node):
    """Virtual exit-point node for AgentsFlow DAGs.

    An EndNode marks the successful completion of a DAG flow. 
    It completes instantly, returning the final result passed to it.
    It uses duck-typing to satisfy FlowNode's agent slot.

    Inherits pre/post action hooks and logger from Node.

    Args:
        name: Identifier for this end node (default: '__end__').
        metadata: Optional metadata dict.
    """

    is_configured: bool = True

    def __init__(
        self,
        name: str = "__end__",
        *,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        self._name = name
        self.metadata = metadata or {}
        self.tool_manager = ToolManager()
        self._init_node(name)

    @property
    def name(self) -> str:
        """Node identifier."""
        return self._name

    async def ask(self, question: str = "", **ctx: Any) -> str:
        """No-op execution with pre/post action hooks."""
        await self.run_pre_actions(prompt=question, **ctx)
        result = question
        await self.run_post_actions(result=result, **ctx)
        return result

    async def configure(self) -> None:
        """No-op — nothing to configure."""
