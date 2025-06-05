from typing import Optional, Dict, List, Any, Type
from abc import abstractmethod
import inspect
from pydantic import BaseModel, Field
from langchain_core.callbacks import CallbackManagerForToolRun
from langchain_core.tools import BaseTool, BaseToolkit, StructuredTool
from navconfig.logging import logging
from datamodel.parsers.json import json_decoder, json_encoder  # noqa  pylint: disable=E0611


logging.getLogger(name='cookie_store').setLevel(logging.INFO)
logging.getLogger(name='httpx').setLevel(logging.INFO)
logging.getLogger(name='httpcore').setLevel(logging.WARNING)
logging.getLogger(name='primp').setLevel(logging.WARNING)

class AbstractToolArgsSchema(BaseModel):
    """Schema for the arguments to the AbstractTool."""

    # This Field allows any number of arguments to be passed in.
    args: list = Field(description="A list of arguments to the tool")


class AbstractTool(BaseTool):
    """Abstract class for tools."""

    args_schema: Type[BaseModel] = AbstractToolArgsSchema
    _json_encoder: Type[Any] = json_encoder
    _json_decoder: Type[Any] = json_decoder

    class Config:
        """Configuration for this pydantic object."""
        arbitrary_types_allowed = True

    def __init__(self, *args, **kwargs):
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
