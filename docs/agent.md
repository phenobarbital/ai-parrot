# AgentTalk Integration Guide

## Overview

This guide covers the new **AgentTalk** HTTP handler and the migration of MCP support directly into `BasicAgent`. These changes provide a more flexible and powerful way to interact with agents via HTTP APIs.

## What's New

### 1. **AgentTalk HTTP Handler**
A new flexible HTTP endpoint for agent interactions with support for:
- Multiple output formats (JSON, HTML, Markdown, Plain Text)
- Content-Type negotiation
- Dynamic MCP server registration
- Integration with OutputMode from `AbstractBot.ask()`
- Session-based conversation management

### 2. **MCP Support in BasicAgent**
MCP (Model Context Protocol) functionality has been migrated from `MCPEnabledMixin` directly into `BasicAgent`:
- All agents now have MCP support built-in
- No need for separate `MCPAgent` class (maintained for backward compatibility)
- Simplified API for adding HTTP and local MCP servers
- Support for API key, OAuth, and bearer token authentication

## File Changes

### New Files

1. **`parrot/handlers/agent_talk.py`**
   - New HTTP handler for flexible agent interaction
   - Location: `parrot/handlers/agent_talk.py`

### Modified Files

1. **`parrot/bots/agent.py`** (BasicAgent)
   - Added MCP support methods from MCPEnabledMixin
   - Now includes: `add_mcp_server()`, `add_http_mcp_server()`, `add_local_mcp_server()`, etc.

2. **`parrot/handlers/manager.py`** (BotManager)
   - Updated `setup()` method to register AgentTalk route
   - New route: `POST /api/v1/agents/chat/`

3. **`parrot/bots/mcp.py`** (MCPAgent)
   - Simplified to just inherit from BasicAgent
   - Maintained for backward compatibility
   - Now deprecated in favor of using BasicAgent directly

## Installation & Setup

### 1. Add AgentTalk Handler

Create the new file:

```bash
# Create the handler file
touch parrot/handlers/agent_talk.py
```

Copy the `AgentTalk` class code into this file (see artifacts).

### 2. Update BasicAgent

Replace or update `parrot/bots/agent.py` with the new version that includes MCP methods.

### 3. Update BotManager

In `parrot/handlers/manager.py`, update the `setup()` method to include:

```python
from ..handlers.agent_talk import AgentTalk

# In setup() method, add:
router.add_view(
    '/api/v1/agents/chat/',
    AgentTalk
)
```

### 4. Update MCPAgent (Optional)

Simplify `parrot/bots/mcp.py` to just inherit from BasicAgent (see artifacts).

## API Endpoints

### AgentTalk Endpoint

```
POST /api/v1/agents/chat/
```

**Request Body:**
```json
{
  "agent_name": "MyAgent",
  "query": "Your question here",
  "output_format": "json",  // optional: json, html, markdown, text
  "search_type": "similarity",  // optional
  "return_sources": true,  // optional
  "use_vector_context": true,  // optional
  "mcp_servers": [  // optional: dynamic MCP server registration
    {
      "name": "weather",
      "url": "https://api.weather.com/mcp",
      "auth_type": "api_key",
      "auth_config": {
        "api_key": "your-key",
        "header_name": "X-API-Key"
      }
    }
  ],
  "format_kwargs": {  // optional: formatting options
    "include_sources": true,
    "show_metadata": true
  }
}
```

**Response (JSON format):**
```json
{
  "success": true,
  "content": "Agent response content...",
  "metadata": {
    "model": "gpt-4",
    "provider": "openai",
    "session_id": "abc123",
    "response_time": 1.23
  },
  "sources": [...],
  "tool_calls": [...]
}
```

**Response (HTML format):**
Complete HTML document ready for display in browser.

**Response (Markdown/Text format):**
Plain text response with optional source citations.

## Usage Examples

### 1. Basic JSON Request

```python
import aiohttp
import json

async def ask_agent():
    async with aiohttp.ClientSession() as session:
        url = "http://localhost:8080/api/v1/agents/chat/"

        payload = {
            "agent_name": "MyAssistant",
            "query": "What is AI?",
            "output_format": "json"
        }

        async with session.post(url, json=payload) as resp:
            result = await resp.json()
            print(json.dumps(result, indent=2))
```

