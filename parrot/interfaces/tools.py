"""
ToolInterface - Interface for tool management functionality.

This interface provides methods for initializing, managing, and using tools
in bot implementations.
"""
from typing import List, Union, Dict, Any, Callable
from collections.abc import Callable as CallableABC
from ..tools import AbstractTool
from ..tools.manager import ToolDefinition
from ..tools.math import MathTool
from ..clients.base import AbstractClient
from ..clients.factory import SUPPORTED_CLIENTS


class ToolInterface:
    """
    Interface for tool management in bot implementations.
    
    This interface provides methods for:
    - Initializing and registering tools
    - Syncing tools with LLM clients
    - Determining when to use tools
    - Validating tools
    - Configuring LLM clients
    """

    def _initialize_tools(self, tools: List[Union[str, AbstractTool, ToolDefinition]]) -> None:
        """Initialize tools in the ToolManager."""
        for tool in tools:
            try:
                if isinstance(tool, str):
                    # Handle tool by name (e.g., 'math', 'calculator')
                    if self.tool_manager.load_tool(tool):
                        self.logger.info(
                            f"Successfully loaded tool: {tool}"
                        )
                        continue
                    else:
                        # try to select a list of built-in tools
                        builtin_tools = {
                            "math": MathTool
                        }
                        if tool.lower() in builtin_tools:
                            tool_instance = builtin_tools[tool.lower()]()
                            self.tool_manager.register_tool(tool_instance)
                            self.logger.info(f"Registered built-in tool: {tool}")
                            continue
                elif isinstance(tool, (AbstractTool, ToolDefinition)):
                    # Handle tool objects directly
                    self.tool_manager.register_tool(tool)
                else:
                    self.logger.warning(
                        f"Unknown tool type: {type(tool)}"
                    )
            except Exception as e:
                self.logger.error(
                    f"Error initializing tool {tool}: {e}"
                )

    def _sync_tools_to_llm(self, llm: AbstractClient = None) -> None:
        """Assign Bot's ToolManager as a reference to LLM's ToolManager.

        Instead of copying tools via sync(), we share the same ToolManager instance
        so that changes to tools are immediately reflected in both places.
        This allows users to swap the tool_manager at runtime for session-specific toolsets.
        """
        try:
            if not llm:
                llm = self._llm
            # Assign by reference instead of syncing
            llm.tool_manager = self.tool_manager
            llm.enable_tools = True
        except Exception as e:
            self.logger.error(
                f"Error assigning tool_manager to LLM: {e}"
            )

    def _use_tools(
        self,
        question: str,
    ) -> bool:
        """Determine if tools should be enabled for this conversation."""
        if not self.enable_tools:
            return False

        # Check if tools are enabled and available via LLM client
        if not self.enable_tools or not self.has_tools():
            return False

        # For agentic mode, always use tools if available
        if self.operation_mode == 'agentic':
            return True

        # For conversational mode, never use tools
        if self.operation_mode == 'conversational':
            return False

        # For adaptive mode, use heuristics
        if self.operation_mode == 'adaptive':
            if self.has_tools():
                return True
            # Simple heuristics based on question content
            conversational_indicators = [
                'how are you', 'what\'s up', 'thanks', 'thank you',
                'hello', 'hi', 'hey', 'bye', 'goodbye',
                'good morning', 'good evening', 'good night',
            ]
            question_lower = question.lower()
            return not any(keyword in question_lower for keyword in conversational_indicators)

        return False

    def get_tools_summary(self) -> Dict[str, Any]:
        """Get a comprehensive summary of available tools and configuration."""
        tool_details = {}
        for tool_name in self.get_available_tools():
            tool = self.get_tool(tool_name)
            if tool:
                tool_details[tool_name] = {
                    'description': getattr(tool, 'description', 'No description'),
                    'category': getattr(tool, 'category', 'general'),
                    'type': type(tool).__name__
                }

        return {
            'tools_enabled': self.enable_tools,
            'operation_mode': self.operation_mode,
            'tools_count': self.get_tools_count(),
            'available_tools': self.get_available_tools(),
            'tool_details': tool_details,
            'categories': self.list_tool_categories(),
            'has_tools': self.has_tools(),
            'is_agent_mode': self.is_agent_mode(),
            'is_conversational_mode': self.is_conversational_mode(),
            'effective_mode': self.get_operation_mode(),
            'tool_threshold': self.tool_threshold
        }

    def validate_tools(self) -> Dict[str, Any]:
        """Validate all registered tools."""
        validation_results = {
            'valid_tools': [],
            'invalid_tools': [],
            'total_count': self.get_tools_count(),
            'validation_errors': []
        }

        for tool_name in self.get_available_tools():
            try:
                tool = self.get_tool(tool_name)
                if tool and hasattr(tool, 'validate'):
                    if tool.validate():
                        validation_results['valid_tools'].append(tool_name)
                    else:
                        validation_results['invalid_tools'].append(tool_name)
                else:
                    # Assume valid if no validation method
                    validation_results['valid_tools'].append(tool_name)
            except Exception as e:
                validation_results['invalid_tools'].append(tool_name)
                validation_results['validation_errors'].append(f"{tool_name}: {str(e)}")

        return validation_results

    def register_tool(
        self,
        tool: Union[ToolDefinition, AbstractTool] = None,
        name: str = None,
        description: str = None,
        input_schema: Dict[str, Any] = None,
        function: Callable = None,
    ) -> None:
        """Register a tool in the shared ToolManager.

        Since Bot and LLM share the same ToolManager reference (assigned during configure),
        we only need to register once. The tool will be immediately available to both.
        """
        self.tool_manager.register_tool(
            tool=tool,
            name=name,
            description=description,
            input_schema=input_schema,
            function=function
        )

    def configure_llm(
        self,
        llm: Union[str, Callable] = None,
        **kwargs
    ) -> AbstractClient:
        """
        Configuration of LLM at runtime (during conversation/ask methods)
        """
        config = self._resolve_llm_config(llm, **kwargs)
        llm = self._create_llm_client(config, self.conversation_memory)
        try:
            if self.tool_manager and hasattr(llm, 'tool_manager'):
                self._sync_tools_to_llm(llm)
        except Exception as e:
            self.logger.error(
                f"Error registering tools: {e}"
            )
        return llm

    def llm_chain(
        self,
        llm: str = "vertexai",
        model: str = None,
        **kwargs
    ) -> AbstractClient:
        """llm_chain.

        Args:
            llm (str): The language model to use.

        Returns:
            AbstractClient: The language model to use.

        """
        try:
            if cls := SUPPORTED_CLIENTS.get(llm.lower(), None):
                return cls(model=model, **kwargs)
            raise ValueError(
                f"Unsupported LLM: {llm}"
            )
        except Exception:
            raise
