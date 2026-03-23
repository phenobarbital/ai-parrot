"""
Simplified MCPAgent for backward compatibility.

Since BasicAgent now has integrated MCP support, MCPAgent is now just
an alias to BasicAgent. This file maintains backward compatibility for
existing code that uses MCPAgent.
"""
from .agent import BasicAgent


class MCPAgent(BasicAgent):
    """
    An agent with MCP (Model Context Protocol) capabilities.

    DEPRECATED: This class is now just an alias to BasicAgent.
    All agents (BasicAgent and subclasses) now have MCP support built-in.

    For new code, use BasicAgent directly:
        agent = BasicAgent(name="my_agent")
        await agent.add_http_mcp_server(...)

    This class is maintained for backward compatibility only.
    """

    def __init__(self, *args, **kwargs):
        """
        Initialize MCPAgent.

        Note: This is now identical to BasicAgent initialization.
        All MCP functionality is available in BasicAgent.
        """
        super().__init__(*args, **kwargs)
        self.logger.debug(
            f"MCPAgent '{self.name}' initialized. "
            "Note: MCPAgent is deprecated, use BasicAgent instead."
        )
