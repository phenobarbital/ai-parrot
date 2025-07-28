import asyncio
from parrot.clients import VertexAIClient, StreamingRetryConfig
from parrot.models.outputs import SentimentAnalysis
from parrot.tools import MathTool


async def main():
    question = "Give me a list of 10 European cities and their capitals. Use a list format."
    print("--- Asking Vertex AI ---")
    async with VertexAIClient() as client:
        response = await client.ask(question)
        print(response.output)                    # Response text
        print(response.usage.prompt_tokens)     # 39 (from usage_metadata)
        print(response.usage.completion_tokens) # 5 (from usage_metadata)
        print(response.usage.total_tokens)      # 110 (from usage_metadata)
        print(response.provider)                # "vertexai"

        result = await client.ask(
            "Analyze this data with sentiment analysis",
            user_id="user123",
            session_id="session456",
            structured_output=SentimentAnalysis
        )
        # Parse the structured output
        if result.is_structured:
            sentiment_data = result.output
            print("- Is structured:", result.is_structured)
            print(type(sentiment_data))
            print("Sentiment Analysis Result:")
            print(f"Sentiment: {sentiment_data.sentiment}")
            print(f"Confidence: {sentiment_data.confidence_level}")
            print(f"Indicators: {sentiment_data.emotional_indicators}")
            print(f"Reason: {sentiment_data.reason}")

        # Streaming with retry logic
        async for chunk in client.ask_stream(
            "Write a long story",
            on_max_tokens="retry",
            retry_config=StreamingRetryConfig(max_retries=3)
        ):
            print(chunk, end="")

        result = await client.analyze_product_review(
            review_text="Great laptop! Fast and reliable.",
            product_id="laptop-123",
            product_name="UltraBook Pro"
        )

        # Extract structured data
        review_data = result.output
        if review_data:
            print(f"Rating: {review_data.rating}/5.0")
            print(f"Sentiment: {review_data.sentiment}")
            print(f"Features: {review_data.key_features}")

    async with VertexAIClient() as client:
        math_tool = MathTool()

        # Register the tool's methods
        client.register_tool(
            math_tool
        )

        response = await client.ask(
            "What is the result of multiplying 5 and 10?",
            structured_output=math_tool.multiply
        )
        print('--- Vertex AI Tool Call Response ---')
        print(response.output)                    # Response text


if __name__ == "__main__":
    asyncio.run(main())
