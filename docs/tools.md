# AI-Parrot Tools Documentation

Complete reference guide for all available tools in the AI-parrot library.

---

## Core Mathematical Tools

### MathTool

**Description:** Performs basic arithmetic operations including addition, subtraction, multiplication, division, and square root calculations.

**Usage:**
```python
from parrot.tools.math import MathTool

tool = MathTool()
result = await tool.execute(
    a=10.0,
    operation="add",
    b=5.0
)
```

**Example:**
```python
# Addition
result = await math_tool.execute(a=25, operation="add", b=15)
# Returns: {"operation": "add", "operands": [25, 15], "result": 40, "expression": "25 + 15 = 40"}

# Square root
result = await math_tool.execute(a=144, operation="sqrt")
# Returns: {"operation": "sqrt", "operands": [144], "result": 12.0, "expression": "sqrt(144) = 12.0"}

# Division
result = await math_tool.execute(a=100, operation="divide", b=4)
# Returns: {"operation": "divide", "operands": [100, 4], "result": 25.0, "expression": "100 / 4 = 25.0"}
```

**Supported Operations:**
- `add`, `addition`, `+`, `plus`, `sum`
- `subtract`, `subtraction`, `-`, `minus`, `difference`
- `multiply`, `multiplication`, `*`, `times`, `×`, `product`
- `divide`, `division`, `/`, `÷`, `quotient`
- `sqrt`, `square_root`, `square root`

---

## Weather & Environment Tools

### OpenWeatherTool

**Description:** Retrieves current weather conditions and forecasts for any location using the OpenWeatherMap API. Supports multiple temperature units and provides comprehensive weather data.

**Usage:**
```python
from parrot.tools.openweather import OpenWeatherTool

tool = OpenWeatherTool(
    api_key="your_api_key",
    default_units='imperial',
    default_country='us',
    timeout=10
)

weather = await tool.execute(
    latitude=40.7128,
    longitude=-74.0060,
    request_type='weather',
    units='imperial',
    country='us'
)
```

**Example:**
```python
# Get current weather for New York City
weather_tool = OpenWeatherTool(api_key="your_key")

current_weather = await weather_tool.execute(
    latitude=40.7128,
    longitude=-74.0060,
    request_type='weather',
    units='imperial'
)

# Get 5-day forecast
forecast = await weather_tool.execute(
    latitude=40.7128,
    longitude=-74.0060,
    request_type='forecast',
    units='metric',
    forecast_days=5
)
```

**Parameters:**
- `latitude`: Latitude coordinate (-90.0 to 90.0)
- `longitude`: Longitude coordinate (-180.0 to 180.0)
- `request_type`: 'weather' (current) or 'forecast' (future predictions)
- `units`: 'metric' (Celsius), 'imperial' (Fahrenheit), or 'standard' (Kelvin)
- `country`: Two-letter ISO 3166 country code (default: 'us')
- `forecast_days`: Number of days for forecast (1-16, only for 'forecast' type)

---

## Database Tools

### DatabaseTool

**Description:** Unified database tool that handles the complete database interaction pipeline including schema discovery, query generation from natural language, query validation, and safe execution across multiple database types.

**Usage:**
```python
from parrot.tools.db import DatabaseTool

tool = DatabaseTool(
    knowledge_store=vector_store,
    default_connection_params={
        DatabaseFlavor.POSTGRESQL: {
            "host": "localhost",
            "port": 5432,
            "database": "mydb",
            "user": "user",
            "password": "pass"
        }
    }
)

result = await tool.execute(
    natural_language_query="Show me all users who registered in the last 30 days",
    database_flavor="postgresql",
    operation="full_pipeline"
)
```

**Example:**
```python
# Full pipeline: natural language to execution
db_tool = DatabaseTool(knowledge_store=my_vector_store)

result = await db_tool.execute(
    natural_language_query="What are the top 10 selling products by revenue?",
    database_flavor="postgresql",
    connection_params={
        "host": "localhost",
        "database": "sales_db"
    },
    operation="full_pipeline",
    max_rows=10
)

# Schema extraction only
schema_info = await db_tool.execute(
    database_flavor="postgresql",
    connection_params=connection_params,
    schema_names=["public", "analytics"],
    operation="schema_extract"
)

# Direct SQL execution
sql_result = await db_tool.execute(
    sql_query="SELECT * FROM users WHERE active = true",
    database_flavor="postgresql",
    operation="query_execute",
    max_rows=100
)
```

