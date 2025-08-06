"""
Usage examples for TransformersClient in ai-parrot framework.
Demonstrates various micro-LLM integration patterns.
"""
import asyncio
import logging
from pathlib import Path
from typing import List, Dict, Any

from parrot.clients.hf import TransformersClient, TransformersModel
from parrot.bots.chatbot import Chatbot
from parrot.models import StructuredOutputConfig, OutputFormat
from parrot.memory import InMemoryConversation

# Configure logging
logging.basicConfig(level=logging.INFO)


# Example 1: Basic usage with different models
async def basic_usage_examples():
    """Demonstrate basic usage with different transformer models."""

    print("=== Basic TransformersClient Usage ===\n")

    # Example with Qwen 3B model
    print("1. Using Qwen 3B model:")
    async with TransformersClient(model=TransformersModel.QWEN_1_5B) as client:
        response = await client.ask(
            prompt="Explain quantum computing in simple terms",
            max_tokens=200,
            temperature=0.7
        )
        print(f"Response: {response.response}")
        print(f"Model: {response.model}")
        print(f"Usage: {response.usage}\n")

    # Example with Gemma 2B model
    print("2. Using Gemma 2B model:")
    async with TransformersClient(model=TransformersModel.GEMMA_3_1B) as client:
        response = await client.ask(
            prompt="Eiffel tower is located in",
            max_tokens=150,
            temperature=0.3
        )
        print(f"Response: {response.output}")
        print(f"Generation time: {response.response_time:.2f}s\n")

    # Example with DialoGPT for conversation
    print("3. Using DialoGPT for conversation:")
    async with TransformersClient(model=TransformersModel.DIALOPT_SMALL) as client:
        # Simulate a conversation
        conversation_turns = [
            "Hello! How are you today?",
            "What's your favorite programming language?",
            "Can you help me with a Python problem?"
        ]

        for turn in conversation_turns:
            response = await client.ask(
                prompt=turn,
                max_tokens=100,
                temperature=0.8
            )
            print(f"User: {turn}")
            print(f"Bot: {response.output}\n")


# Example 2: Integration with Chatbot class
async def chatbot_integration_example():
    """Demonstrate integration with the Chatbot class."""

    print("=== Chatbot Integration ===\n")

    # Create a chatbot with TransformersClient
    chatbot = Chatbot(
        name="MicroBot",
        system_prompt="You are a helpful assistant that provides concise and accurate answers.",
        llm="transformers",  # This would need to be registered in SUPPORTED_CLIENTS
        model=TransformersModel.QWEN_3B.value,
        use_tools=False,  # Disable tools for micro-LLM
        from_database=False
    )

    # Configure the chatbot
    await chatbot.configure()

    # Example conversation
    questions = [
        "What is machine learning?",
        "How do neural networks work?",
        "What are the main types of machine learning?"
    ]

    for question in questions:
        response = await chatbot.conversation(
            question=question,
            user_id="user123",
            session_id="session456"
        )
        print(f"Q: {question}")
        print(f"A: {response}\n")


# Example 3: Streaming responses
async def streaming_example():
    """Demonstrate streaming responses."""

    print("=== Streaming Example ===\n")

    async with TransformersClient(model=TransformersModel.PHI_3_MINI) as client:
        print("Streaming response for: 'Tell me a short story about AI'")
        print("Response: ", end="", flush=True)

        async for chunk in client.ask_stream(
            prompt="Tell me a short story about AI and humans working together",
            max_tokens=300,
            temperature=0.8
        ):
            print(chunk, end="", flush=True)
        print("\n")

# Example 4: Memory and conversation handling
async def memory_conversation_example():
    """Demonstrate conversation memory handling."""

    print("=== Memory and Conversation Handling ===\n")

    # Create a client with memory
    memory = InMemoryConversation()

    async with TransformersClient(
        model=TransformersModel.QWEN_1_5B,
        conversation_memory=memory
    ) as client:

        user_id = "user789"
        session_id = "session123"

        # Simulate a multi-turn conversation
        turns = [
            ("What is your name?", "I am an AI assistant powered by a micro-LLM."),
            ("What can you help me with?", None),  # Let the model respond
            ("Can you write code?", None),
            ("Show me a simple Python function", None)
        ]

        for user_msg, expected_response in turns:
            response = await client.ask(
                prompt=user_msg,
                user_id=user_id,
                session_id=session_id,
                max_tokens=150
            )

            print(f"User: {user_msg}")
            print(f"Assistant: {response.content}\n")

if __name__ == "__main__":
    # Run the examples
    asyncio.run(basic_usage_examples())
    # asyncio.run(chatbot_integration_example())
    # asyncio.run(streaming_example())
