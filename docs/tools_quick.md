# AI-Parrot Tools Quick Reference Guide

Fast lookup for all AI-parrot tools with minimal examples.

---

## 🧮 MathTool

**Purpose:** Basic arithmetic operations

```python
from parrot.tools.math import MathTool

tool = MathTool()
result = await tool.execute(a=10, operation="add", b=5)
# Returns: {"result": 15, "expression": "10 + 5 = 15"}
```

**Operations:** `add`, `subtract`, `multiply`, `divide`, `sqrt`

**Quick Examples:**
```python
await tool.execute(a=144, operation="sqrt")           # √144 = 12
await tool.execute(a=100, operation="divide", b=4)    # 100 ÷ 4 = 25
await tool.execute(a=7, operation="multiply", b=6)    # 7 × 6 = 42
```

---

## 🌦️ OpenWeatherTool

**Purpose:** Current weather and forecasts

```python
from parrot.tools.openweather import OpenWeatherTool

tool = OpenWeatherTool(api_key="YOUR_API_KEY")
weather = await tool.execute(
    latitude=40.7128,
    longitude=-74.0060,
    request_type='weather',  # or 'forecast'
    units='imperial'         # 'metric', 'standard'
)
```

**Key Parameters:**
- `latitude`, `longitude`: Coordinates
- `request_type`: `'weather'` | `'forecast'`
- `units`: `'imperial'` | `'metric'` | `'standard'`
- `forecast_days`: 1-16 (for forecasts)

**Quick Examples:**
```python
# Current weather
await tool.execute(latitude=51.5074, longitude=-0.1278, units='metric')

# 5-day forecast
await tool.execute(latitude=35.6762, longitude=139.6503,
                   request_type='forecast', forecast_days=5)
```

---

## 🗄️ DatabaseTool

**Purpose:** Natural language to SQL, query execution

```python
from parrot.tools.db import DatabaseTool, DatabaseFlavor

tool = DatabaseTool(
    default_connection_params={
        DatabaseFlavor.POSTGRESQL: {
            "host": "localhost",
            "database": "mydb",
            "user": "user",
            "password": "pass"
        }
    }
)

result = await tool.execute(
    natural_language_query="Show top 10 users by signup date",
    database_flavor="postgresql",
    operation="full_pipeline"
)
```

**Operations:**
- `schema_extract`: Get table schemas
- `query_generate`: NL → SQL
- `query_validate`: Check SQL safety
- `query_execute`: Run SQL
- `full_pipeline`: All of the above

**Quick Examples:**
```python
# Direct SQL
await tool.execute(
    sql_query="SELECT * FROM users WHERE active = true",
    operation="query_execute"
)

# Schema only
await tool.execute(
    operation="schema_extract",
    schema_names=["public"]
)

# Natural language
await tool.execute(
    natural_language_query="What products sold over $1000 last month?",
    operation="full_pipeline"
)
```

**Supported DBs:** PostgreSQL, MySQL, SQLite, SQL Server, Oracle

---

## 🌐 WebScrapingTool

**Purpose:** Browser automation and web scraping

```python
from parrot.tools.scraping import WebScrapingTool

tool = WebScrapingTool(
    browser='chrome',      # 'firefox', 'edge', 'undetected'
    headless=True,
    mobile=False
)

result = await tool.execute(
    steps=[
        {"action": "navigate", "url": "https://example.com"},
        {"action": "click", "selector": "#button"},
        {"action": "wait", "condition": "element_visible", "selector": ".result"}
    ],
    selectors=[
        {"name": "title", "selector": "h1", "extract_type": "text"}
    ]
)
```

**Common Actions:**

| Action | Example |
|--------|---------|
| Navigate | `{"action": "navigate", "url": "https://..."}` |
| Click | `{"action": "click", "selector": "#btn"}` |
| Fill Form | `{"action": "fill", "selector": "#email", "value": "user@example.com"}` |
| Wait | `{"action": "wait", "condition": "element_visible", "selector": ".content"}` |
| Scroll | `{"action": "scroll", "direction": "down", "amount": 500}` |
| Screenshot | `{"action": "screenshot", "filename": "page.png"}` |
| Get Text | `{"action": "get_text", "selector": "p"}` |
| Get HTML | `{"action": "get_html"}` |

**Selector Extraction:**

```python
selectors=[
    # Single text element
    {"name": "title", "selector": "h1.main", "extract_type": "text"},

    # Multiple elements
    {"name": "prices", "selector": ".price", "extract_type": "text", "multiple": True},

    # Attribute
    {"name": "links", "selector": "a", "extract_type": "attribute",
     "attribute": "href", "multiple": True}
]
```

