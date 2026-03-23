# AI-Parrot Tools

**ai-parrot-tools** is a collection of tools and toolkits for [AI-Parrot](https://pypi.org/project/ai-parrot/) agents. Each tool wraps an external API or service behind a unified interface that agents can discover and invoke automatically.

## Installation

```bash
pip install ai-parrot-tools
```

Install only the extras you need:

```bash
# Individual extras
pip install ai-parrot-tools[aws]
pip install ai-parrot-tools[slack]
pip install ai-parrot-tools[jira]
pip install ai-parrot-tools[google]
pip install ai-parrot-tools[finance]
pip install ai-parrot-tools[db]

# Everything
pip install ai-parrot-tools[all]
```

## Available Extras

| Extra | Description |
|-------|-------------|
| `jira` | Jira issue tracking |
| `slack` | Slack messaging |
| `aws` | AWS services (EC2, S3, RDS, Lambda, ECS, IAM, etc.) |
| `docker` | Docker container management |
| `git` | Git repository operations |
| `analysis` | Data analysis with pandas, numpy, autoviz |
| `excel` | Excel and ODF spreadsheet support |
| `sandbox` | Sandboxed code execution via Docker |
| `codeinterpreter` | Interactive code interpreter |
| `pulumi` | Pulumi infrastructure-as-code |
| `sitesearch` | Website crawling and search |
| `office365` | Microsoft 365 / Graph API integration |
| `scraping` | Web scraping with Selenium |
| `finance` | Financial analysis (TA-Lib, yfinance, Alpaca) |
| `db` | Database querying via QuerySource |
| `flowtask` | FlowTask workflow integration |
| `google` | Google APIs (Search, Maps, Routes) |
| `arxiv` | arXiv paper search |
| `wikipedia` | Wikipedia lookups |
| `weather` | OpenWeatherMap |
| `messaging` | MQTT and IMAP messaging |

## Quick Start

```python
from parrot.bots import Agent

agent = Agent(
    name="assistant",
    instructions="You are a helpful assistant.",
    tools=["google_search", "weather", "calculator"],
)

response = await agent.chat("What's the weather in New York?")
```

Tools are registered by name. Pass a list of tool names to any AI-Parrot agent and they are loaded on demand.

## Creating Custom Tools

Use the `@tool` decorator for simple functions:

```python
from parrot.tools import tool

@tool
def get_stock_price(symbol: str) -> str:
    """Get the current stock price for a ticker symbol."""
    ...
```

Use `AbstractToolkit` for multi-tool collections:

```python
from parrot.tools import AbstractToolkit

class MyToolkit(AbstractToolkit):
    name = "my_toolkit"
    description = "A collection of related tools."

    def get_tools(self):
        ...
```

## Requirements

- Python >= 3.11
- [ai-parrot](https://pypi.org/project/ai-parrot/) >= 0.23.18

## License

MIT