### 2. HTML Output

```python
async def get_html_response():
    async with aiohttp.ClientSession() as session:
        url = "http://localhost:8080/api/v1/agents/chat/"

        payload = {
            "agent_name": "ReportAgent",
            "query": "Generate Q4 report",
            "output_format": "html"
        }

        async with session.post(url, json=payload) as resp:
            html = await resp.text()

            # Save to file
            with open("report.html", "w") as f:
                f.write(html)
```

### 3. Content Negotiation

```python
async def use_accept_header():
    async with aiohttp.ClientSession() as session:
        headers = {"Accept": "text/html"}

        payload = {
            "agent_name": "MyAgent",
            "query": "Explain quantum computing"
        }

        async with session.post(url, json=payload, headers=headers) as resp:
            html = await resp.text()
```

### 4. Dynamic MCP Server Registration

```python
async def use_mcp_servers():
    payload = {
        "agent_name": "DataAgent",
        "query": "Get weather in Madrid",
        "mcp_servers": [
            {
                "name": "weather_api",
                "url": "https://api.weather.com/mcp",
                "auth_type": "api_key",
                "auth_config": {
                    "api_key": "your-api-key",
                    "header_name": "X-API-Key"
                }
            }
        ],
        "output_format": "json"
    }

    async with session.post(url, json=payload) as resp:
        result = await resp.json()
```

## MCP Server Integration

### Using MCP with BasicAgent

```python
from parrot.bots.agent import BasicAgent

# Create agent
agent = BasicAgent(
    name="MyAgent",
    role="Multi-purpose assistant"
)

await agent.configure()

# Add HTTP MCP server (public)
await agent.add_http_mcp_server(
    name="public_tools",
    url="https://api.example.com/mcp"
)

# Add HTTP MCP server (API key auth)
await agent.add_api_key_mcp_server(
    name="weather",
    url="https://api.weather.com/mcp",
    api_key="your-api-key"
)

# Add local MCP server
await agent.add_local_mcp_server(
    name="file_tools",
    script_path="./mcp_servers/files.py"
)

# List MCP servers
servers = agent.list_mcp_servers()
print(f"Connected: {servers}")

# Get tools from specific server
tools = agent.get_mcp_server_tools("weather")
print(f"Weather tools: {tools}")
```

### MCP Server Configuration Types

#### 1. Public HTTP Server (No Auth)
```python
await agent.add_http_mcp_server(
    name="public",
    url="https://api.example.com/mcp"
)
```

#### 2. API Key Authentication
```python
await agent.add_api_key_mcp_server(
    name="service",
    url="https://api.service.com/mcp",
    api_key="your-api-key",
    header_name="X-API-Key"  # optional, default: "X-API-Key"
)
```

#### 3. OAuth Authentication
```python
await agent.add_oauth_mcp_server(
    name="google",
    url="https://mcp.googleapis.com",
    client_id="client-id",
    client_secret="client-secret",
    auth_url="https://accounts.google.com/o/oauth2/auth",
    token_url="https://oauth2.googleapis.com/token",
    scopes=["mcp.read", "mcp.write"],
    user_id="user@example.com"
)
```

#### 4. Local Stdio Server
```python
await agent.add_local_mcp_server(
    name="local_tools",
    script_path="./servers/tools.py",
    interpreter="python"
)
```

## Output Formats

### Supported Formats

1. **JSON** (`output_format: "json"`)
   - Structured response with metadata
   - Includes sources and tool calls
   - Best for programmatic access

2. **HTML** (`output_format: "html"`)
   - Complete HTML document
   - Styled and formatted
   - Ready for browser display

3. **Markdown** (`output_format: "markdown"`)
   - Plain markdown text
   - Optional source citations
   - Good for documentation

4. **Text** (`output_format: "text"`)
   - Plain text output
   - Simple and clean
   - No formatting

### Format Negotiation

AgentTalk supports format negotiation via:

1. **Explicit parameter**: `output_format` in request body
2. **Query string**: `?output_format=html`
3. **Accept header**: `Accept: text/html`

Priority: Explicit parameter > Query string > Accept header > Default (JSON)

## Webapp Generators Integration

AgentTalk can leverage webapp generators if they're registered as tools:

