"""
AbstractToolkit for creating collections of tools from class methods.
"""
import inspect
from typing import Dict, List, Type, Optional, Any, get_type_hints
from abc import ABC
from pydantic import BaseModel, create_model, Field
from navconfig.logging import logging
from datamodel.parsers.json import json_decoder, json_encoder  # noqa  pylint: disable=E0611
from ..conf import BASE_STATIC_URL
from .abstract import AbstractTool, AbstractToolArgsSchema


class ToolkitTool(AbstractTool):
    """
    A specialized AbstractTool that wraps a method from a toolkit.
    """

    def __init__(
        self,
        name: str,
        bound_method: callable,
        description: str = None,
        args_schema: Type[BaseModel] = None,
        **kwargs
    ):
        """
        Initialize a toolkit tool.

        Args:
            name: Tool name
            bound_method: The bound coroutine method to wrap
            description: Tool description
            args_schema: Pydantic model for arguments
            **kwargs: Additional arguments
        """
        self.bound_method = bound_method

        # Set up the tool
        super().__init__(
            name=name,
            description=description or bound_method.__doc__ or f"Tool: {name}",
            **kwargs
        )

        # Set the args schema
        if args_schema:
            self.args_schema = args_schema
        else:
            # Try to generate schema from method signature
            self.args_schema = self._generate_args_schema_from_method()

    def _generate_args_schema_from_method(self) -> Type[BaseModel]:
        """
        Generate a Pydantic schema from the method's type hints.
        """
        try:
            # Get method signature
            sig = inspect.signature(self.bound_method)
            type_hints = get_type_hints(self.bound_method)

            # Build fields for Pydantic model
            fields = {}

            for param_name, param in sig.parameters.items():
                # Skip 'self' parameter (shouldn't be there for bound methods, but just in case)
                if param_name == 'self':
                    continue

                # Get type hint
                param_type = type_hints.get(param_name, Any)

                # Handle Optional types and defaults
                if param.default == param.empty:
                    # Required parameter
                    default_value = ...
                else:
                    # Has default value
                    default_value = param.default

                # Create field with description based on parameter name
                description = f"Parameter: {param_name}"
                fields[param_name] = (param_type, Field(default=default_value, description=description))

            # Create dynamic Pydantic model
            if fields:
                return create_model(
                    f"{self.name}Args",
                    **fields
                )
            else:
                # No parameters, return base schema
                return AbstractToolArgsSchema

        except Exception as e:
            self.logger.warning(f"Could not generate schema for {self.name}: {e}")
            return AbstractToolArgsSchema

    async def _execute(self, **kwargs) -> Any:
        """
        Execute the toolkit method.

        Args:
            **kwargs: Method arguments

        Returns:
            Method result
        """
        return await self.bound_method(**kwargs)


class AbstractToolkit(ABC):
    """
    Abstract base class for creating toolkits - collections of related tools.

    A toolkit automatically converts all public async methods into tools.
    Each method becomes a tool with:
    - Name: method name
    - Description: method docstring
    - Schema: automatically generated from type hints

    Usage:
        class MyToolkit(AbstractToolkit):
            async def search_web(self, query: str) -> str:
                '''Search the web for information.'''
                # Implementation here
                return result

            async def calculate(self, expression: str) -> float:
                '''Calculate a mathematical expression.'''
                # Implementation here
                return result

        # Get all tools
        toolkit = MyToolkit()
        tools = toolkit.get_tools()
    """

    # Configuration
    input_class: Optional[Type[BaseModel]] = None  # Default input schema (optional)
    return_direct: bool = False  # Whether tools return results directly
    json_encoder: Type[Any] = json_encoder
    json_decoder: Type[Any] = json_decoder
    base_url: str = BASE_STATIC_URL

    def __init__(self, **kwargs):
        """
        Initialize the toolkit.

        Args:
            **kwargs: Configuration options
        """
        # Configuration
        self.return_direct = kwargs.get('return_direct', self.return_direct)
        self.base_url = kwargs.get('base_url', self.base_url)

        # Tool cache
        self._tool_cache: Dict[str, ToolkitTool] = {}
        self._tools_generated = False

    async def start(self) -> None:
        """
        Optional startup logic for the toolkit.
        Override in subclasses if needed.
        """
        pass

    async def stop(self) -> None:
        """
        Optional shutdown logic for the toolkit.
        Override in subclasses if needed.
        """
        pass

    async def cleanup(self) -> None:
        """
        Optional cleanup logic for the toolkit.
        Override in subclasses if needed.
        """
        pass

    def get_tools(self) -> List[AbstractTool]:
        """
        Get all tools from this toolkit.

        Inspects all public async methods and converts them to tools.

        Returns:
            List of AbstractTool instances
        """
        if self._tools_generated and self._tool_cache:
            return list(self._tool_cache.values())

        tools = []

        # Inspect all methods - get bound methods
        for name in dir(self):
            # Skip private methods and non-methods
            if name.startswith('_'):
                continue

            # Skip toolkit management methods
            if name in ('get_tools', 'get_tool', 'list_tool_names', 'start', 'stop', 'cleanup'):
                continue

            # Get the attribute
            attr = getattr(self, name)

            # Check if it's a coroutine function
            if not inspect.iscoroutinefunction(attr):
                continue

            # Create tool from bound method
            tool = self._create_tool_from_method(name, attr)
            tools.append(tool)
            self._tool_cache[name] = tool

        self._tools_generated = True
        return tools

    def get_tool(self, name: str) -> Optional[AbstractTool]:
        """
        Get a specific tool by name.

        Args:
            name: Tool name

        Returns:
            AbstractTool instance or None if not found
        """
        if not self._tools_generated:
            self.get_tools()  # Ensure tools are generated

        return self._tool_cache.get(name)

    def list_tool_names(self) -> List[str]:
        """
        Get a list of all tool names in this toolkit.

        Returns:
            List of tool names
        """
        if not self._tools_generated:
            self.get_tools()

        return list(self._tool_cache.keys())

    def _create_tool_from_method(self, name: str, bound_method: callable) -> ToolkitTool:
        """
        Create a ToolkitTool from a bound method.

        Args:
            name: Method name
            bound_method: The bound coroutine method

        Returns:
            ToolkitTool instance
        """
        # Get description from docstring
        description = bound_method.__doc__ or f"Tool: {name}"
        description = description.strip()

        # Determine args schema - prioritize method-specific schema
        args_schema = getattr(bound_method, '_args_schema', None)

        # If no custom schema is defined, always generate from method signature
        # This ensures each method only gets the parameters it actually needs
        if not args_schema:
            args_schema = None  # Let ToolkitTool generate it from the method signature

        # Create the tool
        tool = ToolkitTool(
            name=name,
            bound_method=bound_method,
            description=description,
            args_schema=args_schema,
            return_direct=self.return_direct
        )

        return tool

    def get_toolkit_info(self) -> Dict[str, Any]:
        """
        Get information about this toolkit.

        Returns:
            Dictionary with toolkit information
        """
        tools = self.get_tools()

        return {
            "toolkit_name": self.__class__.__name__,
            "tool_count": len(tools),
            "tool_names": [tool.name for tool in tools],
            "tool_descriptions": {tool.name: tool.description for tool in tools},
            "return_direct": self.return_direct,
            "base_url": self.base_url
        }
