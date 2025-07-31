from collections.abc import Generator
from json import tool
from typing import Dict, List, Any, Union, Optional
from abc import ABC, abstractmethod
import logging
from enum import Enum
from .math import MathTool
from .abstract import AbstractTool


class ToolFormat(Enum):
    """Enum for different tool format requirements by LLM providers."""
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    GOOGLE = "google"
    GROQ = "groq"
    VERTEX = "vertex"
    GENERIC = "generic"


class ToolSchemaAdapter:
    """
    Adapter class to convert tool schemas between different LLM provider formats.
    """

    @staticmethod
    def clean_schema_for_provider(
        schema: Dict[str, Any],
        provider: ToolFormat
    ) -> Dict[str, Any]:
        """
        Clean and adapt tool schema for specific LLM provider requirements.

        Args:
            schema: Original tool schema
            provider: Target LLM provider format

        Returns:
            Cleaned schema compatible with the provider
        """
        cleaned_schema = schema.copy()

        # Remove internal metadata
        cleaned_schema.pop('_tool_instance', None)

        if provider in [ToolFormat.GOOGLE, ToolFormat.VERTEX]:
            # Google/Vertex AI specific cleaning
            return ToolSchemaAdapter._clean_for_google(cleaned_schema)
        elif provider == ToolFormat.GROQ:
            # Groq specific cleaning
            return ToolSchemaAdapter._clean_for_groq(cleaned_schema)
        elif provider in [ToolFormat.OPENAI, ToolFormat.ANTHROPIC]:
            # OpenAI/Anthropic specific cleaning
            return ToolSchemaAdapter._clean_for_openai(cleaned_schema)
        else:
            # Generic cleaning
            return ToolSchemaAdapter._clean_generic(cleaned_schema)

    @staticmethod
    def _clean_for_google(schema: Dict[str, Any]) -> Dict[str, Any]:
        """Clean schema for Google/Vertex AI compatibility."""
        cleaned = schema.copy()

        # Remove additionalProperties recursively
        def remove_additional_properties(obj):
            if isinstance(obj, dict):
                # Remove additionalProperties
                obj.pop('additionalProperties', None)
                # Remove other unsupported properties
                obj.pop('title', None)  # Google doesn't use title in parameters

                # Recursively clean nested objects
                for _, value in obj.items():
                    remove_additional_properties(value)
            elif isinstance(obj, list):
                for item in obj:
                    remove_additional_properties(item)

        if 'parameters' in cleaned:
            remove_additional_properties(cleaned['parameters'])

        return cleaned

    @staticmethod
    def _clean_for_groq(schema: Dict[str, Any]) -> Dict[str, Any]:
        """Clean schema for Groq compatibility."""
        cleaned = schema.copy()

        def remove_unsupported_constraints(obj):
            if isinstance(obj, dict):
                # Remove validation constraints that Groq doesn't support
                unsupported = [
                    "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum",
                    "minLength", "maxLength", "pattern", "format",
                    "minItems", "maxItems", "uniqueItems",
                    "minProperties", "maxProperties"
                ]

                for constraint in unsupported:
                    obj.pop(constraint, None)

                # Set additionalProperties to false for objects
                if obj.get("type") == "object":
                    obj["additionalProperties"] = False

                # Recursively clean nested objects
                for key, value in obj.items():
                    remove_unsupported_constraints(value)
            elif isinstance(obj, list):
                for item in obj:
                    remove_unsupported_constraints(item)

        if 'parameters' in cleaned:
            remove_unsupported_constraints(cleaned['parameters'])

        return cleaned

    @staticmethod
    def _clean_for_openai(schema: Dict[str, Any]) -> Dict[str, Any]:
        """Clean schema for OpenAI/Anthropic compatibility."""
        cleaned = schema.copy()

        # These providers generally support full JSON Schema
        # Just ensure additionalProperties is properly set
        def ensure_additional_properties(obj):
            if isinstance(obj, dict):
                if obj.get("type") == "object" and "additionalProperties" not in obj:
                    obj["additionalProperties"] = False

                for key, value in obj.items():
                    ensure_additional_properties(value)
            elif isinstance(obj, list):
                for item in obj:
                    ensure_additional_properties(item)

        if 'parameters' in cleaned:
            ensure_additional_properties(cleaned['parameters'])

        return cleaned

    @staticmethod
    def _clean_generic(schema: Dict[str, Any]) -> Dict[str, Any]:
        """Generic schema cleaning."""
        cleaned = schema.copy()

        # Remove internal metadata and ensure basic structure
        cleaned.pop('_tool_instance', None)

        # Ensure required fields exist
        if 'parameters' not in cleaned:
            cleaned['parameters'] = {
                "type": "object",
                "properties": {},
                "required": []
            }

        return cleaned


