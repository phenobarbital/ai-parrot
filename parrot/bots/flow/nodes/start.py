from typing import Optional, Dict, Any
from parrot.bots.flow.node import Node
from parrot.tools.manager import ToolManager


class StartNode(Node):
    """Virtual entry-point node for AgentsFlow DAGs.

    A StartNode carries no agent — it completes instantly and forwards
    the initial task prompt to all downstream targets.  It uses
    duck-typing to satisfy FlowNode's agent slot (name, ask,
    tool_manager, is_configured, configure).

    Inherits pre/post action hooks and logger from Node.

    Args:
        name: Identifier for this start node (default: '__start__').
        metadata: Optional metadata dict (e.g. trigger info, webhook URL).
    """

    is_configured: bool = True

    def __init__(
        self,
        name: str = "__start__",
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
