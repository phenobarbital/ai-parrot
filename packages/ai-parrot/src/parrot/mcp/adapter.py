import json
import logging
from typing import Any

from parrot.tools.abstract import AbstractTool, ToolResult


class MCPToolAdapter:
    """Adapts AI-Parrot AbstractTool to MCP tool format.

    Tools marked ``routing_meta["requires_confirmation"]`` (e.g. the
    destructive members of a toolkit's ``confirming_tools``) get an MCP-side
    guard: a required ``confirm`` boolean is injected into their input
    schema and the call is rejected unless ``confirm=true`` is passed —
    the stdio transport has no interactive HITL channel, so the explicit
    argument is the confirmation record.
    """

    def __init__(self, tool: AbstractTool):
        self.tool = tool
        self.logger = logging.getLogger(f"MCPToolAdapter.{tool.name}")

    def _requires_confirmation(self) -> bool:
        meta = getattr(self.tool, "routing_meta", None) or {}
        return bool(meta.get("requires_confirmation"))

    def to_mcp_tool_definition(self) -> dict[str, Any]:
        """Convert AbstractTool to MCP tool definition."""
        # Extract schema from the tool's args_schema
        input_schema = {}
        if hasattr(self.tool, 'args_schema') and self.tool.args_schema:
            try:
                # Get the JSON schema from the Pydantic model
                input_schema = self.tool.args_schema.model_json_schema()
            except Exception as e:  # noqa: BLE001
                self.logger.warning("Could not extract schema for %s: %s", self.tool.name, e)
                input_schema = {"type": "object", "properties": {}}

        if self._requires_confirmation():
            input_schema.setdefault("type", "object")
            input_schema.setdefault("properties", {})["confirm"] = {
                "type": "boolean",
                "description": (
                    "This operation is destructive. Set true ONLY after the "
                    "user has explicitly approved it; the call is rejected "
                    "otherwise."
                ),
            }
            required = input_schema.setdefault("required", [])
            if "confirm" not in required:
                required.append("confirm")

        return {
            "name": self.tool.name or "unknown_tool",
            "description": self.tool.description or f"Tool: {self.tool.name}",
            "inputSchema": input_schema
        }

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """Execute the AI-Parrot tool and convert result to MCP format."""
        # The guard argument never reaches the tool itself.
        confirm = arguments.pop("confirm", None)
        if self._requires_confirmation() and confirm is not True:
            return {
                "content": [
                    {
                        "type": "text",
                        "text": (
                            f"Error: '{self.tool.name}' is a destructive "
                            "operation and was not confirmed. Ask the user "
                            "for approval, then re-invoke with confirm=true."
                        ),
                    }
                ],
                "isError": True,
            }
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

        except Exception as e:  # noqa: BLE001
            self.logger.error("Tool execution failed: %s", e)
            return {
                "content": [
                    {
                        "type": "text",
                        "text": f"Error executing tool: {e!s}"
                    }
                ],
                "isError": True
            }

    def _toolresult_to_mcp(self, result: ToolResult) -> dict[str, Any]:
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
