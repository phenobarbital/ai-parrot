"""
Usage example showing how to use AbstractBot with ToolManager
"""
import asyncio
from parrot.bots import AbstractBot
from parrot.tools import AbstractTool

def weather_function(location: str) -> str:
    # Mock weather function
    return f"Weather in {location}: Sunny, 25°C"

async def main():
    # Create bot with initial tools
    bot = AbstractBot(
        name="AssistantBot",
        use_tools=True,
        tools=['math', custom_tool_instance],  # Mix of string names and instances
        operation_mode='adaptive'
    )

    # Configure the bot (this will set up ToolManager and sync with LLM)
    await bot.configure()

    # Add more tools dynamically
    bot.register_tool(
        name="weather",
        description="Get weather information",
        input_schema={
            "type": "object",
            "properties": {
                "location": {"type": "string", "description": "City name"}
            },
            "required": ["location"]
        },
        function=weather_function
    )

    # Check tool status
    tools_info = bot.get_tools_summary()
    print(f"Available tools: {tools_info['available_tools']}")
    print(f"Total tools: {tools_info['tools_count']}")
    print(f"Categories: {tools_info['categories']}")

    # Validate tools
    validation = bot.validate_tools()
    print(f"Valid tools: {validation['valid_tools']}")

    # Use the bot
    response = await bot.conversation(
        question="Calculate the square root of 144 and tell me the weather in Paris",
        user_id="user123",
        session_id="session456"
    )

    print(response.response)
    if response.has_tools:
        print(f"Tools used: {[tc.name for tc in response.tool_calls]}")

# Custom tool example
class CustomTool(AbstractTool):
    """A custom tool example."""
    def __init__(self):
        self.name = "custom_calculator"
        self.description = "Performs custom calculations"
        self.category = "math"

    def validate(self) -> bool:
        return True  # Simple validation

    def _execute(self) -> str:
        return "Custom calculation result"

custom_tool_instance = CustomTool()

if __name__ == "__main__":
    asyncio.run(main())
