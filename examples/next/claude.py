from typing import List, TypedDict
from dataclasses import dataclass
import asyncio
from pydantic import BaseModel
from navconfig import BASE_DIR
from parrot.next.claude import ClaudeClient, ClaudeModel, BatchRequest


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
    """Example of how to use the Claude API client."""

    # Initialize client
    async with ClaudeClient() as client:

        # Register a tool
        def get_weather(location: str) -> str:
            """Get weather for a location."""
            weather_data = {
                "New York": "Sunny, 22°C",
                "London": "Rainy, 18°C",
                "Tokyo": "Cloudy, 26°C",
                "Paris": "Sunny, 20°C"
            }
            return weather_data.get(location, "Weather data not available")

        client.register_tool(
            name="get_weather",
            description="Get the current weather for a given location",
            input_schema={
                "type": "object",
                "properties": {
                    "location": {
                        "type": "string",
                        "description": "The name of the city"
                    }
                },
                "required": ["location"]
            },
            function=get_weather
        )

        # Simple question
        response = await client.ask(
            "What's the weather like in New York?",
            model=ClaudeModel.SONNET_3_5.value
        )
        print("Response text:", response.text)
        print("Model used:", response.model)
        print("Provider:", response.provider)
        print("Usage:", response.usage)
        print("Has tools:", response.has_tools)
        print("Tool calls:", [tc.name for tc in response.tool_calls])

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
        print("Response 1 text:", response1.text)
        print("Turn ID:", response1.turn_id)

        response2 = await client.ask(
            "What's my name and what do I like?",
            user_id=user_id,
            session_id=session_id
        )
        print("Response 2 text:", response2.text)
        print("Session ID:", response2.session_id)

        # Simple question
        response = await client.ask("What is the capital of France?")
        print("Response text:", response.text)
        print("Model used:", response.model)
        print("Provider:", response.provider)
        print("Usage:", response.usage)
        print("Has tools:", response.has_tools)
        print("Tool calls:", [tc.name for tc in response.tool_calls])

        # Question with file upload
        filename = BASE_DIR.joinpath("example.pdf")
        if filename.exists():
            response = await client.ask(
                "What is the main topic of this document?",
                files=[filename]
            )
            print(response)
            response = await client.ask(
                "Summarize this document",
                files=[filename],
                model=ClaudeModel.SONNET_4
            )
            print(response)

        # Structured output with memory
        summary = await client.ask(
            "Summarize our conversation as JSON with key topics",
            structured_output=SummaryOutput,
            user_id=user_id,
            session_id=session_id
        )
        print("Structured Summary:", summary)


        # List conversations for user
        sessions = await client.list_conversations(user_id)
        print("User sessions:", sessions)

        # Streaming response with memory
        async for chunk in client.ask_stream(
            "Continue our conversation about Python",
            user_id=user_id,
            session_id=session_id
        ):
            print(chunk, end="", flush=True)

        # Streaming response
        async for chunk in client.ask_stream("Tell me a story about AI"):
            print(chunk, end="", flush=True)

        class WeatherReport(BaseModel):
            location: str
            temperature: str
            condition: str
            recommendation: str

        weather_response = await client.ask(
            "Give me a weather report for Tokyo using the available tools",
            structured_output=WeatherReport,
            model=ClaudeModel.SONNET_4.value
        )
        print("Structured weather response:")
        print("- Is structured:", weather_response.is_structured)
        print("- Output type:", type(weather_response.output))
        print("- Weather data:", weather_response.output)
        print("- Tools used:", [tc.name for tc in weather_response.tool_calls])

        # # Batch requests
        # batch_requests = [
        #     BatchRequest(
        #         custom_id="req1",
        #         params={
        #             "model": ClaudeModel.SONNET_4,
        #             "max_tokens": 1000,
        #             "messages": [{"role": "user", "content": "What is 2+2?"}]
        #         }
        #     ),
        #     BatchRequest(
        #         custom_id="req2",
        #         params={
        #             "model": ClaudeModel.SONNET_4,
        #             "max_tokens": 1000,
        #             "messages": [{"role": "user", "content": "What is the meaning of life?"}]
        #         }
        #     )
        # ]

        # batch_results = await client.batch_ask(batch_requests)
        # for result in batch_results:
        #     print(f"Request {result['custom_id']}: {result['response']}")

    # Usage of Python Tool:
    async with ClaudeClient() as client:
        # Register the Python REPL tool
        repl_tool = client.register_python_tool()

        # Use the tool through Claude
        response = await client.ask(
            "Create a simple DataFrame with 3 rows and 2 columns, then show its info",
            model=ClaudeModel.SONNET_4
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
