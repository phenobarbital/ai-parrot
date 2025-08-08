import asyncio
from parrot.tools.flowtask import FlowtaskTool



async def example_usage():
    """Example usage of the FlowtaskTool."""
    # Create tool instance
    flowtask_tool = FlowtaskTool()

    # Execute a component
    result = await flowtask_tool._execute(
        component_name="GooglePlaces",
        attributes={
            "use_proxies": True,
            "type": "traffic"
        },
        input_data=[
            {"place_id": "ChIJ5ecuOKX5dYgRV2Rwmaj-GHA"}
        ]
    )
    print(result)


if __name__ == "__main__":
    asyncio.run(example_usage())
