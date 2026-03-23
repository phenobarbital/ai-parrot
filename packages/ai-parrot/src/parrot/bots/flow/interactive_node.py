"""Interactive decision node for CLI-based Flows.

This node prompts the user in the console using a rich, interactive
menu (via questionary) to make decisions without requiring an LLM.

Requires the optional ``questionary`` package (pip install questionary).
"""

from typing import List, Optional, Any, Dict

from parrot.bots.flow.node import Node
from parrot.bots.flow.decision_node import DecisionResult, DecisionMode
from parrot.tools.manager import ToolManager


class InteractiveDecisionNode(Node):
    """A Flow node that asks the user a multiple-choice question in the CLI.

    Instead of using an LLM to decide routing, this node presents a list
    of options directly to the user in the terminal and returns the selection.
    
    Args:
        name: Name of the node.
        question: The prompt text shown to the user.
        options: A list of string options to choose from.
        metadata: Optional metadata.
    """

    is_configured: bool = True

    def __init__(
        self,
        name: str,
        question: str,
        options: List[str],
        *,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        self._name = name
        self.question = question
        self.options = options
        self.metadata = metadata or {}
        self.tool_manager = ToolManager()
        self._init_node(name)

    @property
    def name(self) -> str:
        """Node identifier."""
        return self._name

    async def ask(self, question: str = "", **ctx: Any) -> DecisionResult:
        """Prompt the user in the terminal using questionary.
        
        Ignores the incoming `question` string, using the initialized `self.question`
        instead, since this node acts as a static menu prompt.
        """
        await self.run_pre_actions(prompt=self.question, **ctx)
        
        # questionary.select blocks the terminal to capture arrow keys.
        # We run it in the default event loop executor to avoid blocking the async loop.
        import asyncio
        loop = asyncio.get_running_loop()
        
        def _prompt_user() -> str:
            try:
                import questionary
            except ImportError as exc:
                raise ImportError(
                    "questionary is required for InteractiveDecisionNode. "
                    "Install it with: pip install questionary"
                ) from exc
            # We add a generic default 'Cancel' option if they Ctrl+C, but questionary handles it by returning None.
            return questionary.select(
                self.question,
                choices=self.options
            ).ask()
            
        selected_option = await loop.run_in_executor(None, _prompt_user)
        
        if not selected_option:
            # User aborted (Ctrl+C), default to "unknown" or first option depending on requirements.
            # We'll return an unknown state so the flow can handle or fail it.
            selected_option = "unknown"

        # Return a DecisionResult so it's fully compatible with downstream routing predicates
        result = DecisionResult(
            mode=DecisionMode.CIO,
            final_decision=selected_option.lower(),
            decision=selected_option.lower(),
            reasoning="User interactive selection via CLI",
            raw_response=selected_option
        )
        
        await self.run_post_actions(result=result, **ctx)
        return result

    async def configure(self) -> None:
        """No-op — nothing to configure."""
        pass