**Quick Examples:**
```python
# Simple scraping
await tool.execute(
    steps=[{"action": "navigate", "url": "https://news.ycombinator.com"}],
    selectors=[{"name": "titles", "selector": ".titleline", "multiple": True}]
)

# Form login
await tool.execute(
    steps=[
        {"action": "navigate", "url": "https://site.com/login"},
        {"action": "fill", "selector": "#username", "value": "user"},
        {"action": "fill", "selector": "#password", "value": "pass"},
        {"action": "click", "selector": "button[type='submit']"}
    ]
)

# Mobile scraping
mobile_tool = WebScrapingTool(mobile=True, mobile_device='iPhone 14')
```

---

## 🤖 AgentTool

**Purpose:** Use agents as tools in multi-agent systems

```python
from parrot.tools.agent import AgentTool
from parrot.bots.agent import BasicAgent

# Create specialized agent
specialist = BasicAgent(
    name="DataAnalyst",
    role="Data Analysis Expert",
    tools=["MathTool", "DatabaseTool"]
)

# Wrap as tool
agent_tool = AgentTool(
    agent=specialist,
    name="data_analyst",
    description="Analyzes data and generates insights"
)

# Use in orchestrator
orchestrator = BasicAgent(name="Manager", tools=[agent_tool])
result = await orchestrator.conversation("Analyze sales data")
```

**Quick Example:**
```python
# Multi-agent workflow
researcher = BasicAgent(name="Researcher", tools=["WebScrapingTool"])
writer = BasicAgent(name="Writer")

research_tool = AgentTool(agent=researcher, name="research")
writer_tool = AgentTool(agent=writer, name="writer")

manager = BasicAgent(name="PM", tools=[research_tool, writer_tool])
```

---

## 🔧 ToolManager

**Purpose:** Centralized tool registry and management

```python
from parrot.tools.manager import ToolManager, ToolFormat

manager = ToolManager()

# Register tools
manager.register_tool(MathTool())
manager.load_tool("DatabaseTool")  # Load by name
manager.register_tools([tool1, tool2, tool3])

# Get schemas for LLM
openai_format = manager.get_tool_schemas(ToolFormat.OPENAI)
anthropic_format = manager.get_tool_schemas(ToolFormat.ANTHROPIC)

# Execute tool
result = await manager.execute_tool("MathTool", {"a": 5, "operation": "sqrt"})

# List all tools
all_tools = manager.all_tools()
```

**Quick Examples:**
```python
# Shared manager across agents
shared = ToolManager()
shared.register_tools(["MathTool", "OpenWeatherTool", DatabaseTool()])

agent1 = BasicAgent(name="A1", tool_manager=shared)
agent2 = BasicAgent(name="A2", tool_manager=shared)

# Get specific tool
math_tool = manager.get_tool("MathTool")
```

---

## 🔌 MCP Server

**Purpose:** Expose tools via Model Context Protocol

```python
from parrot.tools.server import MCPServerConfig, start_mcp_server

config = MCPServerConfig(
    name="ai-parrot-mcp",
    transport="http",  # or "stdio"
    host="localhost",
    port=8080
)

server = start_mcp_server(
    tools=[MathTool(), OpenWeatherTool(api_key="key")],
    config=config
)
```

---

## 🛠️ Custom Tool Development

**Purpose:** Create your own tools

```python
from parrot.tools.abstract import AbstractTool, ToolResult
from pydantic import BaseModel, Field

# 1. Define arguments schema
class MyToolArgs(BaseModel):
    input_text: str = Field(description="Text to process")
    mode: str = Field(default="simple", description="Processing mode")

# 2. Create tool class
class MyTool(AbstractTool):
    name = "my_tool"
    description = "Does something useful"
    args_schema = MyToolArgs

    async def _execute(self, input_text: str, mode: str = "simple", **kwargs):
        result = self._process(input_text, mode)
        return {"output": result, "mode_used": mode}

    def _process(self, text: str, mode: str) -> str:
        # Your logic here
        return text.upper() if mode == "simple" else text.lower()

# 3. Use it
tool = MyTool()
result = await tool.execute(input_text="Hello", mode="simple")
```

**Minimal Template:**
```python
class QuickTool(AbstractTool):
    name = "quick_tool"
    description = "Quick tool description"

    async def _execute(self, **kwargs):
        return {"result": "success"}
```

---

## 📋 Agent Integration Patterns

### Pattern 1: Direct Tool List
```python
agent = BasicAgent(
    name="Assistant",
    tools=[MathTool(), OpenWeatherTool(api_key="key")]
)
```

### Pattern 2: Tool Names (Auto-load)
```python
agent = BasicAgent(
    name="Assistant",
    tools=["MathTool", "DatabaseTool", "WebScrapingTool"]
)
```