```python
# If agent has HTMLGenerator, PowerPointGenerator, etc. as tools
payload = {
    "agent_name": "WebDevAgent",
    "query": "Create a todo list web app",
    "output_format": "html"
}

# Agent uses HTMLGenerator tool to create the app
# Returns complete HTML application
```

## Migration Guide

### From MCPAgent to BasicAgent

**Old Code:**
```python
from parrot.bots.mcp import MCPAgent

agent = MCPAgent(name="MyAgent")
await agent.configure()
await agent.add_mcp_server(config)
```

**New Code:**
```python
from parrot.bots.agent import BasicAgent

agent = BasicAgent(name="MyAgent")
await agent.configure()
await agent.add_mcp_server(config)
```

The API is identical - just use `BasicAgent` instead of `MCPAgent`.

### From ChatHandler to AgentTalk

**Old Code:**
```python
POST /api/v1/chat/MyBot
{
  "query": "Hello"
}
```

**New Code:**
```python
POST /api/v1/agents/chat/
{
  "agent_name": "MyBot",
  "query": "Hello",
  "output_format": "json"
}
```

## Testing

### Test the AgentTalk Endpoint

```bash
# Create a test agent first via BotManager
curl -X POST http://localhost:8080/api/v1/agents/chat/ \
  -H "Content-Type: application/json" \
  -d '{
    "agent_name": "TestAgent",
    "query": "Hello, world!",
    "output_format": "json"
  }'
```

### Test with MCP Servers

```bash
curl -X POST http://localhost:8080/api/v1/agents/chat/ \
  -H "Content-Type: application/json" \
  -d '{
    "agent_name": "MyAgent",
    "query": "Get weather data",
    "mcp_servers": [
      {
        "name": "weather",
        "url": "https://api.weather.com/mcp"
      }
    ],
    "output_format": "json"
  }'
```

## Best Practices

1. **Output Format Selection**
   - Use JSON for APIs and programmatic access
   - Use HTML for browser display and reports
   - Use Markdown for documentation
   - Use Text for simple responses

2. **MCP Server Management**
   - Pre-configure commonly used MCP servers in agent factory functions
   - Use dynamic registration for user-specific or temporary servers
   - Always handle MCP connection errors gracefully
   - Use `list_mcp_servers()` to verify connections

3. **Authentication**
   - AgentTalk requires authentication (@is_authenticated)
   - Ensure proper session management
   - Use secure storage for MCP server credentials

4. **Error Handling**
   - Always check HTTP response status
   - Handle 404 (agent not found), 401 (auth required), 400 (bad request)
   - Implement retry logic for transient failures

5. **Performance**
   - Reuse agent instances when possible
   - Cache MCP server connections
   - Use connection pooling for HTTP requests

## Troubleshooting

### Agent Not Found (404)
```python
# Ensure agent is registered with BotManager
manager.add_bot(agent)

# Or use agent_registry
await agent_registry.get_instance("AgentName")
```

### MCP Server Connection Failed
```python
# Check URL and network connectivity
# Verify authentication credentials
# Check MCP server logs

# Test manually:
tools = await agent.add_http_mcp_server(
    name="test",
    url="https://api.example.com/mcp"
)
print(f"Connected tools: {tools}")
```

### Session Required (401)
```python
# Ensure user is authenticated
# Include session cookies in request
# Check @is_authenticated decorator
```

### Invalid Output Format
```python
# Use one of: json, html, markdown, text
# Default is json if not specified
```

## Future Enhancements

Potential future improvements:

1. **Streaming Responses**
   - Support for server-sent events (SSE)
   - Real-time agent responses

2. **WebSocket Support**
   - Bidirectional communication
   - Real-time updates

3. **MCP Server Discovery**
   - Automatic discovery of available MCP servers
   - Registry of public MCP servers

4. **Advanced Caching**
   - Cache agent responses
   - Cache MCP server tool definitions

5. **Rate Limiting**
   - Per-user rate limits
   - Per-agent rate limits

## Conclusion

The AgentTalk handler provides a modern, flexible way to interact with AI-Parrot agents via HTTP APIs. Combined with built-in MCP support in BasicAgent, it enables powerful integration with external tools and services.

For more examples and advanced usage, see the accompanying example files.
