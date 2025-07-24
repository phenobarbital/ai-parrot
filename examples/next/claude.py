from pathlib import Path
from typing import List, TypedDict
from dataclasses import dataclass
import asyncio
from PIL import Image
from pydantic import BaseModel, Field
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

    # # Initialize client
    # async with ClaudeClient() as client:

    #     # Register a tool
    #     def get_weather(location: str) -> str:
    #         """Get weather for a location."""
    #         weather_data = {
    #             "New York": "Sunny, 22°C",
    #             "London": "Rainy, 18°C",
    #             "Tokyo": "Cloudy, 26°C",
    #             "Paris": "Sunny, 20°C"
    #         }
    #         return weather_data.get(location, "Weather data not available")

    #     client.register_tool(
    #         name="get_weather",
    #         description="Get the current weather for a given location",
    #         input_schema={
    #             "type": "object",
    #             "properties": {
    #                 "location": {
    #                     "type": "string",
    #                     "description": "The name of the city"
    #                 }
    #             },
    #             "required": ["location"]
    #         },
    #         function=get_weather
    #     )

    #     # Simple question
    #     response = await client.ask(
    #         "What's the weather like in New York?",
    #         model=ClaudeModel.SONNET_3_5.value
    #     )
    #     print("Response text:", response.text)
    #     print("Model used:", response.model)
    #     print("Provider:", response.provider)
    #     print("Usage:", response.usage)
    #     print("Has tools:", response.has_tools)
    #     print("Tool calls:", [tc.name for tc in response.tool_calls])

    #     # Register a tool
    #     def calculate_area(length: float, width: float) -> float:
    #         """Calculate area of a rectangle."""
    #         return length * width

    #     client.register_tool(
    #         name="calculate_area",
    #         description="Calculate the area of a rectangle",
    #         input_schema={
    #             "type": "object",
    #             "properties": {
    #                 "length": {"type": "number", "description": "Length of rectangle"},
    #                 "width": {"type": "number", "description": "Width of rectangle"}
    #             },
    #             "required": ["length", "width"]
    #         },
    #         function=calculate_area
    #     )

    #     # Start a conversation with memory
    #     user_id = "user123"
    #     session_id = "chat001"

    #     await client.start_conversation(user_id, session_id, "You are a helpful assistant.")

    #     # Multi-turn conversation with memory
    #     response1 = await client.ask(
    #         "My name is Jesus and I like Python programming",
    #         user_id=user_id,
    #         session_id=session_id
    #     )
    #     print("Response 1 text:", response1.text)
    #     print("Turn ID:", response1.turn_id)

    #     response2 = await client.ask(
    #         "What's my name and what do I like?",
    #         user_id=user_id,
    #         session_id=session_id
    #     )
    #     print("Response 2 text:", response2.text)
    #     print("Session ID:", response2.session_id)

    #     # Simple question
    #     response = await client.ask("What is the capital of France?")
    #     print("Response text:", response.text)
    #     print("Model used:", response.model)
    #     print("Provider:", response.provider)
    #     print("Usage:", response.usage)
    #     print("Has tools:", response.has_tools)
    #     print("Tool calls:", [tc.name for tc in response.tool_calls])

    #     # Question with file upload
    #     filename = BASE_DIR.joinpath("example.pdf")
    #     if filename.exists():
    #         response = await client.ask(
    #             "What is the main topic of this document?",
    #             files=[filename]
    #         )
    #         print(response)
    #         response = await client.ask(
    #             "Summarize this document",
    #             files=[filename],
    #             model=ClaudeModel.SONNET_4
    #         )
    #         print(response)

    #     # Structured output with memory
    #     summary = await client.ask(
    #         "Summarize our conversation as JSON with key topics",
    #         structured_output=SummaryOutput,
    #         user_id=user_id,
    #         session_id=session_id
    #     )
    #     print("Structured Summary:", summary)


    #     # List conversations for user
    #     sessions = await client.list_conversations(user_id)
    #     print("User sessions:", sessions)

    #     # Streaming response with memory
    #     async for chunk in client.ask_stream(
    #         "Continue our conversation about Python",
    #         user_id=user_id,
    #         session_id=session_id
    #     ):
    #         print(chunk, end="", flush=True)

    #     # Streaming response
    #     async for chunk in client.ask_stream("Tell me a story about AI"):
    #         print(chunk, end="", flush=True)

    #     class WeatherReport(BaseModel):
    #         location: str
    #         temperature: str
    #         condition: str
    #         recommendation: str

    #     weather_response = await client.ask(
    #         "Give me a weather report for Tokyo using the available tools",
    #         structured_output=WeatherReport,
    #         model=ClaudeModel.SONNET_4.value
    #     )
    #     print("Structured weather response:")
    #     print("- Is structured:", weather_response.is_structured)
    #     print("- Output type:", type(weather_response.output))
    #     print("- Weather data:", weather_response.output)
    #     print("- Tools used:", [tc.name for tc in weather_response.tool_calls])

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

    async with ClaudeClient() as client:

        # Example 1: Basic image analysis with a file path
        image_path = BASE_DIR.joinpath('static', "be51ca05-802e-4dfd-bc53-fec65616d569-recap.jpeg")
        response = await client.ask_to_image(
            prompt="What products do you see in this image?",
            image=image_path,
            model=ClaudeModel.SONNET_4,
            max_tokens=1000,
            temperature=0.7
        )
        print("Basic analysis:", response.to_text)

        # Example 2: Using PIL Image object with reference images
        image_path = BASE_DIR.joinpath('static', "1bc3e9e8-3072-4c3a-8620-07fff9413a69-recap.jpeg")
        shaq = BASE_DIR.joinpath('static', "Shaq.jpg")
        pil_image = Image.open(image_path)
        ref_images = [
            Image.open(shaq)
        ]

        response = await client.ask_to_image(
            prompt=(
                "First, analyze the image to see if Shaquille O'Neal (from the reference image) is present. "
                "If he is, describe his location in the image, including any notable features or context. "
                "Then, provide bounding boxes for his location. "
                "Format your entire response as a single JSON object with 'analysis' and 'detections' keys."
            ),
            image=pil_image,
            reference_images=ref_images,
            model=ClaudeModel.SONNET_4
        )
        print("Comparison analysis:", response.to_text)

        # Example 3: Object counting with structured output
        image_path = BASE_DIR.joinpath('static', "8455b202-28cf-4231-a9d9-7c175def0a93-recap.jpeg")
        response = await client.ask_to_image(
            prompt="Count and identify all the electronic devices in this image",
            image=image_path,
            count_objects=True,  # This enables ObjectDetectionResult format
            model=ClaudeModel.SONNET_4
        )

        if response.is_structured:
            detection_result = response.output
            print(f"Found {detection_result.total_count} objects:")
            for detection in detection_result.detections:
                print(f"- {detection.product_type}: {detection.description} (confidence: {detection.confidence:.2f})")

        # Example 4: Using with conversation memory
        user_id = "user123"
        session_id = "session456"

        # First question about an image
        response1 = await client.ask_to_image(
            prompt="Describe what you see in this image",
            image=image_path,
            user_id=user_id,
            session_id=session_id
        )
        print("First response:", response1.to_text)

        # Follow-up question using conversation memory
        response2 = await client.ask(
            prompt="What colors are prominent in the image we just discussed?",
            user_id=user_id,
            session_id=session_id
        )
        print("Follow-up response:", response2.to_text)

        # Example 5: Using bytes data
        with open(str(image_path), "rb") as f:
            image_bytes = f.read()

        response = await client.ask_to_image(
            prompt="Analyze the technical specifications visible in this product image",
            image=image_bytes,
            model=ClaudeModel.SONNET_4,
            temperature=0.3  # Lower temperature for more factual analysis
        )
        print("Technical analysis:", response.to_text)

        # Example 6: Custom structured output

        class ProductAnalysis(BaseModel):
            """Example structured output model for product analysis."""
            brand: str = Field(description="The brand name of the product (e.g., 'Samsung', 'Apple', 'HP')")
            model: str = Field(description="The specific model name or number of the product")
            key_features: List[str] = Field(description="List of key features visible in the image")
            condition: str = Field(
                description="The apparent condition of the product (e.g., 'New', 'Used', 'Refurbished')"
            )
            estimated_price_range: str = Field(
                description="Estimated price range (e.g., '$100-200', 'Under $50')"
            )


        response = await client.ask_to_image(
            prompt="""Analyze this product and respond with ONLY this JSON structure:
            {
                "brand": "exact brand name",
                "model": "exact model name",
                "key_features": ["list", "of", "features"],
                "condition": "condition description",
                "estimated_price_range": "price range"
            }
            Use exactly these field names.""",
            image=image_path,
            structured_output=ProductAnalysis,
            model=ClaudeModel.SONNET_4
        )

        if response.is_structured:
            analysis = response.output
            print(f"Brand: {analysis.brand}")
            print(f"Model: {analysis.model}")
            print(f"Features: {', '.join(analysis.key_features)}")
            print(f"Condition: {analysis.condition}")
            print(f"Price Range: {analysis.estimated_price_range}")

if __name__ == "__main__":
    asyncio.run(example_usage())
