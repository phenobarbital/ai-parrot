# Your First Tool

> **Time**: ~10 minutes
> **Prerequisites**: AI-Parrot installed, API key configured

## What You'll Build

A simple tool that adds two numbers together and attaches it to an agent. This tool will be available to the agent whenever it's invoked, allowing it to perform calculations without needing to call an external API.

In this tutorial, you'll learn how to:
- Define a function and mark it as a tool using the `@tool` decorator
- Attach the tool to a BasicAgent
- Run the agent and see it use your tool automatically
- Understand why `from_database=False` is important for first runs
- Configure the LLM provider explicitly (a bare install has no default)

By the end of this tutorial, you'll have a working agent that can perform calculations using your custom tool. This is the foundation for more complex tools that interact with APIs, databases, or other systems.

## Step 1: Set Up

First, create a new Python file called `my_tool.py` in a new directory. This will be your project directory where you'll build your first tool.

Create the directory and file:

```bash
mkdir my_first_tool
cd my_first_tool
touch my_tool.py
```

Now open `my_tool.py` in your editor and add the following code:

```python
import asyncio
from parrot.tools import tool
from parrot.bots import BasicAgent

@tool
def add_numbers(a: int, b: int) -> int:
    """Add two numbers together.

    This is a simple tool that takes two integers and returns their sum.
    The @tool decorator automatically:
    - Sets the tool name to the function name (`add_numbers`)
    - Extracts the description from the docstring
    - Infers the input schema from the type hints

    Args:
        a: First number
        b: Second number

    Returns:
        The sum of a and b
    """
    return a + b
```

This defines a simple tool using the `@tool` decorator. The decorator automatically:
- Sets the tool name to the function name (`add_numbers`)
- Extracts the description from the docstring
- Infers the input schema from the type hints
- Registers the tool with the agent's tool registry

The `@tool` decorator is the primary way to create tools in AI-Parrot. It's a lightweight wrapper that adds tool metadata to your function without requiring you to inherit from a base class or implement complex interfaces.

## Step 2: Define Your Agent

Now create an agent that uses this tool. Update `my_tool.py` with the complete example:

```python
import asyncio
from parrot.tools import tool
from parrot.bots import BasicAgent

@tool
def add_numbers(a: int, b: int) -> int:
    """Add two numbers together.

    This is a simple tool that takes two integers and returns their sum.
    The @tool decorator automatically:
    - Sets the tool name to the function name (`add_numbers`)
    - Extracts the description from the docstring
    - Infers the input schema from the type hints

    Args:
        a: First number
        b: Second number

    Returns:
        The sum of a and b
    """
    return a + b

async def main():
    # Create an agent with the tool
    agent = BasicAgent(
        name="CalculatorAgent",
        llm="anthropic",  # or "openai", "google", etc.
        from_database=False  # Don't load from database for this simple example
    )

    # Attach the tool to the agent
    agent.tools = [add_numbers]

    # Configure the agent
    await agent.configure()

    # Use the agent to add two numbers
    response = await agent.invoke("Add 5 and 3")
    print(f"Result: {response.output}")

if __name__ == "__main__":
    asyncio.run(main())
```

**Key points:**
- `from_database=False` is important for first runs — it prevents the agent from trying to load configuration from a database you haven't set up yet. By default, `Chatbot.__init__` (which `BasicAgent` extends) sets `from_database=True`, which tries to load the bot's configuration from a Postgres database. For a first run with nothing set up, you need to explicitly set this to `False`.
- `llm="anthropic"` (or another provider) is required — a bare install has no default provider to fall back to. The `LLMFactory.list_providers()` returns `{}` until you install at least one provider client.
- Tools are attached to the agent via the `tools` attribute. You can pass a list of tools to the constructor, or attach them after creation.

## Step 3: Run It

Run the script with your virtual environment activated:

```bash
python my_tool.py
```

You should see output like:

```
Result: 8
```

The agent received the request "Add 5 and 3", used the `add_numbers` tool to perform the calculation, and returned the result.

**What just happened?**
1. The agent was created with the `add_numbers` tool attached
2. `await agent.configure()` initialized the agent, including setting up the LLM client
3. `await agent.invoke("Add 5 and 3")` sent the request to the LLM
4. The LLM decided to use the `add_numbers` tool (because it's the most appropriate for the request)
5. The tool was executed with arguments `a=5, b=3`
6. The result `8` was returned to the LLM
7. The LLM formatted the response and returned it to you

This is the core pattern for building agents: create an agent, attach tools, and let the LLM decide when and how to use them.

## What's Next

- [Your First Agent](first-agent.md) — Learn how to create an agent with more complex behavior
- [Deploy Your Agent](deployment.md) — Learn how to serve your agent as a production HTTP service
- [Wiki: Bots & Agents](https://github.com/phenobarbital/ai-parrot/wiki/Home) — Deep dive into agents and tools
- [Wiki: Tools & RAG](https://github.com/phenobarbital/ai-parrot/wiki/Home) — Learn about tools, toolkits, and RAG pipelines