class ToolManager:
    """
    Unified tool manager for handling tools across AbstractBot and AbstractClient.
    """

    def __init__(
        self,
        logger: Optional[logging.Logger] = None
    ):
        """
        Initialize tool manager.

        Args:
            logger: Logger instance
        """
        self.logger = logger or logging.getLogger(self.__class__.__name__)
        self._tools: Dict[str, Any] = {}  # Unified storage as dictionary

    def default_tools(self, tools: list = None) -> List[AbstractTool]:
        if tools:
            self.register_tools(tools)
        # define the list of Default Tools:
        default_tools = [
            MathTool(),
        ]
        self.register_tools(default_tools)

    def register_tool(self, tool: Any, name: Optional[str] = None) -> None:
        """
        Register a tool in the unified format.

        Args:
            tool: Tool instance (AbstractTool, ToolDefinition, or dict)
            name: Optional custom name for the tool
        """
        try:
            # Determine tool name
            if name:
                tool_name = name
            elif hasattr(tool, 'name') and tool.name:
                tool_name = tool.name
            elif hasattr(tool, '__class__'):
                tool_name = tool.__class__.__name__
            elif isinstance(tool, dict) and 'name' in tool:
                tool_name = tool['name']
            else:
                tool_name = f"tool_{len(self._tools)}"

            # Store the tool
            self._tools[tool_name] = tool
            self.logger.debug(
                f"Registered tool: {tool_name}"
            )

        except Exception as e:
            self.logger.error(f"Error registering tool: {e}")

    def register_tools(self, tools: Union[List[Any], Dict[str, Any]]) -> None:
        """
        Register multiple tools from list or dictionary.

        Args:
            tools: List of tools or dictionary of tools
        """
        if tools is None:
            return
        if isinstance(tools, dict):
            for name, tool in tools.items():
                self.register_tool(tool, name)
        elif isinstance(tools, list):
            for tool in tools:
                if isinstance(tool, str):
                    # Use load_tool to get tool instance by name
                    self.load_tool(tool)
                else:
                    # Register tool instance directly
                    if hasattr(tool, 'name'):
                        self.register_tool(tool, tool.name)
                    else:
                        self.register_tool(tool)
        else:
            self.logger.error(
                f"Invalid tools format: {type(tools)}"
            )

    def load_tool(self, tool_name: str, **kwargs) -> Optional[Any]:
        """
        Load a tool by name.

        Args:
            tool_name: Name of the tool to load

        Returns:
            Tool instance or None if not found
        """
        if tool_name in self._tools:
            return self._tools[tool_name]

        tool_file = tool_name.lower().replace('tool', '')
        try:
            module = __import__(f"parrot.tools.{tool_file}", fromlist=[tool_name])
            cls = getattr(module, tool_name)
            self._tools[tool_name] = cls(**kwargs)
        except (ImportError, AttributeError) as e:
            self.logger.error(
                f"Error loading tool {tool_name}: {e}"
            )

    def get_tool_schemas(
        self,
        provider_format: ToolFormat = ToolFormat.GENERIC
    ) -> List[Dict[str, Any]]:
        """
        Get tool schemas formatted for specific LLM provider.

        Args:
            provider_format: Target provider format

        Returns:
            List of tool schemas compatible with the provider
        """
        if not self._tools:
            return []

        client_tools = []

        for tool_name, tool in self._tools.items():
            try:
                # Get tool schema
                schema = self._extract_tool_schema(tool, tool_name)

                if schema:
                    # Add tool instance reference for execution
                    schema['_tool_instance'] = tool

                    # Clean schema for provider compatibility
                    cleaned_schema = ToolSchemaAdapter.clean_schema_for_provider(
                        schema, provider_format
                    )

                    # Re-add tool instance after cleaning
                    cleaned_schema['_tool_instance'] = tool

                    client_tools.append(cleaned_schema)
                    self.logger.debug(f"Prepared tool schema for: {tool_name}")

            except Exception as e:
                self.logger.error(f"Error preparing tool {tool_name}: {e}")

        return client_tools

    def _extract_tool_schema(self, tool: Any, tool_name: str) -> Optional[Dict[str, Any]]:
        """
        Extract schema from various tool formats.

        Args:
            tool: Tool instance
            tool_name: Tool name

        Returns:
            Tool schema dictionary or None
        """
        try:
            # AbstractTool with get_tool_schema method
            if hasattr(tool, 'get_tool_schema'):
                return tool.get_tool_schema()

            # ToolDefinition with input_schema
            elif hasattr(tool, 'input_schema') and hasattr(tool, 'description'):
                return {
                    "name": tool_name,
                    "description": tool.description,
                    "parameters": tool.input_schema
                }

            # Dictionary format
            elif isinstance(tool, dict):
                if 'name' in tool and 'parameters' in tool:
                    return tool
                else:
                    # Try to construct from available fields
                    return {
                        "name": tool.get('name', tool_name),
                        "description": tool.get('description', f"Tool: {tool_name}"),
                        "parameters": tool.get('parameters', tool.get('input_schema', {}))
                    }

            # Legacy format with name, description, input_schema attributes
            elif hasattr(tool, 'name') and hasattr(tool, 'description'):
                schema = getattr(tool, 'input_schema', {})
                return {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": schema
                }

            else:
                self.logger.warning(f"Unknown tool format for: {tool_name}")
                return None

        except Exception as e:
            self.logger.error(
                f"Error extracting schema for {tool_name}: {e}"
            )
            return None

    def get_tool(self, tool_name: str) -> Optional[Any]:
        """
        Get tool instance by name.

        Args:
            tool_name: Name of the tool

        Returns:
            Tool instance or None
        """
        return self._tools.get(tool_name)

    def list_tools(self) -> List[str]:
        """Get list of registered tool names."""
        return list(self._tools.keys())

    def get_tools(self) -> Dict[str, Any]:
        """Get all registered tools."""
        return self._tools.values()

    def all_tools(self) -> Generator[Any, Any, Any]:
        """
        Get all registered tools with their schemas as a generator.

        Returns:
            List of tool schemas
        """
        for tool in self._tools.values():
            yield tool

    def clear_tools(self) -> None:
        """Clear all registered tools."""
        self._tools.clear()
        self.logger.debug("Cleared all tools")

    def remove_tool(self, tool_name: str) -> None:
        """
        Remove a tool by name.

        Args:
            tool_name: Name of the tool to remove
        """
        if tool_name in self._tools:
            del self._tools[tool_name]
            self.logger.debug(f"Removed tool: {tool_name}")
        else:
            self.logger.warning(f"Tool not found: {tool_name}")

    def __repr__(self) -> str:
        """String representation of the ToolManager."""
        return f"ToolManager(tools={list(self._tools.keys())})"

    def __len__(self) -> int:
        """Get number of registered tools."""
        return len(self._tools)

    def build_tools_description(
        self,
        format_style: str = "compact",
        include_parameters: bool = True,
        include_examples: bool = False,
        max_tools: Optional[int] = None
    ) -> str:
        """
        Build formatted tool descriptions for system prompts.

        Args:
            format_style: Style of formatting ("detailed", "compact", "list", "markdown")
            include_parameters: Whether to include parameter details
            include_examples: Whether to include usage examples
            max_tools: Maximum number of tools to include (None for all)

        Returns:
            Formatted string describing all available tools
        """
        if not self._tools:
            return "No tools available."

        # Get tools to describe (limit if specified)
        tools_to_describe = list(self._tools.items())
        if max_tools:
            tools_to_describe = tools_to_describe[:max_tools]

        if format_style == "detailed":
            return self._build_detailed_description(
                tools_to_describe,
                include_parameters,
                include_examples
            )
        elif format_style == "compact":
            return self._build_compact_description(tools_to_describe, include_parameters)
        elif format_style == "list":
            return self._build_list_description(tools_to_describe)
        elif format_style == "markdown":
            return self._build_markdown_description(
                tools_to_describe,
                include_parameters,
                include_examples
            )
        else:
            return self._build_detailed_description(
                tools_to_describe,
                include_parameters,
                include_examples
            )

    def _build_detailed_description(
        self,
        tools: List[tuple],
        include_parameters: bool,
        include_examples: bool
    ) -> str:
        """Build detailed tool descriptions."""
        descriptions = ["=== AVAILABLE TOOLS ===\n"]

        for i, (tool_name, tool) in enumerate(tools, 1):
            try:
                schema = self._extract_tool_schema(tool, tool_name)
                if not schema:
                    continue

                # Tool header
                descriptions.append(f"{i}. {schema['name']}: {schema['description']}")

                # Parameters section
                if include_parameters and 'parameters' in schema:
                    params = schema['parameters'].get('properties', {})
                    required = schema['parameters'].get('required', [])

                    if params:
                        descriptions.append("   Parameters:")
                        for param_name, param_info in params.items():
                            param_type = param_info.get('type', 'unknown')
                            param_desc = param_info.get('description', 'No description')
                            required_marker = " (required)" if param_name in required else " (optional)"
                            descriptions.append(f"     - {param_name} ({param_type}){required_marker}: {param_desc}")

                # Usage example
                if include_examples:
                    descriptions.append(f"   Usage: Call {schema['name']} when you need to {schema['description'].lower()}")

                descriptions.append("")  # Empty line between tools

            except Exception as e:
                self.logger.error(f"Error building description for {tool_name}: {e}")
                descriptions.append(f"{i}. {tool_name}: Error getting tool information")
                descriptions.append("")

        descriptions.append(
            "Use these tools when appropriate to answer the question effectively."
        )
        return "\n".join(descriptions)

    def _build_compact_description(self, tools: List[tuple], include_parameters: bool) -> str:
        """Build compact tool descriptions."""
        descriptions = ["Available tools: "]
        tool_summaries = []

        for tool_name, tool in tools:
            try:
                schema = self._extract_tool_schema(tool, tool_name)
                if not schema:
                    continue

                summary = f"{schema['name']}"

                if include_parameters and 'parameters' in schema:
                    params = schema['parameters'].get('properties', {})
                    if params:
                        param_names = list(params.keys())[:3]  # First 3 params
                        param_str = ", ".join(param_names)
                        if len(params) > 3:
                            param_str += "..."
                        summary += f"({param_str})"

                summary += f" - {schema['description']}"
                tool_summaries.append(summary)

            except Exception as e:
                self.logger.error(f"Error building compact description for {tool_name}: {e}")
                tool_summaries.append(f"{tool_name} - Tool information unavailable")

        descriptions.extend(tool_summaries)
        return "; ".join(descriptions) + "."

    def _build_list_description(self, tools: List[tuple]) -> str:
        """Build simple list of tool names and descriptions."""
        descriptions = ["Available tools:\n"]

        for tool_name, tool in tools:
            try:
                schema = self._extract_tool_schema(tool, tool_name)
                if schema:
                    descriptions.append(f"• {schema['name']}: {schema['description']}")
                else:
                    descriptions.append(f"• {tool_name}: Description unavailable")
            except Exception as e:
                self.logger.error(f"Error building list description for {tool_name}: {e}")
                descriptions.append(f"• {tool_name}: Error getting information")

        return "\n".join(descriptions)

    def _build_markdown_description(
        self,
        tools: List[tuple],
        include_parameters: bool,
        include_examples: bool
    ) -> str:
        """Build markdown-formatted tool descriptions."""
        descriptions = ["## Available Tools\n"]

        for tool_name, tool in tools:
            try:
                schema = self._extract_tool_schema(tool, tool_name)
                if not schema:
                    continue

                # Tool header
                descriptions.append(f"### {schema['name']}")
                descriptions.append(f"**Description:** {schema['description']}\n")

                # Parameters section
                if include_parameters and 'parameters' in schema:
                    params = schema['parameters'].get('properties', {})
                    required = schema['parameters'].get('required', [])

                    if params:
                        descriptions.append("**Parameters:**")
                        for param_name, param_info in params.items():
                            param_type = param_info.get('type', 'unknown')
                            param_desc = param_info.get('description', 'No description')
                            required_marker = "**required**" if param_name in required else "*optional*"
                            descriptions.append(f"- `{param_name}` ({param_type}) - {required_marker}: {param_desc}")
                        descriptions.append("")

                # Usage example
                if include_examples:
                    descriptions.append(f"**Usage:** Call `{schema['name']}` when you need to {schema['description'].lower()}\n")

            except Exception as e:
                self.logger.error(f"Error building markdown description for {tool_name}: {e}")
                descriptions.append(f"### {tool_name}\n**Error:** Could not retrieve tool information\n")

        return "\n".join(descriptions)

    def get_tools_summary(self) -> Dict[str, Any]:
        """
        Get a summary of all registered tools.

        Returns:
            Dictionary with tool count and basic information
        """
        if not self._tools:
            return {"count": 0, "tools": []}

        tools_info = []
        for tool_name, tool in self._tools.items():
            try:
                schema = self._extract_tool_schema(tool, tool_name)
                tool_info = {
                    "name": tool_name,
                    "description": schema.get(
                        'description', 'No description'
                    ) if schema else 'Schema unavailable',
                    "parameters_count": len(
                        schema.get('parameters', {}).get('properties', {})
                    ) if schema else 0
                }
                tools_info.append(tool_info)
            except Exception as e:
                self.logger.error(f"Error getting summary for {tool_name}: {e}")
                tools_info.append({
                    "name": tool_name,
                    "description": "Error getting information",
                    "parameters_count": 0
                })

        return {
            "count": len(self._tools),
            "tools": tools_info
        }
