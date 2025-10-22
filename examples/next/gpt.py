from typing import List, TypedDict
from dataclasses import dataclass
import asyncio
from pydantic import BaseModel
from parrot.clients.gpt import OpenAIClient, OpenAIModel
from parrot.models import VideoGenerationPrompt


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
            model=OpenAIModel.O3
        )
        # response is an AIMessage object
        print("Weather response:", response.output)

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
            prompt="What's my name and what do I like?",
            user_id=user_id,
            session_id=session_id
        )
        print("Response 2:", response2)

        # Simple question
        response = await client.ask("What is the capital of France?")
        print(response)

        class WeatherReport(BaseModel):
            location: str
            temperature: str
            condition: str
            recommendation: str

        weather_response = await client.ask(
            "Give me a weather report for Tokyo using the available tools",
            structured_output=WeatherReport,
            model=OpenAIModel.GPT_4_1_MINI
        )
        print("Structured weather response:")
        print("- Is structured:", weather_response.is_structured)
        print("- Output type:", type(weather_response.output))
        print("- Weather data:", weather_response.output)
        print("- Tools used:", [tc.name for tc in weather_response.tool_calls])


        # Streaming response
        async for chunk in client.ask_stream("Tell me a story about AI"):
            print(chunk, end="", flush=True)
    # Usage of Python Tool:
    async with OpenAIClient() as client:
        # Register the Python REPL tool
        repl_tool = client.register_python_tool()

        # Use the tool through OpenAI
        response = await client.ask(
            "Create a simple DataFrame with 3 rows and 2 columns, then show its info",
            tools=[repl_tool],
        )
        print(response)


async def example_video_generation():
    """Example of generating a video using Sora via the OpenAI client."""

    async with OpenAIClient() as client:
        video_prompt = VideoGenerationPrompt(
            prompt=(
                "A timelapse of a city skyline transitioning from dusk to night, "
                "with neon lights gradually illuminating the streets."
            ),
            model=OpenAIModel.SORA.value,
            number_of_videos=1,
            aspect_ratio="16:9",
            duration=10,
        )

        response = await client.generate_video(video_prompt)

        print("Video generation metadata:", response.output)
        print("Saved video files:", [str(path) for path in response.media or []])


if __name__ == "__main__":
    asyncio.run(example_usage())
