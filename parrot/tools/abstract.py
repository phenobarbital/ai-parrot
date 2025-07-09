from typing import Optional, Dict, List, Any, Type, Union
from abc import ABC, abstractmethod
from datetime import datetime
from urllib.parse import urlparse, urlunparse
import traceback
import asyncio
import inspect
from pathlib import Path
from pydantic import BaseModel, Field
from langchain_core.callbacks import CallbackManagerForToolRun
from langchain_core.tools import BaseTool, BaseToolkit, StructuredTool
from navconfig import BASE_DIR
from navconfig.logging import logging
from datamodel.parsers.json import json_decoder, json_encoder  # noqa  pylint: disable=E0611
from ..conf import BASE_STATIC_URL, STATIC_DIR


logging.getLogger(name='cookie_store').setLevel(logging.INFO)
logging.getLogger(name='httpx').setLevel(logging.INFO)
logging.getLogger(name='httpcore').setLevel(logging.WARNING)
logging.getLogger(name='primp').setLevel(logging.WARNING)


class AbstractToolArgsSchema(BaseModel):
    """Schema for the arguments to the AbstractTool."""

    # This Field allows any number of arguments to be passed in.
    args: list = Field(description="A list of arguments to the tool")


class AbstractTool(BaseTool, ABC):
    """
    Abstract base class for all generator tools (PDF, PPT, Podcast, etc.).
    Provides common functionality like file path management and URL generation.
    """

    args_schema: Type[BaseModel] = AbstractToolArgsSchema
    _json_encoder: Type[Any] = json_encoder
    _json_decoder: Type[Any] = json_decoder

    class Config:
        """Configuration for this pydantic object."""
        arbitrary_types_allowed = True

    def __init__(
        self,
        *args,
        **kwargs
    ):
        super().__init__(*args, **kwargs)
        self.name = kwargs.pop('name', self.__class__.__name__)
        self.logger = logging.getLogger(
            f'{self.name}.Tool'
        )

    @abstractmethod
    def _search(self, query: str) -> str:
        """Run the tool."""

    async def _asearch(self, *args, **kwargs):
        """Run the tool asynchronously."""
        return self._search(*args, **kwargs)

    def _run(
        self,
        query: str,
        run_manager: Optional[CallbackManagerForToolRun] = None
    ) -> Dict[str, Any]:
        args = [a.strip() for a in query.split(',')]
        try:
            return self._search(*args)
        except Exception as e:
            raise ValueError(f"Error running tool: {e}") from e

    async def _arun(
        self,
        query: str,
        run_manager: Optional[CallbackManagerForToolRun] = None
    ) -> Dict[str, Any]:
        """Use the tool asynchronously."""
        args = [a.strip() for a in query.split(',')]
        try:
            return await self._asearch(*args)
        except Exception as e:
            raise ValueError(f"Error running tool: {e}") from e


class AbstractToolkit(BaseToolkit):
    """
    A “drop-in” base class for all toolkits.  Any concrete subclass:
        1. must define a class variable `input_class = <SomePydanticModel>`
            (used as `args_schema` for every tool).
        2. may add any number of `async def <public_method>(…)` methods.
        3. will automatically have `get_tools()` implemented for you.
    """
    input_class: Type[BaseModel] = None
    tool_list: Dict[str, BaseTool] = {}
    model_config = {
        "arbitrary_types_allowed": True
    }
    json_encoder: Type[Any] = json_encoder  # Type for JSON encoder, if needed
    json_decoder: Type[Any] = json_decoder  # Type for JSON decoder, if needed
    base_url: str = BASE_STATIC_URL  # Base URL for static files
    return_direct: bool = True  # Whether to return raw output directly

    def get_tools(self) -> list[BaseTool]:
        """
        Inspect every public `async def` on the subclass, and convert it into
        a StructuredTool.  Returns a list of StructuredTool instances.
        """
        tools: List[BaseTool] = []
        # 1) Walk through all coroutine functions defined on this subclass
        for name, func in inspect.getmembers(self, predicate=inspect.iscoroutinefunction):
            # 2) Skip any “private” or dunder methods:
            if name.startswith("_"):
                continue

            # 3) Skip the get_tools method itself
            if name in ("get_tools", "get_tool"):
                continue

            # 4) Build a StructuredTool for this method
            #    We will bind the method to an instance when the agent actually runs,
            #    but for now we just register its definition.
            tool = self._return_structured_tool(func_name=name, method=func)
            tools.append(
                tool
            )
            self.tool_list[name] = tool

        return tools

    def get_tool(self, name: str) -> Optional[BaseTool]:
        """Get a tool by name."""
        if name in self.tool_list:  # Check the cached tool list first
            return self.tool_list[name]
        for tool in self.get_tools():
            if tool.name == name:
                return tool
        return None

    def _return_structured_tool(self, func_name: str, method) -> StructuredTool:
        """
        Given the name of the coroutine (func_name) and its function object,
        produce a StructuredTool that wraps it.

        Assumptions:
        - The subclass defines `input_class` as a valid Pydantic `BaseModel`.
        - We take the docstring from `method.__doc__` as the tool’s description.
        """
        if not hasattr(self, "input_class"):
            raise AttributeError(f"{self.__name__} must define `input_class = <SomePydanticModel>`")

        args_schema = getattr(method, "_arg_schema", getattr(self, "input_class"))
        # Extract docstring (or use empty string if none)
        description = method.__doc__ or ""

        # name the tool exactly the same as the method’s name:
        return StructuredTool.from_function(
            name=func_name,
            func=method,         # the coroutine function itself
            coroutine=method,     # same as func, because it’s async
            description=description.strip(),
            args_schema=args_schema,
            return_direct=self.return_direct,   # instruct LangChain to hand the raw return back to the agent
            handle_tool_error=True,
        )


