# Your First Chatbot

> **Time**: ~10 minutes
> **Prerequisites**: AI-Parrot installed, API key configured

## What You'll Build

In this tutorial, you'll build a simple chatbot that can answer questions using an LLM. You'll learn how to create a `Chatbot` instance, configure it with a language model, and interact with it through the `ask` method. By the end, you'll have a working chatbot that can answer general knowledge questions.

Chatbots are conversational AI systems that can understand and respond to natural language queries. They're useful for customer service, information retrieval, and educational purposes. AI-Parrot's Chatbot class provides a powerful foundation for building these systems with minimal code.

## Step 1: Set Up

First, make sure you have AI-Parrot installed with at least one LLM provider. If you haven't installed it yet, follow the [Getting Started guide](../getting-started.md) to set up your environment.

For this tutorial, we'll use the Anthropic provider, but you can substitute it with any provider you have installed. The `from_database=False` parameter is important here - it tells the chatbot not to try to load its configuration from a database, which you likely haven't set up yet.

```python
import asyncio
from parrot.bots import Chatbot

async def main():
    # Create a chatbot instance
    chatbot = Chatbot(
        name="MyFirstChatbot",
        llm="anthropic",  # or "openai", "google", etc.
        from_database=False  # Don't load from database
    )
    
    # Configure the chatbot
    await chatbot.configure()
    
    return chatbot

# Run the async function
chatbot = asyncio.run(main())
```

Make sure you have your API key set in the environment variables:
- For Anthropic: `ANTHROPIC_API_KEY`
- For OpenAI: `OPENAI_API_KEY`
- For Google: `GOOGLE_API_KEY`

You can set these in your terminal session:
```bash
export ANTHROPIC_API_KEY="your-api-key-here"
```

Or in Windows PowerShell:
```powershell
$env:ANTHROPIC_API_KEY = "your-api-key-here"
```

## Step 2: Define Components

Now that we have our chatbot set up, let's define a function to interact with it. The `ask` method is the primary way to communicate with the chatbot. It sends a message to the LLM and returns the response.

The chatbot maintains conversation context automatically, meaning it remembers previous messages in the conversation. This allows for natural back-and-forth interactions.

```python
async def chat_with_bot(chatbot, question):
    """Send a question to the chatbot and get a response."""
    response = await chatbot.ask(question)
    return response.output

# Example usage
async def demo_chat():
    # Create and configure the chatbot
    chatbot = Chatbot(
        name="MyFirstChatbot",
        llm="anthropic",
        from_database=False
    )
    await chatbot.configure()
    
    # Ask a question
    question = "What is the capital of France?"
    answer = await chat_with_bot(chatbot, question)
    print(f"Question: {question}")
    print(f"Answer: {answer}")
    
    return chatbot, answer
```

The `response` object contains more than just the output text. It includes metadata about the LLM call, such as token usage, response time, and other debugging information that can be useful for monitoring and optimization.

## Step 3: Run It

Let's put everything together and run our chatbot. We'll create a more comprehensive example that demonstrates multiple questions and shows how the chatbot maintains context:

```python
import asyncio
from parrot.bots import Chatbot

async def chat_with_bot(chatbot, question):
    """Send a question to the chatbot and get a response."""
    response = await chatbot.ask(question)
    return response.output

async def main():
    # Create and configure the chatbot
    chatbot = Chatbot(
        name="MyFirstChatbot",
        llm="anthropic",
        from_database=False
    )
    await chatbot.configure()
    
    # Have a conversation
    questions = [
        "What is the capital of France?",
        "What is the population of Paris?",
        "What are some famous landmarks in Paris?",
        "Tell me about the history of the Eiffel Tower"
    ]
    
    print("Starting conversation with chatbot...")
    print("=" * 60)
    
    for i, question in enumerate(questions, 1):
        answer = await chat_with_bot(chatbot, question)
        print(f"Q{i}: {question}")
        print(f"A{i}: {answer}")
        print("-" * 60)
        
        # Add a small delay to make the conversation feel more natural
        await asyncio.sleep(0.5)
    
    return chatbot

# Run the chatbot
if __name__ == "__main__":
    asyncio.run(main())
```

When you run this code, you should see responses from the LLM to each of your questions. Notice how the chatbot maintains context within a single conversation. For example, when you ask about the Eiffel Tower in the last question, the chatbot understands that you're referring to the landmark mentioned in the previous response.

## Advanced Features

### Customizing System Prompts

You can customize the chatbot's behavior by providing a system prompt that defines its personality or role:

```python
chatbot = Chatbot(
    name="MyFirstChatbot",
    llm="anthropic",
    system_prompt="You are a helpful assistant who answers questions with enthusiasm and provides detailed explanations.",
    from_database=False
)
```

### Handling Errors

In production applications, you should handle potential errors gracefully:

```python
async def safe_chat_with_bot(chatbot, question):
    """Send a question to the chatbot with error handling."""
    try:
        response = await chatbot.ask(question)
        return response.output
    except Exception as e:
        return f"Sorry, I encountered an error: {str(e)}"
```

## What's Next

- [Your First Agent](first-agent.md) - Learn how to create an agent that can use tools
- [Wiki: Bots & Agents](https://github.com/phenobarbital/ai-parrot/wiki/Bots-&-Agents) - Deep dive into the bot and agent architecture

## Troubleshooting

If you encounter issues:

1. **API Key Error**: Make sure your API key is set in the environment and is valid
2. **Provider Not Found**: Ensure you've installed the appropriate provider package (e.g., `pip install ai-parrot[anthropic]`)
3. **Network Issues**: Check your internet connection and firewall settings
4. **Rate Limits**: Some providers have rate limits; add delays between requests if needed

For more detailed troubleshooting, check the [Getting Started guide](../getting-started.md) and the [Wiki documentation](https://github.com/phenobarbital/ai-parrot/wiki).