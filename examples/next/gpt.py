from typing import List, TypedDict
from dataclasses import dataclass
import asyncio
from navconfig import BASE_DIR
from parrot.next.gpt import OpenAIClient


# Example usage and helper functions
@dataclass
class SummaryOutput:
    """Data structure for summary output."""
    title: str
    key_points: List[str]
    sentiment: str


class SummaryResponse(TypedDict):
    """TypedDict for structured summary response."""
    title: str
    key_points: List[str]
    sentiment: str


async def example_usage():
    """Example of how to use the OpenAI API client."""

    # Initialize client
    async with OpenAIClient() as client:

        # Register a tool
        def calculate_area(length: float, width: float) -> float:
            """Calculate area of a rectangle."""
            return length * width

        client.register_tool(
            name="calculate_area",
            description="Calculate the area of a rectangle",
            input_schema={
                "type": "object",
                "properties": {
                    "length": {"type": "number", "description": "Length of rectangle"},
                    "width": {"type": "number", "description": "Width of rectangle"}
                },
                "required": ["length", "width"]
            },
            function=calculate_area
        )

        # Start a conversation with memory
        user_id = "user123"
        session_id = "chat001"

        await client.start_conversation(user_id, session_id, "You are a helpful assistant.")

        # Multi-turn conversation with memory
        response1 = await client.ask(
            "My name is Jesus and I like Python programming",
            user_id=user_id,
            session_id=session_id
        )
        print("Response 1:", response1)

        response2 = await client.ask(
            "What's my name and what do I like?",
            user_id=user_id,
            session_id=session_id
        )
        print("Response 2:", response2)

        # Simple question
        response = await client.ask("What is the capital of France?")
        print(response)

    # Usage of Python Tool:
    async with OpenAIClient() as client:
        # Register the Python REPL tool
        repl_tool = client.register_python_tool()

        # Use the tool through OpenAI
        response = await client.ask(
            "Create a simple DataFrame with 3 rows and 2 columns, then show its info"
        )
        print(response)

        # Direct usage of the tool
        result = repl_tool.execute("""
import pandas as pd
df = pd.DataFrame({'A': [1, 2, 3], 'B': [4, 5, 6]})
df.head()
        """, debug=True)
        print("Direct execution result:", result)


if __name__ == "__main__":
    asyncio.run(example_usage())
