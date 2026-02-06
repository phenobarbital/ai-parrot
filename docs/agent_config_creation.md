# Agent Configuration via `agents.yaml`

The AI-Parrot `AgentRegistry` allows you to define and manage agents declaratively using a YAML configuration file. This approach is preferred for static agent definitions, enabling easy modification of models, tools, and behaviors without changing code.

## File Location

The configuration file is located at:
`agents/agents.yaml` (relative to your project root).

## Basic Structure

The file expects a top-level `agents` key containing a list of agent definitions.

```yaml
agents:
  - name: "MyAgent"
    class_name: "BasicAgent"
    module: "parrot.bots.agent"
    enabled: true
    # ... further configuration
```

## Configuration Reference

### Core Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | Yes | Unique identifier for the agent. Used to retrieve instances. |
| `class_name` | string | Yes | The class name of the bot (e.g., `BasicAgent`, `Chatbot`). |
| `module` | string | Yes | The python module path where the class is defined. |
| `enabled` | boolean | No | Defaults to `true`. Set to `false` to disable loading. |
| `singleton` | boolean | No | If `true`, only one instance of this bot is created. |
| `at_startup` | boolean | No | If `true`, the bot is instantiated immediately when the registry loads. |

### Model Configuration

You can define the LLM in two ways:

**1. Simple String**
Format: `client:model_name`

```yaml
model: "openai:gpt-4o"
```

**2. Detailed Dictionary**

```yaml
model:
  client: "anthropic"
  model: "claude-3-5-sonnet-20240620"
  temperature: 0.7  # Optional parameters passed to config
```

### System Prompt

Directly define the system instructions for the agent.

```yaml
system_prompt: |
  You are a helpful coding assistant.
  Always answer in Python.
```

### Tools

List of tool names (strings) available in the `ToolManager`.

```yaml
tools:
  - "google_search"
  - "calculator"
```

### Toolkits

List of toolkit names to register.

```yaml
toolkits:
  - "data_analysis_toolkit"
```

### MCP Servers (Model Context Protocol)

Connect to MCP servers to dynamically load tools.

```yaml
mcp_servers:
  - name: "filesystem"
    transport: "stdio"
    command: "npx"
    args: ["-y", "@modelcontextprotocol/server-filesystem", "/home/user/allowed_dir"]
  
  - name: "weather_service"
    transport: "sse"
    url: "http://localhost:8080/sse"
```

**Attributes:**
- `name`: Identifier for the server.
- `transport`: `stdio` (default) or `sse` (HTTP).
- `command`: Executable to run (for `stdio`).
- `args`: List of arguments for the command.
- `url`: URL endpoint (for `sse`).
- `env`: Dictionary of environment variables.

### Vector Store (Memory)

Configure vector memory for the agent.

```yaml
vector_store:
  vector_store: "pgvector"  # or 'chroma', 'qdrant', etc.
  collection_name: "agent_memory"
  dimension: 1536
  embedding_model: "openai"
```

### Additional Configuration (`config`)

Any extra key-value pairs in the `config` block are passed directly to the Agent's `__init__` method as keyword arguments.

```yaml
config:
  verbose: true
  max_history: 10
  user_id: "default_user"
```

## Complete Example

```yaml
agents:
  - name: "ResearchBot"
    class_name: "BasicAgent"
    module: "parrot.bots.agent"
    enabled: true
    description: "An agent that researches topics using Google and MCP."
    
    # Model Setup
    model:
      client: "openai"
      model: "gpt-4-turbo"
      
    # Behavior
    system_prompt: |
      You are a senior researcher.
      Use Google Search for latest info and Filesystem to save reports.
      
    # Capabilities
    tools:
      - "google_search"
      
    # MCP Integration
    mcp_servers:
      - name: "filesystem"
        command: "npx"
        args: ["-y", "@modelcontextprotocol/server-filesystem", "./research_reports"]
        
    # specific arguments for BasicAgent
    config:
      speech_context: "Formal"
      report_template: "research_layout.html"
```
