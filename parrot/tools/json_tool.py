from typing import Any, Type, Dict
from pydantic import BaseModel, Field
from parrot.tools.abstract import AbstractTool, ToolResult
from datamodel.parsers.json import JSONContent

class ToJsonArgs(BaseModel):
    data: Any = Field(..., description="The data content to convert to JSON")

class ToJsonTool(AbstractTool):
    """
    Tool to convert data to JSON using datamodel.parsers.json.
    """
    name = "to_json"
    description = "Converts input data to JSON format."
    args_schema = ToJsonArgs

    async def _execute(self, data: Any, **kwargs) -> ToolResult:
        try:
            json_lib = JSONContent()
            result = json_lib.dumps(data)
            return ToolResult(
                result=result,
                status="success"
            )
        except Exception as e:
            self.logger.error(f"Error converting to JSON: {e}")
            return ToolResult(
                status="error",
                error=str(e),
                result=None
            )
