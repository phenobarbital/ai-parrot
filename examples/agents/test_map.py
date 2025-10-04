import asyncio
import folium
from parrot.bots.agent import Agent
from parrot.tools import PythonPandasTool
from parrot.outputs import OutputMode



async def test_map():
    """Test Folium map rendering in different output modes"""
    agent = Agent(
        name="MapTester",
        use_tools=True,
        tools=[PythonPandasTool(locals={'folium': folium})],
        instructions="You create interactive maps using Folium",
        llm='openai',
        model='gpt-4.1',
    )
    await agent.configure()

    # User query
    response = await agent.ask("""
Create a Folium map centered at:
- latitude of 40.417° North
- longitude of 3.704° West
- zoom level of 12
Add a marker at the center with a popup saying "Center of Madrid".
Return the map as the final output.
    """,
        output_mode=OutputMode.HTML,
        format_kwargs={'return_html': True},
    )
    print("HTML Output:\n", response)


if __name__ == "__main__":
    asyncio.run(test_map())
