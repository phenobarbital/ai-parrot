from __future__ import annotations
from collections.abc import Generator
import asyncio
from typing import Dict, List, Any, Union, Optional, Callable
from dataclasses import dataclass
import logging
from enum import Enum

import pandas as pd
from .math import MathTool
from .abstract import AbstractTool, ToolResult


@dataclass
class ToolDefinition:
    """Data structure for tool definition."""
    """Defines a tool with its name, description, input schema, and function."""
    __slots__ = ('name', 'description', 'input_schema', 'function')
    name: str
    description: str
    input_schema: Dict[str, Any]
    function: Callable


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

        def ensure_openai_object(obj):
            if isinstance(obj, dict):
                if obj.get("type") == "object":
                    props = obj.get("properties", {}) or {}

                    # Ensure additionalProperties is set
                    if "additionalProperties" not in obj:
                        obj["additionalProperties"] = False

                    # 🔑 Ensure 'required' exists and includes ALL properties
                    prop_keys = list(props.keys())
                    if "required" not in obj:
                        obj["required"] = prop_keys
                    else:
                        required = obj.get("required") or []
                        missing = [k for k in prop_keys if k not in required]
                        obj["required"] = required + missing

                # Recurse into nested dicts/lists
                for _, value in obj.items():
                    ensure_openai_object(value)

            elif isinstance(obj, list):
                for item in obj:
                    ensure_openai_object(item)

        if 'parameters' in cleaned:
            ensure_openai_object(cleaned['parameters'])

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
        logger: Optional[logging.Logger] = None,
        debug: bool = False
    ):
        """
        Initialize tool manager.

        Args:
            logger: Logger instance
        """
        self._shared: Dict[str, Any] = {"dataframes": {}}  # name -> (df, meta)
        self._result_hooks: List[Callable[[str, Any, Dict[str, Any]], None]] = []
        self.logger = logger or logging.getLogger(self.__class__.__name__)
        self._debug: bool = debug
        self._tools: Dict[str, Union[ToolDefinition, AbstractTool]] = {}
        self._categories: Dict[str, List[str]] = {}
        # policy (tweak as required)
        self.auto_share_dataframes: bool = True
        self.auto_push_to_pandas: bool = True
        self.pandas_tool_name: str = "python_pandas"

    def default_tools(self, tools: list = None) -> List[AbstractTool]:
        if not tools:
            tools = [
                MathTool(),
            ]
        self.register_tools(tools)

    @property
    def tools(self) -> List[AbstractTool]:
        """Get list of registered tool instances."""
        return self._tools

    def sync(self, other_manager: 'ToolManager') -> None:
        """
        Sync tools from another ToolManager instance.

        Args:
            other_manager: Another ToolManager instance to sync from
        """
        if not isinstance(other_manager, ToolManager):
            self.logger.error("Can only sync from another ToolManager instance")
            return

        for tool_name, tool in other_manager._tools.items():
            if tool_name not in self._tools:
                self._tools[tool_name] = tool
                self.logger.debug(
                    f"Synchronized tool: {tool_name}"
                )
            else:
                self.logger.debug(
                    f"Tool already exists, skipping: {tool_name}"
                )

    def add_tool(self, tool: Union[ToolDefinition, AbstractTool], name: Optional[str] = None) -> None:
        """
        Add a tool to the manager.

        Args:
            tool: Tool instance (AbstractTool or ToolDefinition)
            name: Optional custom name for the tool
        """
        tool_name = name or getattr(tool, 'name', None) or tool.__class__.__name__
        if isinstance(tool, AbstractTool) or isinstance(tool, ToolDefinition):
            self._tools[tool_name] = tool
            self.logger.debug(
                f"Registered tool: {tool_name}"
            )
        else:
            self.logger.error(
                f"Unsupported tool type: {type(tool)}"
            )

    def register_tool(
        self,
        tool: Union[dict, ToolDefinition, AbstractTool] = None,
        name: str = None,
        description: str = None,
        input_schema: Dict[str, Any] = None,
        function: Callable = None,
    ) -> None:
        """
        Register a tool in the unified format.

        Args:
            tool: Tool instance (AbstractTool, ToolDefinition, or dict)
            name: Optional custom name for the tool
        """
        tool_name = tool.name if isinstance(tool, (ToolDefinition, AbstractTool)) else name
        if tool_name in self._tools:
            self.logger.warning(
                f"Tool '{tool_name}' is already registered."
            )
            return
        try:
            if isinstance(tool, (ToolDefinition, AbstractTool)):
                self._tools[tool_name] = tool
            elif isinstance(tool, dict):
                tool_name = tool.get('name')
                if tool_name in self._tools:
                    self.logger.warning(f"Tool '{tool_name}' is already registered.")
                    return
                self._tools[tool_name] = ToolDefinition(
                    name=tool_name,
                    description=tool.get('description', ''),
                    input_schema=tool.get('parameters', {}),
                    function=tool.get('_tool_instance')
                )
            elif name and description and input_schema and function:
                # Create a ToolDefinition from the provided parameters
                self._tools[tool_name] = ToolDefinition(
                    name=name,
                    description=description,
                    input_schema=input_schema,
                    function=function
                )
            else:
                # TODO: if provided a function and a name, create the input_schema based on instrospection
                if not (name and description and input_schema and function):
                    self.logger.error(
                        f"Tool '{tool_name}' must be a ToolDefinition, AbstractTool, or provide all parameters: "
                        "name, description, input_schema, function."
                    )
                raise ValueError(
                    "Tool must be a ToolDefinition, AbstractTool, or provide all parameters: "
                    "name, description, input_schema, function."
                )
            self.logger.debug(
                f"Registered tool: {tool_name}"
            )
        except Exception as e:
            self.logger.error(
                f"Error registering tool: {e}"
            )

    def register_tools(
        self,
        tools: List[Union[ToolDefinition, AbstractTool]]
    ) -> None:
        """
        Register multiple tools from list or dictionary.

        Args:
            tools: List of tools or dictionary of tools
        """
        if not tools:
            return
        for tool in tools:
            if isinstance(tool, str):
                # If tool is a string, load it by name
                self.load_tool(tool)
            elif isinstance(tool, AbstractTool):
                # Register AbstractTool instance directly
                self.register_tool(tool)
            elif isinstance(tool, ToolDefinition):
                # Register ToolDefinition instance directly
                self.register_tool(tool, tool.name)
            elif isinstance(tool, dict):
                # Register dictionary as a tool
                self.register_tool(tool)
            elif hasattr(tool, 'name'):
                self.register_tool(tool, tool.name)
            else:
                self.logger.error(
                    f"Unsupported tool type: {type(tool)}"
                )

    def load_tool(self, tool_name: str, **kwargs) -> bool:
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
            return True
        except (ImportError, AttributeError) as e:
            self.logger.error(
                f"Error loading tool {tool_name}: {e}"
            )
            return False

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

    def list_categories(self) -> List[str]:
        """List available tool categories."""
        return list(self._categories.keys())

    def get_tools_by_category(self, category: str) -> List[str]:
        """Get tools by category."""
        return self._categories.get(category, [])

    def list_tools(self) -> List[str]:
        """Get list of registered tool names."""
        return list(self._tools.keys())

    def get_tools(self) -> Dict[str, Any]:
        """Get all registered tools."""
        return self._tools.values()

    def get_all_tools(self) -> List[Union[ToolDefinition, AbstractTool]]:
        """Get all registered tool instances."""
        return list(self._tools.values())

    def all_tools(self) -> Generator[Any, Any, Any]:
        """
        Get all registered tools with their schemas as a generator.

        Returns:
            List of tool schemas
        """
        for tool in self._tools.values():
            yield tool

    def unregister_tool(self, tool_name: str) -> bool:
        """Unregister a tool by name."""
        if tool_name in self._tools:
            del self._tools[tool_name]
            return True
        return False

    def clear_tools(self) -> None:
        """Clear all registered tools."""
        self._tools.clear()
        self._categories.clear()
        self.logger.debug("Cleared all tools")

    def remove_tool(self, tool_name: str) -> None:
        """
        Remove a tool by name.

        Args:
            tool_name: Name of the tool to remove
        """
        if tool_name in self._tools:
            del self._tools[tool_name]
            self.logger.debug(
                f"Removed tool: {tool_name}"
            )
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

    async def execute_tool(
        self,
        tool_name: str,
        parameters: Dict[str, Any]
    ) -> Any:
        """Execute a registered tool function."""

        if tool_name not in self._tools:
            raise ValueError(
                f"Tool '{tool_name}' not registered"
            )
        try:
            tool = self._tools[tool_name]
            if isinstance(tool, ToolDefinition):
                if asyncio.iscoroutinefunction(tool.function):
                    result = await tool.function(**parameters)
                else:
                    result = tool.function(**parameters)
                self.logger.debug(
                    f"Executed tool '{tool_name}' with parameters: {parameters}"
                )
                return result
            elif isinstance(tool, AbstractTool):
                # Handle AbstractTool (new)
                result = await tool.execute(**parameters)
                # Handle ToolResult objects
                if isinstance(result, ToolResult):
                    if result.status == "error":
                        raise ValueError(result.error)
                    out = result.result
                    meta = getattr(result, "metadata", {}) or {}
                else:
                    out = result
                    meta = {}
                self._postprocess_result(tool_name, out, meta)
                self._run_result_hooks(tool_name, out, meta)
                return out
            else:
                raise ValueError(
                    f"Unknown tool type: {type(tool)}"
                )
        except Exception as e:
            self.logger.error(
                f"Error executing tool {tool_name}: {e}"
            )
            raise

    async def execute_tool_call(
        self,
        content_block: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute a single tool call and return the result."""
        tool_name = content_block["name"]
        tool_input = content_block["input"]
        tool_id = content_block["id"]

        try:
            tool_result = await self.execute_tool(tool_name, tool_input)
            return {
                "type": "tool_result",
                "tool_use_id": tool_id,
                "content": str(tool_result)
            }
        except Exception as e:
            return {
                "type": "tool_result",
                "tool_use_id": tool_id,
                "is_error": True,
                "content": str(e)
            }

    def _postprocess_result(self, tool_name: str, out: Any, meta: Dict[str, Any]) -> None:
        """Auto-share DataFrame outputs and push to PythonPandasTool."""
        try:
            if not self.auto_share_dataframes:
                return
            # Handle single DF
            if isinstance(out, pd.DataFrame):
                # Prefer a semantic name when metadata exists
                base = meta.get("query_slug") or meta.get("name") or tool_name
                df_name = self._unique_df_name(base)
                self.share_dataframe(df_name, out, meta)
                return
            # Handle tuple or dict containers that embed a DataFrame under 'result'
            if isinstance(out, dict) and "result" in out and isinstance(out["result"], pd.DataFrame):
                base = meta.get("query_slug") or meta.get("name") or tool_name
                df_name = self._unique_df_name(base)
                self.share_dataframe(df_name, out["result"], meta)
        except Exception as e:
            self.logger.debug(f"No DF shared for {tool_name}: {e}")

    def _unique_df_name(self, base: str) -> str:
        base = (base or "df").replace(" ", "_").lower()
        name = base
        i = 1
        while name in self._shared["dataframes"]:
            i += 1
            name = f"{base}_{i}"
        return name


    def tool_count(self) -> int:
        """Get the number of registered tools."""
        return len(self._tools)

    def share_dataframe(self, name: str, df: "pd.DataFrame", meta: Dict[str, Any] = None) -> str:
        """Store df in shared context and push into python_pandas if present."""
        if not isinstance(df, pd.DataFrame):
            raise ValueError("share_dataframe expects a pandas.DataFrame")
        safe = name or f"df_{len(self._shared['dataframes'])+1}"
        self._shared["dataframes"][safe] = (df, meta or {})
        # auto-push into python_pandas
        if self.auto_push_to_pandas:
            pandas_tool = self.get_tool(self.pandas_tool_name)
            if pandas_tool:
                try:
                    msg = pandas_tool.add_dataframe(safe, df, regenerate_guide=True)
                    self.logger.debug(f"PandasTool: {msg}")
                except Exception as e:
                    self.logger.warning(f"Could not push DF into {self.pandas_tool_name}: {e}")
        return safe

    def get_shared_dataframe(self, name: str) -> "pd.DataFrame":
        df, _ = self._shared["dataframes"][name]
        return df

    def list_shared_dataframes(self) -> List[str]:
        return list(self._shared["dataframes"].keys())

    def clear_shared(self) -> None:
        self._shared = {"dataframes": {}}

    # == Hooks ==
    def add_result_hook(self, fn: Callable[[str, Any, Dict[str, Any]], None]) -> None:
        """Register a function(tool_name, result, metadata) -> None run after each tool."""
        self._result_hooks.append(fn)

    def _run_result_hooks(self, tool_name: str, result: Any, metadata: Dict[str, Any]) -> None:
        for fn in self._result_hooks:
            try:
                fn(tool_name, result, metadata)
            except Exception as e:
                self.logger.warning(f"Result hook error in {fn}: {e}")
