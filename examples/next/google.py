import asyncio
from parrot.next import VertexAIClient, GoogleGenAIClient, GoogleModel
from parrot.next.tools.math_tool import MathTool

async def main():
    question = "Give me a list of 10 European cities and their capitals. Use a list format."

    print("--- Asking Vertex AI ---")
    async with VertexAIClient() as client:
        response = await client.ask(question)
        print(response.text)                    # Response text
        print(response.usage.prompt_tokens)     # 39 (from usage_metadata)
        print(response.usage.completion_tokens) # 5 (from usage_metadata)
        print(response.usage.total_tokens)      # 110 (from usage_metadata)
        print(response.provider)                # "vertex_ai"

    print("\n--- Asking Google GenAI ---")
    async with GoogleGenAIClient() as client:
        response = await client.ask(question)
        print(response.text)                    # Response text
        print(response.usage.prompt_tokens)     # 39 (from usage_metadata)
        print(response.usage.completion_tokens) # 5 (from usage_metadata)
        print(response.usage.total_tokens)      # 110 (from usage_metadata)
        print(response.provider)                # "vertex_ai"

    async with VertexAIClient() as client:
        math_tool = MathTool()

        # Register the tool's methods
        client.register_tool(
            name="multiply",
            description="Multiplies two numbers.",
            input_schema={
                "type": "object",
                "properties": {
                    "a": {"type": "number"},
                    "b": {"type": "number"},
                },
                "required": ["a", "b"],
            },
            function=math_tool.multiply,
        )

        response = await client.ask(
            "What is the result of multiplying 5 and 10?",
            structured_output=math_tool.multiply
        )
        print('--- Vertex AI Tool Call Response ---')
        print(response.text)                    # Response text
        print(response.usage.prompt_tokens)     # 39 (from usage_metadata)
        print(response.usage.completion_tokens) # 5 (from usage_metadata)
        print(response.usage.total_tokens)      # 110 (from usage_metadata)
        print(response.provider)                # "vertex_ai"

    async with GoogleGenAIClient() as client:
        math_tool = MathTool()

        # Register the tool's methods
        client.register_tool(
            name="add",
            description="Adds two numbers.",
            input_schema={
                "type": "object",
                "properties": {
                    "a": {"type": "number"},
                    "b": {"type": "number"},
                },
                "required": ["a", "b"],
            },
            function=math_tool.add,
        )
        client.register_tool(
            name="divide",
            description="Divides two numbers.",
            input_schema={
                "type": "object",
                "properties": {
                    "a": {"type": "number"},
                    "b": {"type": "number"},
                },
                "required": ["a", "b"],
            },
            function=math_tool.divide,
        )
        question = "What is 150 plus 79, and also what is 1024 divided by 256?"
        response = await client.ask(
            question,
            structured_output=math_tool.add
        )
        print('--- Google GenAI Tool Call Response ---')
        print(response.text)                    # Response text
        print(response.usage.prompt_tokens)     # 39 (from usage_metadata)
        print(response.usage.completion_tokens) # 5 (from usage_metadata)
        print(response.usage.total_tokens)      # 110 (from usage_metadata)
        print(response.provider)                # "google_genai"

        # Register multiple tools for parallel execution
        def add_numbers(a: float, b: float) -> float:
            """Add two numbers."""
            return a + b

        def multiply_numbers(a: float, b: float) -> float:
            """Multiply two numbers."""
            return a * b

        client.register_tool(
            name="add_numbers",
            description="Add two numbers together",
            input_schema={
                "type": "object",
                "properties": {
                    "a": {"type": "number", "description": "First number"},
                    "b": {"type": "number", "description": "Second number"}
                },
                "required": ["a", "b"]
            },
            function=add_numbers
        )

        client.register_tool(
            name="multiply_numbers",
            description="Multiply two numbers together",
            input_schema={
                "type": "object",
                "properties": {
                    "a": {"type": "number", "description": "First number"},
                    "b": {"type": "number", "description": "Second number"}
                },
                "required": ["a", "b"]
            },
            function=multiply_numbers
        )

        # Parallel tool execution
        response = await client.ask(
            "Calculate both: 5 + 3 and 4 * 7. Use the appropriate tools for each calculation.",
            model=GoogleModel.GEMINI_2_5_FLASH
        )
        print("Response text:", response.text)
        print("Model used:", response.model)
        print("Provider:", response.provider)
        print("Has tools:", response.has_tools)
        print("Tool calls:", [f"{tc.name}({tc.arguments}) = {tc.result}" for tc in response.tool_calls])
        print("Total execution time:", sum(tc.execution_time for tc in response.tool_calls))

        # Conversation with memory
        user_id = "user123"
        session_id = "chat001"

        await client.start_conversation(user_id, session_id, "You are a helpful math assistant.")

        response1 = await client.ask(
            "My lucky numbers are 3 and 7",
            user_id=user_id,
            session_id=session_id,
            model=GoogleModel.GEMINI_2_5_FLASH
        )
        print("Response 1 text:", response1.text)
        print("Turn ID:", response1.turn_id)

        response2 = await client.ask(
            "Add my two lucky numbers together using the add function",
            user_id=user_id,
            session_id=session_id,
            model=GoogleModel.GEMINI_2_5_FLASH
        )
        print("Response 2 text:", response2.text)
        print("Tools used:", [tc.name for tc in response2.tool_calls])

        # Streaming response
        print("Streaming response:")
        async for chunk in client.ask_stream(
            "Tell me an interesting fact about mathematics",
            temperature=0.7,
            model=GoogleModel.GEMINI_2_5_FLASH
        ):
            print(chunk, end="", flush=True)
        print()  # New line after streaming

        # Structured output
        from pydantic import BaseModel

        class MathOperations(BaseModel):
            addition_result: float
            multiplication_result: float
            explanation: str

        math_response = await client.ask(
            "Calculate 12 + 8 and 6 * 9, then format the results",
            structured_output=MathOperations,
            model=GoogleModel.GEMINI_2_5_FLASH
        )
        print("Structured math response:")
        print("- Is structured:", math_response.is_structured)
        print("- Output type:", type(math_response.output))
        print("- Math data:", math_response.output)
        print("- Parallel tools used:", len(math_response.tool_calls))

if __name__ == "__main__":
    asyncio.run(main())
