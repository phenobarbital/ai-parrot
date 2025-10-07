# 🦜 AI-Parrot

**A unified Python library for building intelligent agents, chatbots, and LLM-powered applications**

AI-Parrot simplifies working with Large Language Models by providing a cohesive framework for creating conversational agents, managing tools, implementing RAG systems, and orchestrating complex AI workflows—all without the bloat of traditional frameworks.

## ✨ Key Features

### 🤖 Multi-Provider LLM Support
Connect seamlessly to multiple AI providers through a unified interface:
- **OpenAI** (GPT-4, GPT-3.5)
- **Anthropic Claude** (Claude 3.5 Sonnet, Opus)
- **Google GenAI** (Gemini models)
- **Groq** (Fast inference)

### 🛠️ Intelligent Agent System
Build sophisticated agents with built-in tool support and orchestration:
- **Tool Manager**: Share tools across multiple agents
- **Agent Registry**: Decorator-based agent creation and registration
- **Python Tool Calling**: Native support for calling Python functions as tools
- **Complex Toolkits**: Compose multiple tools into reusable toolkits

### 💬 Chatbot Creation
Create production-ready chatbots with minimal code:
- Conversational context management
- Multi-turn dialogue support
- Streaming responses
- Custom personality and behavior configuration

### 🗄️ Knowledge Base & RAG
Implement Retrieval-Augmented Generation with enterprise-grade components:
- **PgVector Integration**: PostgreSQL-based vector storage for semantic search
- **Document Loaders**: Transform any document format into AI-ready context
- **Open-Source Embeddings**: Hugging Face Transformers integration
- **Structured Outputs**: Type-safe responses from your LLMs

### 🌐 API & Server Capabilities
Deploy your AI applications with ease:
- **Bot Manager**: Centralized management for multiple bot instances
- **REST API**: Expose your agents and chatbots via HTTP endpoints
- **MCP Server**: Model Context Protocol support for standardized agent communication

### ⏰ Task Scheduling
Orchestrate agent actions over time:
- Schedule periodic agent tasks
- Trigger-based automation
- Asynchronous execution support
- Task dependency management

## 🚀 Quick Start

### Installation

```bash
pip install ai-parrot
```

### Create Your First Chatbot

```python
from ai_parrot import ChatBot, OpenAIClient

# Initialize LLM client
client = OpenAIClient(api_key="your-api-key")

# Create a chatbot
bot = ChatBot(
    name="assistant",
    client=client,
    system_prompt="You are a helpful AI assistant."
)

# Have a conversation
response = bot.chat("What's the weather like today?")
print(response)
```

### Build an Agent with Tools

```python
from ai_parrot import Agent, tool
from ai_parrot.registry import agent_registry

@tool
def calculate_sum(a: int, b: int) -> int:
    """Add two numbers together."""
    return a + b

@tool
def get_current_time() -> str:
    """Get the current time."""
    from datetime import datetime
    return datetime.now().strftime("%H:%M:%S")

# Register an agent with tools
@agent_registry.register("math_agent")
class MathAgent(Agent):
    def __init__(self):
        super().__init__(
            name="Math Helper",
            tools=[calculate_sum, get_current_time]
        )

# Use the agent
agent = agent_registry.get("math_agent")
result = agent.run("What's 42 plus 58? Also, what time is it?")
```

### Implement RAG with Vector Store

```python
from ai_parrot import RAGChatBot, PgVectorStore
from ai_parrot.loaders import PDFLoader, TextLoader

# Initialize vector store
vector_store = PgVectorStore(
    connection_string="postgresql://user:pass@localhost/db"
)

# Load and index documents
loader = PDFLoader()
documents = loader.load("./docs/manual.pdf")
vector_store.add_documents(documents)

# Create RAG-enabled chatbot
rag_bot = RAGChatBot(
    client=client,
    vector_store=vector_store,
    top_k=5
)

# Query with context
response = rag_bot.chat("How do I configure the settings?")
```

### Expose via API

```python
from ai_parrot import BotManager, create_api

# Create bot manager
manager = BotManager()
manager.register_bot("assistant", bot)
manager.register_agent("math_helper", agent)

# Create and run API server
app = create_api(manager)

# Run with: uvicorn main:app --reload
```

### Schedule Agent Tasks

```python
from ai_parrot import TaskScheduler

scheduler = TaskScheduler()

# Schedule a daily summary
@scheduler.schedule(cron="0 9 * * *")  # Every day at 9 AM
async def daily_summary():
    summary = await agent.run("Generate a summary of yesterday's activities")
    send_email(summary)

# Run the scheduler
scheduler.start()
```

## 🏗️ Architecture

AI-Parrot is designed with modularity and extensibility in mind:

```
┌─────────────────────────────────────────┐
│          Application Layer              │
│  (Chatbots, Agents, Custom Logic)       │
└──────────────┬──────────────────────────┘
               │
┌──────────────▼──────────────────────────┐
│         AI-Parrot Core                  │
│  • Agent Registry  • Tool Manager       │
│  • Bot Manager    • Task Scheduler      │
└──────────────┬──────────────────────────┘
               │
┌──────────────▼──────────────────────────┐
│      Provider Integrations              │
│  • OpenAI    • Claude    • Gemini       │
│  • Groq      • Hugging Face             │
└──────────────┬──────────────────────────┘
               │
┌──────────────▼──────────────────────────┐
│      Storage & Infrastructure           │
│  • PgVector  • Document Loaders         │
│  • MCP Server • API Layer               │
└─────────────────────────────────────────┘
```

## 🎯 Use Cases

- **Customer Support Bots**: Build intelligent support agents with knowledge base integration
- **Research Assistants**: Create agents that can search, analyze, and synthesize information
- **Automation Workflows**: Schedule and orchestrate AI-powered tasks
- **Internal Tools**: Expose LLM capabilities through APIs for your team
- **Multi-Agent Systems**: Coordinate multiple specialized agents working together

## 🗺️ Roadmap

- ✅ **Langchain Independence**: Removed heavyweight dependencies
- 🚧 **Complex Toolkits**: Advanced tool composition and chaining
- 🚧 **Model Interoperability**: Seamless LLM + Hugging Face model integration
- 📋 **Non-LLM Models**: Support for classification, NER, and other ML models
- 📋 **MCP Full Integration**: Complete Model Context Protocol implementation
- 📋 **Graph-Based RAG**: Knowledge graphs with ArangoDB for advanced reasoning

## 🤝 Contributing

Contributions are welcome! Whether it's bug fixes, new features, or documentation improvements, we appreciate your help in making AI-Parrot better.

## 📄 License

MIT License.

## 📚 Documentation

For detailed documentation, examples, and API reference, see the examples/ folder.

## 💬 Community & Support

- **Issues**: [GitHub Issues](your-github-repo/issues)
- **Discussions**: [GitHub Discussions](your-github-repo/discussions)

---

Built with ❤️ for developers who want powerful AI tools without the complexity.
