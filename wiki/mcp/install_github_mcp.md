# GitHub MCP Installation and Usage

This guide explains how to install and use the GitHub MCP server with `ai-parrot`.

## Prerequisites

- **Node.js & npm**: Required to run the MCP server.
- **GitHub Personal Access Token (PAT)**: Required for authentication.
    - Scopes needed: `repo` (all), `user` (read:user).
    - Can be created [here](https://github.com/settings/tokens).

## Installation

We use the `@modelcontextprotocol/server-github` package.

To install it locally (without modifying `package.json`):

```bash
make install-github
```

This runs: `npm install @modelcontextprotocol/server-github`

## Usage

You can use the GitHub MCP server in two modes:

1.  **Local (Stdio)**: Uses `npx` to run the server process locally.
2.  **Remote (Insiders)**: Connects to the GitHub Copilot MCP HTTP endpoint.

### 1. Local Mode (Stdio)

This mode runs the server as a subprocess. It requires `npx` to be available in your PATH.

**Environment Setup:**
Set your PAT in the environment variables:
```bash
export GITHUB_PERSONAL_ACCESS_TOKEN=ghp_...
```

**Code Example:**
```python
# In your agent setup (e.g., in a bot wrapper or handler)

# Option A: Using environment variable (Recommended)
await agent.tool_manager.add_github_mcp()

# Option B: Passing token explicitly
await agent.tool_manager.add_github_mcp(
    personal_access_token="ghp_..."
)
```

### 2. Remote Mode (GitHub Insiders)

This mode connects to the remote MCP server hosted by GitHub Copilot. This is useful for "insiders" builds or when local node execution is restricted.

**Code Example:**
```python
# Basic usage (defaults: readonly=True, toolsets="repos,issues")
await agent.tool_manager.add_github_remote_mcp(
    personal_access_token="ghp_..."
)

# Advanced usage
await agent.tool_manager.add_github_remote_mcp(
    personal_access_token="ghp_...",
    toolsets=["repos", "issues", "code"],  # Enable code search
    readonly=False,                        # Allow write operations (e.g. creating issues)
    lockdown=False                         # Disable lockdown mode if needed
)
```

### Configuration Options for Remote Mode

- **toolsets**: List of activated toolsets. Common values: `repos`, `issues`, `code`, `users`.
- **readonly**: If `True` (default), prevents modifying data.
- **lockdown**: If `True`, restricts access further (server-side implementation specific).