class BaseAbstractTool(BaseTool, ABC):
    """
    Abstract base class for all generator tools (PDF, PPT, Podcast, etc.).
    Provides common functionality like file path management and URL generation.
    """

    args_schema: Type[BaseModel] = AbstractToolArgsSchema
    _json_encoder: Type[Any] = json_encoder
    _json_decoder: Type[Any] = json_decoder
    static_dir: Path = None
    base_url: str = BASE_STATIC_URL
    _base_scheme_netloc: tuple = None
    output_dir: Optional[Path] = None
    logger: logging.Logger = None

    class Config:
        """Configuration for this pydantic object."""
        arbitrary_types_allowed = True

    def __init__(
        self,
        *args,
        output_dir: Optional[Union[str, Path]] = None,
        base_url: Optional[str] = None,
        **kwargs
    ):
        super().__init__(*args, **kwargs)
        self.name = kwargs.pop('name', self.__class__.__name__)
        self.logger = logging.getLogger(
            f'{self.name}.Tool'
        )
        # Set up output directory
        if output_dir:
            self.output_dir = Path(output_dir).resolve()
        else:
            self.output_dir = self._default_output_dir()
        # Ensure output directory exists
        if not self.output_dir.exists():
            self.output_dir.mkdir(parents=True, exist_ok=True)
        # Configure base URL if provided
        self.base_url = base_url or BASE_STATIC_URL
        parsed = urlparse(self.base_url)
        self._base_scheme_netloc = (parsed.scheme, parsed.netloc)
        # set static directory
        self.static_dir = kwargs.get('static_dir', STATIC_DIR)
        if isinstance(self.static_dir, str):
            self.static_dir = Path(self.static_dir).resolve()

    @abstractmethod
    def _default_output_dir(self) -> Path:
        """Get the default output directory for this tool type."""
        pass

    @abstractmethod
    async def _generate_content(self, payload: BaseModel) -> Dict[str, Any]:
        """Main content generation method - must be implemented by subclasses."""
        pass

    def to_static_url(self, file_path: Union[str, Path]) -> str:
        """
        Convert an absolute file path to a static URL.

        Args:
            file_path: Absolute path to the file

        Returns:
            URL-based path for serving the static file

        Example:
            Input:  "/home/user/project/static/documents/pdf/report.pdf"
            Output: "/static/documents/pdf/report.pdf"
        """
        file_path = Path(file_path)

        # Check if the file is within the static directory
        try:
            relative_path = file_path.relative_to(self.static_dir)
            return f"{self.base_url.rstrip('/')}/{relative_path}"
        except ValueError:
            # File is not within static directory
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
        # if url is not absolute, return as is:
        if not parts.scheme or not parts.netloc:
            return url
        # only strip when scheme+netloc match
        if (parts.scheme, parts.netloc) == self._base_scheme_netloc:
            # urlunparse with empty scheme/netloc → just path;params?query#frag
            return urlunparse((
                "",
                "",
                parts.path,
                parts.params,
                parts.query,
                parts.fragment,
            ))
        return url

    def generate_filename(
        self,
        prefix: str = "document",
        extension: str = "",
        include_timestamp: bool = True
    ) -> str:
        """
        Generate a unique filename with optional timestamp.

        Args:
            prefix: File prefix (default: "document")
            extension: File extension (with or without dot)
            include_timestamp: Whether to include timestamp in filename

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

    async def safe_generate(self, payload: BaseModel) -> Dict[str, Any]:
        """
        Safely generate content with error handling and logging.

        Args:
            payload: Validated input payload

        Returns:
            Generation result with standardized error handling
        """
        try:
            self.logger.info(f"Starting content generation with {self.__class__.__name__}")
            result = await self._generate_content(payload)

            # Add file info if a file was generated
            # if "filename" in result and result.get("status") == "success":
                # file_info = self.get_file_info(result["filename"])
                # result.update(file_info)

            self.logger.info(
                "Content generation completed successfully"
            )
            return result

        except Exception as e:
            error_msg = f"Error in {self.__class__.__name__}: {str(e)}"
            self.logger.error(error_msg)
            self.logger.error(traceback.format_exc())

            return {
                "status": "error",
                "error": error_msg,
                "timestamp": datetime.now().isoformat()
            }

    @abstractmethod
    def _generate_payload(self, **kwargs) -> BaseModel:
        """
        Generate a payload from the provided arguments.
        This method should be implemented by subclasses to convert
        input arguments into a Pydantic model instance.
        """
        pass

    async def _arun(
        self,
        *args,
        **kwargs: Any
    ) -> Dict[str, Any]:
        """
        LangChain will call this with keyword args matching Input, e.g.:
        _arun(text="Hello", output_dir="documents/", …)
        """
        try:
            # 1) Build a dict of everything LangChain passed us
            # 2) Let Pydantic validate & coerce
            payload = self._generate_payload(**kwargs)
            # 3) Call the “real” generator
            return await self.safe_generate(payload)
        except Exception as e:
            print(f"❌ Error in Document._arun: {e}")
            print(traceback.format_exc())
            return {"error": str(e)}

    def _run(self, *args, **kwargs) -> Dict[str, Any]:
        """Synchronous entry point."""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(self._arun(*args, **kwargs))
        finally:
            loop.close()

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
        file_path = Path(file_path).resolve()

        # Ensure the path is within the static directory for security
        try:
            file_path.relative_to(self.static_dir.resolve())
        except ValueError:
            raise ValueError(
                f"Output path {file_path} must be within static directory {self.static_dir}"
            )

        return file_path
