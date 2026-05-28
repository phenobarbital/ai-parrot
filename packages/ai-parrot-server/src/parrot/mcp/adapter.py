import logging
import json
from typing import Dict, Any

from parrot.tools.abstract import AbstractTool, ToolResult

class MCPToolAdapter:
    """Adapts AI-Parrot AbstractTool to MCP tool format."""

    def __init__(self, tool: AbstractTool):
        self.tool = tool
        self.logger = logging.getLogger(f"MCPToolAdapter.{tool.name}")

    def to_mcp_tool_definition(self) -> Dict[str, Any]:
        """Convert AbstractTool to MCP tool definition."""
        # Extract schema from the tool's args_schema
        input_schema = {}
        if hasattr(self.tool, 'args_schema') and self.tool.args_schema:
            try:
                # Get the JSON schema from the Pydantic model
                input_schema = self.tool.args_schema.model_json_schema()
            except Exception as e:
                self.logger.warning(f"Could not extract schema for {self.tool.name}: {e}")
                input_schema = {"type": "object", "properties": {}}

        return {
            "name": self.tool.name or "unknown_tool",
            "description": self.tool.description or f"Tool: {self.tool.name}",
            "inputSchema": input_schema
        }

    async def execute(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Execute the AI-Parrot tool and convert result to MCP format."""
        try:
            # Execute the tool
            result = await self.tool._execute(**arguments)

            # Convert ToolResult to MCP response format
            if isinstance(result, ToolResult):
                return self._toolresult_to_mcp(result)
            else:
                # Handle direct results (for backward compatibility)
                return {
                    "content": [
                        {
                            "type": "text",
                            "text": str(result)
                        }
                    ],
                    "isError": False
                }

        except Exception as e:
            self.logger.error(f"Tool execution failed: {e}")
            return {
                "content": [
                    {
                        "type": "text",
                        "text": f"Error executing tool: {str(e)}"
                    }
                ],
                "isError": True
            }

    def _toolresult_to_mcp(self, result: ToolResult) -> Dict[str, Any]:
        """Convert ToolResult to MCP response format."""
        content_items = []

        if result.status == "success":
            # Handle different result types
            if isinstance(result.result, str):
                content_items.append({
                    "type": "text",
                    "text": result.result
                })
            elif isinstance(result.result, dict):
                content_items.append({
                    "type": "text",
                    "text": json.dumps(result.result, indent=2, default=str)
                })
            else:
                content_items.append({
                    "type": "text",
                    "text": str(result.result)
                })

            # Add metadata if present
            if result.metadata:
                content_items.append({
                    "type": "text",
                    "text": f"\nMetadata: {json.dumps(result.metadata, indent=2, default=str)}"
                })

        else:
            # Handle error case
            error_text = result.error or "Unknown error occurred"
            content_items.append({
                "type": "text",
                "text": f"Error: {error_text}"
            })

        return {
            "content": content_items,
            "isError": result.status != "success"
        }
