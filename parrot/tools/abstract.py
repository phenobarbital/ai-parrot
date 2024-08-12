from typing import Optional, Dict, Any, Type
from abc import abstractmethod
from langchain_core.pydantic_v1 import BaseModel, Field, Extra
from langchain_core.callbacks import CallbackManagerForToolRun
from langchain_core.tools import BaseTool

class AbstractToolArgsSchema(BaseModel):
    """Schema for the arguments to the AbstractTool."""

    # This Field allows any number of arguments to be passed in.
    args: list = Field(description="A list of arguments to the tool")


class AbstractTool(BaseTool):
    """Abstract class for tools."""

    args_schema: Type[BaseModel] = AbstractToolArgsSchema

    class Config:
        """Configuration for this pydantic object."""
        extra = Extra.forbid
        arbitrary_types_allowed = True

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