**Supported Operations:**
- `schema_extract`: Extract and cache table schemas
- `query_generate`: Convert natural language to SQL
- `query_validate`: Syntax and security validation
- `query_execute`: Safe query execution
- `full_pipeline`: Complete end-to-end workflow

**Supported Databases:**
- PostgreSQL
- MySQL
- SQLite
- Microsoft SQL Server
- Oracle

---

## Web Scraping & Browser Automation

### WebScrapingTool

**Description:** Advanced web scraping and browser automation tool with support for both Selenium and Playwright. Provides step-by-step navigation, flexible content extraction, and comprehensive browser control.

**Usage:**
```python
from parrot.tools.scraping import WebScrapingTool

tool = WebScrapingTool(
    browser='chrome',
    driver_type='selenium',
    headless=True,
    mobile=False,
    default_timeout=10
)

result = await tool.execute(
    steps=[
        {"action": "navigate", "url": "https://example.com"},
        {"action": "click", "selector": "#login-button"},
        {"action": "fill", "selector": "#username", "value": "user@example.com"},
        {"action": "wait", "condition": "element_visible", "selector": ".dashboard"}
    ],
    selectors=[
        {"name": "title", "selector": "h1.page-title", "extract_type": "text"},
        {"name": "prices", "selector": ".product-price", "extract_type": "text", "multiple": True}
    ]
)
```

**Example:**
```python
# Basic page scraping
scraper = WebScrapingTool(browser='chrome', headless=True)

result = await scraper.execute(
    steps=[
        {
            "action": "navigate",
            "url": "https://news.ycombinator.com",
            "description": "Go to Hacker News"
        },
        {
            "action": "wait",
            "condition": "element_visible",
            "selector": ".titleline",
            "timeout": 5
        }
    ],
    selectors=[
        {
            "name": "story_titles",
            "selector": ".titleline > a",
            "extract_type": "text",
            "multiple": True
        },
        {
            "name": "story_links",
            "selector": ".titleline > a",
            "extract_type": "attribute",
            "attribute": "href",
            "multiple": True
        }
    ]
)

# Form interaction with authentication
login_result = await scraper.execute(
    steps=[
        {"action": "navigate", "url": "https://example.com/login"},
        {"action": "fill", "selector": "#email", "value": "user@example.com"},
        {"action": "fill", "selector": "#password", "value": "secret"},
        {"action": "click", "selector": "button[type='submit']"},
        {"action": "wait", "condition": "url_contains", "value": "/dashboard"}
    ]
)

# Mobile device emulation
mobile_scraper = WebScrapingTool(
    browser='chrome',
    mobile=True,
    mobile_device='iPhone 14 Pro Max'
)
```

**Supported Actions:**
- **Navigation:** `navigate`, `back`, `refresh`
- **Interaction:** `click`, `fill`, `press_key`, `scroll`
- **Data Extraction:** `get_text`, `get_html`, `get_cookies`, `screenshot`
- **Authentication:** `authenticate`, `set_cookies`
- **File Operations:** `upload_file`, `wait_for_download`
- **Waiting:** `wait`, `await_human`, `await_keypress`, `await_browser_event`
- **Advanced:** `evaluate` (JavaScript), `loop` (iterations)

**Supported Browsers:**
- Chrome (default)
- Firefox
- Edge
- Safari
- Undetected Chrome (anti-detection)

---

## Agent Tools

### AgentTool

**Description:** Wraps any BasicAgent or AbstractBot as a tool, allowing agents to be used as tools by other agents in a multi-agent orchestration system.

**Usage:**
```python
from parrot.tools.agent import AgentTool
from parrot.bots.agent import BasicAgent

# Create a specialized agent
research_agent = BasicAgent(
    name="ResearchAgent",
    role="Research Specialist",
    goal="Find and synthesize information"
)

# Wrap it as a tool
research_tool = AgentTool(
    agent=research_agent,
    name="research_tool",
    description="Use this tool to perform in-depth research on any topic"
)

# Use in another agent
orchestrator.register_tool(research_tool)
```

