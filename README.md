# AI-Parrot 🦜

**AI-Parrot** is a powerful, async-first Python framework for building, extending, and orchestrating AI Agents and Chatbots. Built on top of `navigator-api`, it provides a unified interface for interacting with various LLM providers, managing tools, conducting agent-to-agent (A2A) communication, and serving agents via the Model Context Protocol (MCP).

Whether you need a simple chatbot, a complex multi-agent orchestration workflow, or a robust production-ready AI service, AI-Parrot exposes the primitives to build it efficiently.

## 🚀 Key Features

*   **Unified Agent API**: Simple interface (`Chatbot`) to create agents with memory, tools, and RAG capabilities.
*   **Tool Management**: Easy-to-use decorators (`@tool`) and class-based toolkits (`AbstractToolkit`) to give your agents capabilities.
*   **Orchestration & Workflow**: `AgentCrew` for managing multi-agent workflows (Sequential, Parallel, Flow, Loop).
*   **Advanced Connectivity**:
    *   **A2A (Agent-to-Agent)**: Native protocol for agents to discover and talk to each other.
    *   **MCP (Model Context Protocol)**: Expose your agents as MCP servers or consume external MCP servers.
*   **OpenAPI Integration**: Consume any OpenAPI specification as a dynamic toolkit (`OpenAPIToolkit`).
*   **Scheduling**: Built-in task scheduling for agents using the `@schedule` decorator.
*   **Multi-Provider Support**: Switch seamlessy between OpenAI, Anthropic, Google Gemini, Groq, and more.
*   **Integrations**: Native support for exposing bots via Telegram, MS Teams, and Slack.

---

## 📦 Installation

```bash
pip install ai-parrot
```

For specific provider support (e.g., Anthropic, Google):

```bash
pip install "ai-parrot[anthropic,google]"
```

---

## ⚡ Quick Start

Create a simple weather chatbot in just a few lines of code:

```python
import asyncio
from parrot.bots import Chatbot
from parrot.tools import tool

# 1. Define a tool
@tool
def get_weather(location: str) -> str:
    """Get the current weather for a location."""
    return f"The weather in {location} is Sunny, 25°C"

async def main():
    # 2. Create the Agent
    bot = Chatbot(
        name="WeatherBot",
        llm="openai:gpt-4o",  # Provider:Model
        tools=[get_weather],
        system_prompt="You are a helpful weather assistant."
    )
    
    # 3. Configure (loads tools, connects to memory)
    await bot.configure()

    # 4. Chat!
    response = await bot.ask("What's the weather like in Madrid?")
    print(response)

if __name__ == "__main__":
    asyncio.run(main())
```

---

## 🏗️ Architecture

AI-Parrot is designed with a modular architecture enabling agents to be both consumers and providers of tools and services.

```mermaid
graph TD
    User[User / Client] --> API[AgentTalk Handlers]
    API --> Bot[Chatbot / BaseBot]
    
    subgraph "Agent Core"
        Bot --> Memory[Memory / Vector Store]
        Bot --> LLM[LLM Client (OpenAI/Anthropic/Etc)]
        Bot --> TM[Tool Manager]
    end
    
    subgraph "Tools & Capabilities"
        TM --> LocalTools[Local Tools (@tool)]
        TM --> Toolkits[Toolkits (OpenAPI/Custom)]
        TM --> MCPServer[External MCP Servers]
    end
    
    subgraph "Connectivity"
        Bot -.-> A2A[A2A Protocol (Client/Server)]
        Bot -.-> MCP[MCP Protocol (Server)]
        Bot -.-> Integrations[Telegram / MS Teams]
    end
    
    subgraph "Orchestration"
        Crew[AgentCrew] --> Bot
        Crew --> OtherBots[Other Agents]
    end
```

---

## 🧩 Core Concepts

### Agents (`Chatbot`)
The `Chatbot` class is your main entry point. It handles conversation history, RAG (Retrieval-Augmented Generation), and tool execution loop.

```python
bot = Chatbot(
    name="MyAgent",
    model="anthropic:claude-3-5-sonnet-20240620",
    enable_memory=True
)
```

### Tools

#### Functional Tools (`@tool`)
The simplest way to create a tool. The docstring and type hints are automatically used to generate the schema for the LLM.

