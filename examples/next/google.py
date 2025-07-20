import asyncio
from parrot.next import VertexAIClient, GenAIClient
from parrot.next.tools.math_tool import MathTool

async def main():
    question = "Give me a list of 10 European cities and their capitals. Use a list format."

    print("--- Asking Vertex AI ---")
    async with VertexAIClient() as client:
        response = await client.ask(question)
        print(response['content'][0]['text'])

    print("\n--- Asking Google GenAI ---")
    async with GenAIClient() as client:
        response = await client.ask(question)
        print(response['content'][0]['text'])

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
        print(response["content"][0]["text"])

    async with GenAIClient() as client:
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
        print(response["content"][0]["text"])

if __name__ == "__main__":
    asyncio.run(main())