**Example:**
```python
# Create specialized agents as tools
code_agent = BasicAgent(
    name="CodeExpert",
    role="Software Engineer",
    tools=["DatabaseTool", "WebScrapingTool"]
)

writer_agent = BasicAgent(
    name="ContentWriter",
    role="Technical Writer",
    goal="Create clear documentation"
)

# Convert to tools
code_tool = AgentTool(agent=code_agent, name="coding_expert")
writer_tool = AgentTool(agent=writer_agent, name="writing_expert")

# Orchestrator uses both
orchestrator = BasicAgent(
    name="ProjectManager",
    tools=[code_tool, writer_tool]
)

result = await orchestrator.conversation(
    prompt="Build a web scraper and document how it works"
)
```

---

## Tool Management

### ToolManager

**Description:** Central registry for managing and sharing tools across agents. Handles tool registration, discovery, and schema generation for different LLM providers.

**Usage:**
```python
from parrot.tools.manager import ToolManager

# Create manager
tool_manager = ToolManager()

# Register tools
tool_manager.register_tool(MathTool())
tool_manager.register_tool(OpenWeatherTool(api_key="key"))
tool_manager.load_tool("DatabaseTool")

# Get tools for specific LLM format
openai_tools = tool_manager.get_tool_schemas(ToolFormat.OPENAI)
anthropic_tools = tool_manager.get_tool_schemas(ToolFormat.ANTHROPIC)

# Execute tool
result = await tool_manager.execute_tool(
    "MathTool",
    {"a": 10, "operation": "add", "b": 5}
)
```

**Example:**
```python
# Shared tool manager for multiple agents
shared_manager = ToolManager()

# Load common tools
shared_manager.load_tool("MathTool")
shared_manager.load_tool("OpenWeatherTool")
shared_manager.register_tool(CustomTool())

# Agent 1 uses the manager
agent1 = BasicAgent(
    name="Assistant1",
    tool_manager=shared_manager
)

# Agent 2 shares the same tools
agent2 = BasicAgent(
    name="Assistant2",
    tool_manager=shared_manager
)

# Get all available tools
all_tools = shared_manager.all_tools()
tool_names = [tool.name for tool in all_tools]
```

---

## Integration & Communication

### MCP Server Tools

**Description:** Model Context Protocol (MCP) server that exposes AI-Parrot tools via the MCP protocol, enabling integration with MCP-compatible clients.

**Usage:**
```python
from parrot.tools.server import MCPServerConfig, MCPToolAdapter

config = MCPServerConfig(
    name="ai-parrot-mcp",
    transport="stdio",  # or "http"
    port=8080,
    allowed_tools=["MathTool", "OpenWeatherTool"]
)

# Adapt tools to MCP format
adapter = MCPToolAdapter(tool=MathTool())
mcp_definition = adapter.to_mcp_tool_definition()
```

**Example:**
```python
# Start MCP server exposing tools
from parrot.tools.server import start_mcp_server

server = start_mcp_server(
    tools=[
        MathTool(),
        OpenWeatherTool(api_key="key"),
        DatabaseTool()
    ],
    config=MCPServerConfig(
        transport="http",
        host="0.0.0.0",
        port=8080
    )
)
```

---

## Custom Tool Development

### AbstractTool Base Class

**Description:** Base class for creating custom tools in AI-parrot. Provides standardized interface, schema generation, and error handling.

**Usage:**
```python
from parrot.tools.abstract import AbstractTool, ToolResult
from pydantic import BaseModel, Field

class MyToolArgs(BaseModel):
    """Arguments schema for MyTool."""
    input_text: str = Field(description="Text to process")
    options: dict = Field(default={}, description="Processing options")

class MyTool(AbstractTool):
    """Custom tool implementation."""

    name = "MyTool"
    description = "Processes text with custom logic"
    args_schema = MyToolArgs

    async def _execute(self, input_text: str, options: dict = None, **kwargs) -> dict:
        """Execute tool logic."""
        result = self._process_text(input_text, options)
        return {
            "processed_text": result,
            "metadata": {"length": len(result)}
        }

    def _process_text(self, text: str, options: dict) -> str:
        # Custom processing logic
        return text.upper()
```

