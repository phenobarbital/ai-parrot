from pydantic import BaseModel
from parrot.clients.groq import GroqClient, GroqModel
from parrot.models.outputs import SentimentAnalysis, ProductReview

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
        # Response is an AIMessage object
        print("Response text:", response)

    #     # Conversation with memory
    #     user_id = "user123"
    #     session_id = "chat001"

    #     await client.start_conversation(user_id, session_id, "You are a helpful assistant.")

    #     response1 = await client.ask(
    #         "My name is Alice and I like programming",
    #         user_id=user_id,
    #         session_id=session_id
    #     )
    #     print("Response 1 text:", response1.output)

    #     response2 = await client.ask(
    #         "What's my name and what do I like?",
    #         user_id=user_id,
    #         session_id=session_id
    #     )
    #     print("Response 2 text:", response2.output)

    #     # Streaming response
    #     print("Streaming response:")
    #     async for chunk in client.ask_stream(
    #         "Tell me a short story about AI",
    #         temperature=0.7,
    #         model=GroqModel.LLAMA_3_3_70B_VERSATILE
    #     ):
    #         print(chunk, end="", flush=True)
    #     print()  # New line after streaming

    #     # Structured output (requires a Pydantic model)
    #     class WeatherReport(BaseModel):
    #         """Weather report structure."""
    #         location: str
    #         temperature: str
    #         condition: str
    #         recommendation: str

    #     weather_response = await client.ask(
    #         "Give me a weather report for Tokyo",
    #         structured_output=WeatherReport,
    #         model=GroqModel.KIMI_K2_INSTRUCT  # Supports JSON mode
    #     )
    #     print("Structured weather response:")
    #     print("- Is structured:", weather_response.is_structured)
    #     print("- Output type:", type(weather_response.output))
    #     print("- Weather data:", weather_response.output)
    #     print("- Tools used:", [tc.name for tc in weather_response.tool_calls])

    #     # Example of accessing raw response for debugging
    #     print(
    #         "Raw response keys:",
    #         list(weather_response.raw_response.keys()) if weather_response.raw_response else "None"
    #     )
    # async with GroqClient() as client:
    #     result = await client.analyze_sentiment(
    #         "I absolutely love this product! It works perfectly.",
    #         use_structured=True
    #     )

    #     # Parse the structured output
    #     if result.is_structured:
    #         sentiment_data = result.output
    #         print("- Is structured:", result.is_structured)
    #         print(type(sentiment_data))
    #         print("Sentiment Analysis Result:")
    #         print(f"Sentiment: {sentiment_data.sentiment}")
    #         print(f"Confidence: {sentiment_data.confidence_level}")
    #         print(f"Indicators: {sentiment_data.emotional_indicators}")
    #         print(f"Reason: {sentiment_data.reason}")

    #         # Any client (Groq/Claude/OpenAI)
    #     result = await client.analyze_product_review(
    #         review_text="Great laptop! Fast and reliable.",
    #         product_id="laptop-123",
    #         product_name="UltraBook Pro"
    #     )

    #     # Extract structured data
    #     review_data = result.output
    #     if review_data:
    #         print(f"Rating: {review_data.rating}/5.0")
    #         print(f"Sentiment: {review_data.sentiment}")
    #         print(f"Features: {review_data.key_features}")


if __name__ == "__main__":
    import asyncio
    asyncio.run(example_usage())
