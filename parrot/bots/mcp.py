from typing import List
from ..mcp import MCPEnabledMixin, MCPServerConfig
from .agent import BasicAgent


class MCPAgent(MCPEnabledMixin, BasicAgent):
    """An agent that combines MCP capabilities with basic agent functionality."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    async def setup_mcp_servers(self, configurations: List[MCPServerConfig]):
        """Setup multiple MCP servers during initialization."""
        for config in configurations:
            try:
                tools = await self.add_mcp_server(
                    config
                )
                self.logger.info(
                    f"Added MCP server '{config.name}' with tools: {tools}"
                )
            except Exception as e:
                self.logger.error(
                    f"Failed to add MCP server '{config.name}': {e}"
                )
