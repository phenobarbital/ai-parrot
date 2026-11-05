# Your First Agent

> **Time**: ~10 minutes
> **Prerequisites**: AI-Parrot installed, API key configured

## What You'll Build

In this tutorial, you'll build a simple agent that can use tools to perform actions. Unlike a chatbot that only responds to queries, an agent can take actions using tools. You'll learn how to create an `Agent` instance, define custom tools, and configure the agent to use those tools. By the end, you'll have a working agent that can perform calculations using a custom calculator tool.

## Step 1: Set Up

First, make sure you have AI-Parrot installed with at least one LLM provider. If you haven't installed it yet, follow the [Getting Started guide](../getting-started.md) to set up your environment.

We'll create a simple calculator tool that our agent can use. Let's start by defining the tool:

```python
import asyncio
from parrot.bots import Agent
from parrot.tools import tool

# Define a simple calculator tool
@tool
def calculator(operation: str, a: float, b: float) -> float:
    """
    Perform basic mathematical operations.
    
    Args:
        operation: The operation to perform ("add", "subtract", "multiply", "divide")
        a: First number
        b: Second number
        
    Returns:
        The result of the operation
    """
    if operation == "add":
        return a + b
    elif operation == "subtract":
        return a - b
    elif operation == "multiply":
        return a * b
    elif operation == "divide":
        if b == 0:
            raise ValueError("Cannot divide by zero")
        return a / b
    else:
        raise ValueError(f"Unsupported operation: {operation}")

async def main():
    # Create an agent with the calculator tool
    agent = Agent(
        name="MyFirstAgent",
        llm="anthropic",  # or "openai", "google", etc.
        tools=[calculator],  # Pass our tool to the agent
        from_database=False  # Don't load from database
    )
    
    # Configure the agent
    await agent.configure()
    
    return agent

# Run the async function
agent = asyncio.run(main())
```

## Step 2: Define Components

Now that we have our agent with a tool, let's define a function to interact with it. The agent can use tools automatically when it determines they're needed to answer a question:

```python
async def ask_agent(agent, question):
    """Send a question to the agent and get a response."""
    response = await agent.invoke(question)
    return response.output

# Example usage
async def demo_agent():
    # Create and configure the agent
    agent = Agent(
        name="MyFirstAgent",
        llm="anthropic",
        tools=[calculator],
        from_database=False
    )
    await agent.configure()
    
    # Ask a question that requires the calculator tool
    question = "What is 15 multiplied by 4?"
    answer = await ask_agent(agent, question)
    print(f"Question: {question}")
    print(f"Answer: {answer}")
    
    return agent, answer
```

## Step 3: Run It

Let's put everything together and run our agent:

```python
import asyncio
from parrot.bots import Agent
from parrot.tools import tool

# Define a simple calculator tool
@tool
def calculator(operation: str, a: float, b: float) -> float:
    """
    Perform basic mathematical operations.
    
    Args:
        operation: The operation to perform ("add", "subtract", "multiply", "divide")
        a: First number
        b: Second number
        
    Returns:
        The result of the operation
    """
    if operation == "add":
        return a + b
    elif operation == "subtract":
        return a - b
    elif operation == "multiply":
        return a * b
    elif operation == "divide":
        if b == 0:
            raise ValueError("Cannot divide by zero")
        return a / b
    else:
        raise ValueError(f"Unsupported operation: {operation}")

async def ask_agent(agent, question):
    """Send a question to the agent and get a response."""
    response = await agent.invoke(question)
    return response.output

async def main():
    # Create and configure the agent
    agent = Agent(
        name="MyFirstAgent",
        llm="anthropic",
        tools=[calculator],
        from_database=False
    )
    await agent.configure()
    
    # Have a conversation that requires tool usage
    questions = [
        "What is 15 multiplied by 4?",
        "What is the sum of 100 and 25?",
        "Calculate 75 divided by 5, then subtract 10 from the result."
    ]
    
    for question in questions:
        answer = await ask_agent(agent, question)
        print(f"Q: {question}")
        print(f"A: {answer}")
        print("-" * 50)
    
    return agent

# Run the agent
if __name__ == "__main__":
    asyncio.run(main())
```

When you run this code, you should see the agent automatically determine when to use the calculator tool to perform mathematical operations. The agent will call the tool, get the result, and then incorporate that information into its final response.

## What's Next

- [Your First Chatbot](first-chatbot.md) - Learn how to create a simple chatbot
- [Wiki: Tools & RAG](https://github.com/phenobarbital/ai-parrot/wiki/Tools-&-RAG) - Deep dive into tools and retrieval-augmented generation