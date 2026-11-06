Fireflies MCP Server Configuration Fix
Problem Summary
The Fireflies MCP server was failing to connect with HTTP 401 and 406 errors when attempting to use direct HTTP JSON-RPC communication. Investigation revealed that Fireflies MCP requires using npx mcp-remote as a command-line proxy with stdio transport, not direct HTTP connections.

Initial Issues Encountered
HTTP 401 Unauthorized: Missing Bearer token prefix in Authorization header
HTTP 406 Not Acceptable: The endpoint doesn't accept direct JSON-RPC HTTP requests
Root Cause
The Fireflies API documentation shows that their MCP server must be accessed via the mcp-remote npm package:

{
  "mcpServers": {
    "fireflies": {
      "command": "npx",
      "args": [
        "mcp-remote",
        "https://api.fireflies.ai/mcp",
        "--header",
        "Authorization: Bearer YOUR_API_KEY_HERE"
      ]
    }
  }
}
Changes Implemented
1. Updated
create_fireflies_mcp_server
 Function
File:
parrot/mcp/integration.py

Before: OAuth-based configuration with HTTP transport
After: API key-based configuration with stdio transport

def create_fireflies_mcp_server(
     *,
-    user_id: str,
-    client_id: str,
-    auth_url: str = "https://api.fireflies.ai/oauth/authorize",
-    token_url: str = "https://api.fireflies.ai/oauth/token",
-    scopes: list[str] = ("meetings:read", "transcripts:read"),
+    api_key: str,
     api_base: str = "https://api.fireflies.ai/mcp",
-    client_secret: str | None = None,
-    redis=None,
+    **kwargs
 ) -> MCPServerConfig:
-    return create_oauth_mcp_server(
+    return MCPServerConfig(
         name="fireflies",
-        url=api_base,
-        ...
+        command="npx",
+        args=[
+            "mcp-remote",
+            api_base,
+            "--header",
+            f"Authorization: Bearer {api_key}"
+        ],
+        transport="stdio",
+        **kwargs
     )
2. Updated
add_fireflies_mcp_server
 Method
File:
parrot/mcp/integration.py

Simplified the signature to only require an API key:

async def add_fireflies_mcp_server(
    self,
    api_key: str,
    **kwargs
) -> List[str]:
    """Add Fireflies.ai MCP server capability."""
    config = create_fireflies_mcp_server(api_key=api_key, **kwargs)
    return await self.add_mcp_server(config)
3. Created Bearer Token Support (Collateral Enhancement)
File:
parrot/mcp/client.py

Added use_bearer_prefix parameter to MCPAuthHandler._get_api_key_headers() for other APIs that might need Bearer token format with HTTP transport.

Testing
Test Script
File:
examples/test_fireflies_bearer_auth.py

async def test_fireflies_auth():
    agent = BasicAgent(
        name="test-agent",
        model="gpt-4",
        instructions="You are a helpful assistant.",
    )

    await agent.configure()

    # Add Fireflies MCP server
    tools = await agent.add_fireflies_mcp_server(
        api_key="c73a26e6-73d1-4b1d-a0c8-c7065099fa5e"
    )

    print(f"✅ Successfully registered Fireflies tools: {tools}")
    await agent.cleanup()
Test Results
✅ SUCCESS - The connection now works correctly:

[INFO] Connected to MCP server fireflies via stdio with 8 tools
✅ Successfully registered Fireflies tools: [
  'mcp_fireflies_fireflies_get_transcript',
  'mcp_fireflies_fireflies_get_summary',
  'mcp_fireflies_fireflies_get_transcripts',
  'mcp_fireflies_fireflies_get_user',
  'mcp_fireflies_fireflies_get_usergroups',
  'mcp_fireflies_fireflies_get_user_contacts',
  'mcp_fireflies_fireflies_search',
  'mcp_fireflies_fireflies_fetch'
]
Usage
For Agent Developers
Use the dedicated helper method:

from parrot.bots.agent import BasicAgent
# Create and configure agent
agent = BasicAgent(name="my-agent", model="gpt-4")
await agent.configure()
# Add Fireflies MCP server
tools = await agent.add_fireflies_mcp_server(
    api_key="your-fireflies-api-key"
)
Get Your Fireflies API Key
Go to Fireflies.ai Settings
Navigate to Developer Settings
Copy your API key
See detailed guide →
Available Fireflies Tools
After successful connection, the following 8 tools are available:

fireflies_get_transcript - Get transcript for a specific meeting
fireflies_get_summary - Get AI-generated summary of a meeting
fireflies_get_transcripts - List all transcripts
fireflies_get_user - Get current user information
fireflies_get_usergroups - Get user groups
fireflies_get_user_contacts - Get user contacts
fireflies_search - Search through meetings and transcripts
fireflies_fetch - Fetch specific meeting data
Prerequisites
IMPORTANT

Node.js and npm must be installed on your system for npx to work. The mcp-remote package is automatically installed by npx on first run.

Key Learnings
Not all MCP servers use HTTP: Some MCP servers require stdio transport with command-line tools
Always check official documentation: The Fireflies docs clearly showed the npx mcp-remote requirement
Protocol mismatch causes 406 errors: When a server expects a different communication protocol, it returns 406 Not Acceptable
Bearer tokens can be implemented different ways: Some APIs use HTTP headers directly, others require proxy tools