**Example:**
```python
# Complete custom tool with validation
from typing import Literal

class SentimentAnalyzerArgs(BaseModel):
    text: str = Field(description="Text to analyze")
    model: Literal["simple", "advanced"] = Field(
        default="simple",
        description="Analysis model to use"
    )

class SentimentAnalyzerTool(AbstractTool):
    name = "sentiment_analyzer"
    description = "Analyzes sentiment of text"
    args_schema = SentimentAnalyzerArgs

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.models = {
            "simple": self._simple_analysis,
            "advanced": self._advanced_analysis
        }

    async def _execute(self, text: str, model: str = "simple", **kwargs):
        analysis_func = self.models.get(model)
        sentiment = analysis_func(text)

        return ToolResult(
            status="success",
            result={
                "text": text,
                "sentiment": sentiment,
                "model_used": model
            },
            metadata={"text_length": len(text)}
        )

    def _simple_analysis(self, text: str) -> str:
        # Simple sentiment logic
        positive_words = ["good", "great", "excellent", "happy"]
        negative_words = ["bad", "terrible", "awful", "sad"]

        text_lower = text.lower()
        pos_count = sum(word in text_lower for word in positive_words)
        neg_count = sum(word in text_lower for word in negative_words)

        if pos_count > neg_count:
            return "positive"
        elif neg_count > pos_count:
            return "negative"
        return "neutral"

    def _advanced_analysis(self, text: str) -> str:
        # More sophisticated analysis
        return "neutral"

# Use the custom tool
sentiment_tool = SentimentAnalyzerTool()
result = await sentiment_tool.execute(
    text="This is a great day!",
    model="simple"
)
```

---

## Tool Configuration Examples

### Registering Tools with Agents

```python
from parrot.bots.agent import BasicAgent
from parrot.tools.math import MathTool
from parrot.tools.openweather import OpenWeatherTool

# Method 1: Tool instances
agent = BasicAgent(
    name="Assistant",
    tools=[
        MathTool(),
        OpenWeatherTool(api_key="key")
    ]
)

# Method 2: Tool names (auto-loaded)
agent = BasicAgent(
    name="Assistant",
    tools=["MathTool", "DatabaseTool"]
)

# Method 3: Mixed approach
agent = BasicAgent(
    name="Assistant",
    tools=[
        "MathTool",
        OpenWeatherTool(api_key="key"),
        CustomTool()
    ]
)
```

### Tool Manager Integration

```python
from parrot.tools.manager import ToolManager

# Create shared tool manager
manager = ToolManager()

# Register multiple tools
manager.register_tools([
    MathTool(),
    OpenWeatherTool(api_key="key"),
    DatabaseTool(),
    WebScrapingTool()
])

# Use with agent
agent = BasicAgent(
    name="MultiToolAgent",
    tool_manager=manager
)

# Execute tools directly
result = await manager.execute_tool(
    "OpenWeatherTool",
    {"latitude": 40.7, "longitude": -74.0}
)
```

---

## Best Practices

1. **Error Handling:** Always wrap tool execution in try-except blocks
2. **Tool Selection:** Use specific tools for specific tasks rather than general-purpose tools
3. **Resource Management:** Clean up resources (database connections, browser instances) after use
4. **API Keys:** Store API keys in environment variables, not in code
5. **Validation:** Use Pydantic schemas to validate tool arguments
6. **Async Execution:** Prefer async methods for I/O-bound operations
7. **Tool Descriptions:** Provide clear, detailed descriptions for LLM tool selection
8. **Return Types:** Use standardized `ToolResult` format for consistent responses

---

## Additional Resources

- **Tool Manager Documentation:** See `parrot/tools/manager.py`
- **Agent Integration:** See `parrot/bots/agent.py`
- **Custom Tool Development:** Extend `AbstractTool` class
- **MCP Integration:** See `parrot/tools/server.py` for protocol details

For more information on specific tools or creating custom tools, consult the source code in the `parrot/tools/` directory.