```python
from parrot.tools import tool

@tool
def calculate_vat(amount: float, rate: float = 0.20) -> float:
    """Calculate VAT for a given amount."""
    return amount * rate
```

#### Class-Based Toolkits (`AbstractToolkit`)
Group related tools into a reusable class. All public async methods become tools.

```python
from parrot.tools import AbstractToolkit

class MathToolkit(AbstractToolkit):
    async def add(self, a: int, b: int) -> int:
        """Add two numbers."""
        return a + b
        
    async def multiply(self, a: int, b: int) -> int:
        """Multiply two numbers."""
        return a * b
```

#### OpenAPI Toolkit (`OpenAPIToolkit`)
Dynamically generate tools from any OpenAPI/Swagger specification.

```python
from parrot.tools.openapi_toolkit import OpenAPIToolkit

petstore = OpenAPIToolkit(
    spec="https://petstore.swagger.io/v2/swagger.json",
    service="petstore"
)

# Now your agent can call petstore_get_pet_by_id, etc.
bot = Chatbot(name="PetBot", tools=petstore.get_tools())
```

### Orchestration (`AgentCrew`)
orchestrate multiple agents to solve complex tasks using `AgentCrew`.

**Supported Modes:**
*   **Sequential**: Agents run one after another, passing context.
*   **Parallel**: Independent tasks run concurrently.
*   **Flow**: DAG-based execution defined by dependencies.
*   **Loop**: Iterative execution until a condition is met.

```python
from parrot.bots.orchestration import AgentCrew

crew = AgentCrew(
    name="ResearchTeam",
    agents=[researcher_agent, writer_agent]
)

# Define a Flow
# Writer waits for Researcher to finish
crew.task_flow(researcher_agent, writer_agent)

await crew.run_flow("Research the latest advancements in Quantum Computing")
```

### Scheduling (`@schedule`)
Give your agents agency to run tasks in the background.

```python
from parrot.scheduler import schedule, ScheduleType

class DailyBot(Chatbot):
    @schedule(schedule_type=ScheduleType.DAILY, hour=9, minute=0)
    async def morning_briefing(self):
        news = await self.ask("Summarize today's top tech news")
        await self.send_notification(news)
```

---

## 🔌 Connectivity & Exposure

### Agent-to-Agent (A2A) Protocol
Agents can discover and talk to each other using the A2A protocol.

**Expose an Agent:**
```python
# In your server setup (aiohttp)
from parrot.a2a import A2AServer

a2a = A2AServer(my_agent)
a2a.setup(app, url="https://my-agent.com")
```

**Consume an Agent:**
```python
from parrot.a2a import A2AClient

async with A2AClient("https://remote-agent.com") as client:
    response = await client.send_message("Hello from another agent!")
```

### Model Context Protocol (MCP)
**AI-Parrot** has first-class support for MCP.

**Consume MCP Servers:**
Give your agent access to filesystem, git, or any other MCP server.
```python
# In Chatbot config
mcp_servers = [
    MCPServerConfig(
        name="filesystem",
        command="npx",
        args=["-y", "@modelcontextprotocol/server-filesystem", "/home/user"]
    )
]
await bot.setup_mcp_servers(mcp_servers)
```

**Expose Agent as MCP Server:**
Allow Claude Desktop or other MCP clients to use your agent as a tool.
```python
# (Configuration details in documentation)
```

### Platform Integrations
Expose your bots natively to chat platforms defined in your `parrot.conf`:
*   **Telegram**
*   **Microsoft Teams**
*   **Slack**
*   **WhatsApp**

---

## 🤖 Supported LLM Clients

AI-Parrot supports a wide range of LLM providers via `parrot.clients`:

*   **OpenAI** (`openai`)
*   **Anthropic** (`anthropic`, `claude`)
*   **Google Gemini** (`google`)
*   **Groq** (`groq`)
*   **X.AI** (`grok`)
*   **HuggingFace** (`hf`)
*   **Ollama/Local** (via OpenAI compatible endpoint)

---

## 🤝 Community & Support

*   **Issues**: [GitHub Tracker](https://github.com/phenobarbital/ai-parrot/issues)
*   **Discussion**: [GitHub Discussions](https://github.com/phenobarbital/ai-parrot/discussions)
*   **Contribution**: Pull requests are welcome! Please read `CONTRIBUTING.md`.

---
*Built with ❤️ by the Navigator Team*
