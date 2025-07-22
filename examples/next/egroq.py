from pydantic import BaseModel
from parrot.next import GroqClient, GroqModel

# Usage example
async def example_usage():
    """Example of how to use the GroqClient."""
    async with GroqClient() as client:

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
            model=GroqModel.LLAMA_3_3_70B_VERSATILE
        )
        print("Response text:", response.text)
        print("Model used:", response.model)
        print("Provider:", response.provider)
        print("Usage:", response.usage)
        print("Has tools:", response.has_tools)
        print("Tool calls:", [tc.name for tc in response.tool_calls])

        # Conversation with memory
        user_id = "user123"
        session_id = "chat001"

        await client.start_conversation(user_id, session_id, "You are a helpful assistant.")

        response1 = await client.ask(
            "My name is Alice and I like programming",
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

        # Streaming response
        print("Streaming response:")
        async for chunk in client.ask_stream(
            "Tell me a short story about AI",
            temperature=0.7,
            model=GroqModel.LLAMA_3_3_70B_VERSATILE
        ):
            print(chunk, end="", flush=True)
        print()  # New line after streaming

        # Structured output (requires a Pydantic model)
        class WeatherReport(BaseModel):
            """Weather report structure."""
            location: str
            temperature: str
            condition: str
            recommendation: str

        weather_response = await client.ask(
            "Give me a weather report for Tokyo",
            structured_output=WeatherReport,
            model=GroqModel.KIMI_K2_INSTRUCT  # Supports JSON mode
        )
        print("Structured weather response:")
        print("- Is structured:", weather_response.is_structured)
        print("- Output type:", type(weather_response.output))
        print("- Weather data:", weather_response.output)
        print("- Tools used:", [tc.name for tc in weather_response.tool_calls])

        # Example of accessing raw response for debugging
        print(
            "Raw response keys:",
            list(weather_response.raw_response.keys()) if weather_response.raw_response else "None"
        )



if __name__ == "__main__":
    import asyncio
    asyncio.run(example_usage())
