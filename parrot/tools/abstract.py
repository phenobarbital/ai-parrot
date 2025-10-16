"""
Abstract Tool base class and MathTool implementation.
"""
import importlib
import inspect
import os
from typing import Dict, Any, Union, Optional, Type
from abc import ABC, abstractmethod
from pathlib import Path
from datetime import datetime
import traceback
import asyncio
import logging
from dataclasses import dataclass
from urllib.parse import urlparse, urlunparse
from pydantic import BaseModel, Field
from datamodel.parsers.json import json_decoder, json_encoder, JSONContent  # noqa  pylint: disable=E0611
from navconfig.logging import logging
from ..conf import BASE_STATIC_URL, STATIC_DIR


logging.getLogger(name='matplotlib').setLevel(logging.INFO)
logging.getLogger(name='h5py').setLevel(logging.INFO)
logging.getLogger(name='datasets').setLevel(logging.WARNING)
logging.getLogger(name='numexpr').setLevel(logging.WARNING)
logging.getLogger(name='pymongo').setLevel(logging.WARNING)


class AbstractToolArgsSchema(BaseModel):
    """Base schema for tool arguments."""
    pass


class ToolResult(BaseModel):
    """Standardized tool result format."""
    status: str = Field(default="success", description="Status of the operation")
    result: Any = Field(description="The actual result of the tool operation")
    error: Optional[str] = Field(default=None, description="Error message if any")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional metadata")
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())