### Pattern 3: Shared Tool Manager
```python
manager = ToolManager()
manager.register_tools(["MathTool", "OpenWeatherTool"])

agent1 = BasicAgent(name="A1", tool_manager=manager)
agent2 = BasicAgent(name="A2", tool_manager=manager)
```

### Pattern 4: Mixed Approach
```python
agent = BasicAgent(
    name="Assistant",
    tools=[
        "MathTool",                           # By name
        OpenWeatherTool(api_key="key"),       # Instance
        CustomTool(config="special")          # Custom instance
    ]
)
```

---

## ⚡ Quick Tips

### Tool Execution
```python
# Sync execution (if needed)
result = tool.execute_sync(param1="value")

# Async execution (preferred)
result = await tool.execute(param1="value")
```

### Error Handling
```python
try:
    result = await tool.execute(param="value")
    if result.get("status") == "success":
        data = result.get("result")
except Exception as e:
    logger.error(f"Tool execution failed: {e}")
```

### Tool Schema
```python
# Get tool JSON schema
schema = tool.get_tool_schema()

# Get formatted for specific LLM
openai_schema = tool.get_tool_schema(format="openai")
anthropic_schema = tool.get_tool_schema(format="anthropic")
```

### Resource Cleanup
```python
# For tools with resources (browsers, DB connections)
try:
    result = await tool.execute(...)
finally:
    await tool.cleanup()  # or tool.close()
```

---

## 🎯 Common Use Cases

### Data Analysis Pipeline
```python
agent = BasicAgent(
    name="DataAnalyst",
    tools=[
        DatabaseTool(),
        MathTool(),
        "StatisticsTool"
    ]
)
```

### Web Research Bot
```python
agent = BasicAgent(
    name="Researcher",
    tools=[
        WebScrapingTool(browser='undetected'),
        "SearchTool",
        "SummaryTool"
    ]
)
```

### Multi-Agent System
```python
researcher = BasicAgent(tools=[WebScrapingTool()])
analyst = BasicAgent(tools=[DatabaseTool(), MathTool()])
writer = BasicAgent(tools=[])

orchestrator = BasicAgent(
    tools=[
        AgentTool(agent=researcher, name="research"),
        AgentTool(agent=analyst, name="analyze"),
        AgentTool(agent=writer, name="write")
    ]
)
```

### Weather Assistant
```python
agent = BasicAgent(
    name="WeatherBot",
    tools=[
        OpenWeatherTool(api_key=os.getenv("OPENWEATHER_API_KEY")),
        "LocationTool"
    ]
)
```

---

## 🔑 Environment Variables

```bash
# .env file
OPENWEATHER_API_KEY=your_api_key_here
DATABASE_URL=postgresql://user:pass@localhost:5432/db
HUGGINGFACE_TOKEN=your_hf_token
```

```python
import os
from dotenv import load_dotenv

load_dotenv()

tool = OpenWeatherTool(api_key=os.getenv("OPENWEATHER_API_KEY"))
```

---

## 📊 Tool Comparison Matrix

| Tool | Async | Requires API Key | Resource Heavy | Best For |
|------|-------|------------------|----------------|----------|
| MathTool | ✓ | ✗ | ✗ | Calculations |
| OpenWeatherTool | ✓ | ✓ | ✗ | Weather data |
| DatabaseTool | ✓ | ✗ | ✓ | SQL queries |
| WebScrapingTool | ✓ | ✗ | ✓✓ | Web automation |
| AgentTool | ✓ | ✗ | ✓ | Multi-agent |
| ToolManager | ✓ | ✗ | ✗ | Tool organization |

**Legend:**
- ✓ = Supported
- ✗ = Not required
- ✓✓ = Very resource-intensive (browsers, memory)

---

## 🚀 Performance Tips

1. **Reuse tool instances** - Don't recreate tools for each call
2. **Use headless browsers** - Set `headless=True` for WebScrapingTool
3. **Limit database connections** - Use connection pooling
4. **Cache API results** - Especially for weather/search tools
5. **Async execution** - Always use `await tool.execute()` for I/O
6. **Clean up resources** - Close browsers and DB connections

```python
# Good: Reuse instance
tool = WebScrapingTool()
for url in urls:
    await tool.execute(steps=[{"action": "navigate", "url": url}])
await tool.cleanup()

# Bad: Recreate each time
for url in urls:
    tool = WebScrapingTool()  # ❌ Inefficient
    await tool.execute(steps=[{"action": "navigate", "url": url}])
```

---

## 📚 Further Reading

- **Full Documentation:** See detailed tool documentation
- **Source Code:** `parrot/tools/` directory
- **Examples:** `examples/` directory in repository
- **Custom Tools:** Extend `AbstractTool` class
- **Agent Integration:** See `parrot/bots/agent.py`