class AbstractTool(ABC):
    """
    Abstract base class for all tools in the ai-parrot framework.

    This class provides a unified interface for tools that can be used by both
    conversational bots and agents. It includes common functionality like:
    - Name and description management
    - JSON schema generation
    - File path management
    - Logging and error handling
    - Async/sync execution support
    """

    # Class attributes that should be set by subclasses
    name: str = None
    description: str = None
    args_schema: Type[BaseModel] = AbstractToolArgsSchema
    return_direct: bool = False

    def __init__(
        self,
        name: Optional[str] = None,
        description: Optional[str] = None,
        output_dir: Optional[Union[str, Path]] = None,
        base_url: Optional[str] = None,
        static_dir: Optional[Union[str, Path]] = None,
        **kwargs
    ):
        """
        Initialize the tool.

        Args:
            name: Tool name (defaults to class name)
            description: Tool description
            output_dir: Directory for output files (if tool generates files)
            base_url: Base URL for serving static files
            static_dir: Static directory path
            **kwargs: Additional configuration
        """
        # Set name and description
        self.name = name or self.name or self.__class__.__name__
        self.description = description or self.__class__.__doc__ or f"Tool: {self.name}"

        # Set up logging
        self.logger = logging.getLogger(
            f'{self.name}.Tool'
        )

        # JSON encoders/decoders
        self._json_encoder = json_encoder
        self._json_decoder = json_decoder
        self._json = JSONContent()

        # File and URL configuration
        self.base_url = base_url or BASE_STATIC_URL
        self.static_url = base_url or BASE_STATIC_URL
        parsed = urlparse(self.static_url)
        self._base_scheme_netloc = (parsed.scheme, parsed.netloc)

        # Set up directories
        self.static_dir = Path(static_dir or STATIC_DIR).resolve()

        self.output_dir = Path(output_dir).resolve() if output_dir else self._default_output_dir()

        # Ensure output directory exists if specified
        if self.output_dir and not self.output_dir.exists():
            self.output_dir.mkdir(parents=True, exist_ok=True)

    def _default_output_dir(self) -> Optional[Path]:
        """Get the default output directory for this tool type."""
        # Default implementation - tools that don't need output can return None
        return None

    @abstractmethod
    async def _execute(self, **kwargs) -> Any:
        """
        Execute the tool with the given arguments.
        This is the main method that subclasses must implement.

        Args:
            **kwargs: Tool arguments

        Returns:
            Tool execution result
        """
        pass

    def get_tool_schema(self) -> Dict[str, Any]:
        """
        Get the JSON schema for this tool.

        Returns:
            JSON schema dictionary compatible with LLM tool registration
        """
        schema = {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
                "additionalProperties": False
            }
        }

        # If args_schema is defined, use it to build the parameters
        if self.args_schema and self.args_schema != AbstractToolArgsSchema:
            pydantic_schema = self.args_schema.model_json_schema()
            schema["parameters"] = {
                "type": "object",
                "properties": pydantic_schema.get("properties", {}),
                "required": pydantic_schema.get("required", []),
                "additionalProperties": False
            }

        return schema

    def validate_args(self, **kwargs) -> BaseModel:
        """
        Validate arguments using the tool's schema.

        Args:
            **kwargs: Arguments to validate

        Returns:
            Validated arguments as Pydantic model instance
        """
        if not self.args_schema or self.args_schema == AbstractToolArgsSchema:
            # If no schema is defined, return a basic model with the kwargs
            return AbstractToolArgsSchema()
        try:
            result = self.args_schema(**kwargs)
            if not result:
                self.logger.warning(
                    f"Validation failed for {self.name} with args: {kwargs}"
                )
            return result
        except Exception as e:
            self.logger.error(f"Validation error in {self.name}: {e}")
            raise ValueError(
                f"Invalid arguments for {self.name}: {e}"
            ) from e


    async def execute(self, *args, **kwargs) -> ToolResult:
        """
        Execute the tool with error handling and result standardization.

        Args:
            **kwargs: Tool arguments

        Returns:
            Standardized ToolResult

        TODO: Use the Global Registry to share data between tools.
        """
        try:
            self.logger.notice(f"Executing tool: {self.name}")

            # Validate arguments
            validated_args = self.validate_args(**kwargs)

            # Execute the tool
            if hasattr(validated_args, 'model_dump'):
                result = await self._execute(*args, **validated_args.model_dump())
            else:
                result = await self._execute(*args, **kwargs)

            # if is an toolResult, return it directly
            if isinstance(result, ToolResult):
                return result
            elif isinstance(result, dict) and 'status' in result and 'result' in result:
                try:
                    return ToolResult(**result)
                except Exception as e:
                    self.logger.error(f"Error creating ToolResult from dict: {e}")
                    return ToolResult(
                        status="done_with_errors",
                        result=result.get('result', []),
                        error=f"Error creating ToolResult: {e}",
                        metadata=result.get('metadata', {})
                    )
            if result is None:
                raise ValueError(
                    "Tool execution returned None, expected a result."
                )

            self.logger.info(f"Tool {self.name} executed successfully")

            return ToolResult(
                status="success",
                result=result,
                metadata={
                    "tool_name": self.name,
                    "execution_time": datetime.now().isoformat()
                }
            )

        except Exception as e:
            print('ERROR')
            print(f'============ {e} ============')
            error_msg = f"Error in {self.name}: {str(e)}"
            self.logger.error(error_msg)
            self.logger.error(traceback.format_exc())

            return ToolResult(
                status="error",
                result=None,
                error=error_msg,
                metadata={
                    "tool_name": self.name,
                    "error_type": type(e).__name__
                }
            )

    run = execute  # Alias for compatibility with sync code

    # Utility methods for file handling (inherited from BaseAbstractTool)
    def to_static_url(self, file_path: Union[str, Path]) -> str:
        """
        Convert an absolute file path to a static URL.

        Args:
            file_path: Absolute path to the file

        Returns:
            URL-based path for serving the static file
        """
        if not self.static_dir:
            return str(file_path)

        file_path = Path(file_path)

        try:
            relative_path = file_path.relative_to(self.static_dir)
            return f"{self.static_url.rstrip('/')}/{relative_path}"
        except ValueError:
            self.logger.warning(
                f"File {file_path} is not within static directory {self.static_dir}"
            )
            return str(file_path)

    def relative_url(self, url: str) -> str:
        """
        Convert an absolute URL to a relative URL based on the base URL.

        Args:
            url: Absolute URL to convert

        Returns:
            Relative URL based on the base URL
        """
        parts = urlparse(url)
        if not parts.scheme or not parts.netloc:
            return url

        if (parts.scheme, parts.netloc) == self._base_scheme_netloc:
            return urlunparse((
                "", "", parts.path, parts.params, parts.query, parts.fragment
            ))
        return url

    def generate_filename(
        self,
        prefix: str = "output",
        extension: str = "",
        include_timestamp: bool = True
    ) -> str:
        """
        Generate a unique filename with optional timestamp.

        Args:
            prefix: File prefix
            extension: File extension (with or without dot)
            include_timestamp: Whether to include timestamp

        Returns:
            Generated filename
        """
        if include_timestamp:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"{prefix}_{timestamp}"
        else:
            filename = prefix

        if extension:
            if not extension.startswith('.'):
                extension = f".{extension}"
            filename += extension

        return filename

    def validate_output_path(self, file_path: Union[str, Path]) -> Path:
        """
        Validate and ensure the output path is within allowed directories.

        Args:
            file_path: Path to validate

        Returns:
            Validated Path object

        Raises:
            ValueError: If path is outside allowed directories
        """
        if not self.static_dir:
            return Path(file_path).resolve()

        file_path = Path(file_path).resolve()

        try:
            file_path.relative_to(self.static_dir.resolve())
        except ValueError as e:
            raise ValueError(
                f"Output path {file_path} must be within static directory {self.static_dir}"
            ) from e

        return file_path

    def __str__(self) -> str:
        return f"{self.name}: {self.description}"

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}(name='{self.name}')>"


@dataclass
class ToolInfo:
    """Information about a discovered tool."""
    class_name: str
    module_name: str
    description: str
    tool_name: str
    file_path: str
    args_schema: Optional[Dict[str, Any]] = None


# Tool Registry for easy tool management
class ToolRegistry:
    """Registry for managing available tools."""

    def __init__(self):
        self._tools = {}
        self.tools_package_path = 'parrot/tools'
        self.discovered_tools: Dict[str, ToolInfo] = {}
        self.loaded_classes: Dict[str, Type[AbstractTool]] = {}

    def _create_tool_info(
        self,
        cls: Type[AbstractTool],
        class_name: str,
        module_name: str,
        file_path: str
    ) -> ToolInfo:
        """Create ToolInfo object from a tool class."""
        try:
            # Get tool description
            description = getattr(cls, 'description', cls.__doc__ or 'No description available')

            # Get tool name
            tool_name = getattr(cls, 'name', class_name)

            # Get args schema if available
            args_schema = None
            if hasattr(cls, 'args_schema') and cls.args_schema:
                try:
                    args_schema = cls.args_schema.model_json_schema()
                except Exception as e:
                    logging.debug(f"Could not get schema for {class_name}: {e}")

            return ToolInfo(
                class_name=class_name,
                module_name=module_name,
                description=description,
                tool_name=tool_name,
                file_path=file_path,
                args_schema=args_schema
            )

        except Exception as e:
            logging.error(f"Error creating tool info for {class_name}: {e}")
            return ToolInfo(
                class_name=class_name,
                module_name=module_name,
                description="Error loading description",
                tool_name=class_name,
                file_path=file_path
            )

    def _process_python_file(self, file_path: Path, tools_dir: Path) -> None:
        """Process a single Python file to find tool classes."""
        try:
            # Get relative path from tools directory
            relative_to_tools = file_path.relative_to(tools_dir)
            # Build module name using the configured tools_package_path
            base_package = self.tools_package_path.replace('/', '.')  # 'parrot.tools'

            # Add any subdirectories and filename
            if relative_to_tools.parent != Path('.'):
                # Handle subdirectories: e.g., 'analysis/correlation.py' -> 'parrot.tools.analysis.correlation'
                subpath = str(relative_to_tools.parent).replace(os.sep, '.')
                module_name = f"{base_package}.{subpath}.{relative_to_tools.stem}"
            else:
                # Direct file in tools directory: 'google.py' -> 'parrot.tools.google'
                module_name = f"{base_package}.{relative_to_tools.stem}"

            logging.debug(f"Processing module: {module_name}")

            # Import the module
            module = importlib.import_module(module_name)

            # Find tool classes in the module
            for name, obj in inspect.getmembers(module, inspect.isclass):
                if issubclass(obj, AbstractTool):
                    if name == 'AbstractTool':
                        continue
                    tool_info = self._create_tool_info(
                        obj,
                        name,
                        module_name,
                        str(file_path)
                    )
                    self.discovered_tools[name] = tool_info
                    self.loaded_classes[name] = obj
                    logging.debug(f"Found tool: {name}")

        except Exception as e:
            logging.error(f"Error processing {file_path}: {e}")

    def discover_tools(self) -> Dict[str, ToolInfo]:
        """
        Discover all tool classes in the tools package.

        Returns:
            Dict mapping class names to ToolInfo objects
        """
        tools_dir = Path(self.tools_package_path).resolve()
        if not tools_dir.exists():
            logging.warning(f"Tools directory '{tools_dir}' does not exist")
            return {}

        # Clear previous discoveries
        self.discovered_tools.clear()
        self.loaded_classes.clear()

        # walk through the tools directory and find all .py files
        for file_path in tools_dir.rglob('*.py'):
            if file_path.name.startswith('_'):
                continue
            self._process_python_file(file_path, tools_dir)

        logging.info(f"Discovered {len(self.discovered_tools)} tools")
        return self.discovered_tools

    def register_toolkit(self, toolkit: Type[AbstractTool], prefix: str = ""):
        """
        Register all tools from a toolkit in a tool registry.

        Args:
            registry: Tool registry instance
            toolkit: Toolkit instance
            prefix: Optional prefix for tool names
        """
        tools = toolkit.get_tools()
        for tool in tools:
            tool_name = f"{prefix}{tool.name}" if prefix else tool.name
            self.register(tool.__class__, tool_name)

    def register(self, tool_class: Type[AbstractTool], name: Optional[str] = None):
        """Register a tool class."""
        tool_name = name or tool_class.name or tool_class.__name__
        self._tools[tool_name] = tool_class

    def register_by_name(self, tool_name: str):
        """Register a tool class by its name."""
        if tool_name in self._tools:
            raise ValueError(f"Tool '{tool_name}' is already registered")
        # use importlib to dynamically import the tool class
        file_name = tool_name.lower().replace('tool', '')
        try:
            module = __import__(f"parrot.tools.{file_name}", fromlist=[tool_name])
            tool_class = getattr(module, tool_name)
        except (ImportError, AttributeError) as e:
            raise ValueError(f"Could not import tool '{tool_name}': {e}")
        if not issubclass(tool_class, AbstractTool):
            raise ValueError(f"Tool '{tool_name}' must be a subclass of AbstractTool")
        if tool_name in self._tools:
            raise ValueError(f"Tool '{tool_name}' is already registered")
        # Register the tool class
        self._tools[tool_name] = tool_class

    def get_tool(self, name: str, **kwargs) -> AbstractTool:
        """Get an instance of a tool by name."""
        if name not in self._tools:
            raise ValueError(f"Tool '{name}' not found in registry")

        tool_class = self._tools[name]
        return tool_class(**kwargs)

    def list_tools(self) -> Dict[str, str]:
        """List all registered tools with their descriptions."""
        return {
            name: getattr(tool_class, 'description', 'No description')
            for name, tool_class in self._tools.items()
        }

    def get_all_schemas(self) -> Dict[str, Dict[str, Any]]:
        """Get schemas for all registered tools."""
        schemas = {}
        for name, tool_class in self._tools.items():
            try:
                # Create a temporary instance to get schema
                temp_instance = tool_class()
                schemas[name] = temp_instance.get_tool_schema()
            except Exception as e:
                logging.error(f"Error getting schema for tool {name}: {e}")
        return schemas
