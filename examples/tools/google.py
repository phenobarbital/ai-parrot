import asyncio
from parrot.tools.google import (
    GoogleSearchTool,
    GoogleSiteSearchTool,
    GoogleLocationTool,
    GoogleRoutesTool
)

async def example_usage():
    # # Search with content preview
    # search_tool = GoogleSearchTool()
    # result = await search_tool.execute(
    #     query="Python async programming",
    #     max_results=10,
    #     preview=True,
    #     preview_method="aiohttp" # or selenium
    # )
    # print(f"Search results: {result}")

    # # Site-specific search
    # site_search = GoogleSiteSearchTool()
    # result = await site_search.execute(
    #     query="machine learning",
    #     site="github.com",
    #     max_results=5
    # )
    # print(f"Site search results: {result}")

    # # Geocoding with structured output
    # location_tool = GoogleLocationTool()
    # result = await location_tool.execute(
    #     address="1600 Amphitheatre Parkway, Mountain View, CA"
    # )
    # print(f"Geocoded location: {result}")

    # Route planning with static map
    routes_tool = GoogleRoutesTool()
    result = await routes_tool.execute(
        origin="San Francisco, CA",
        destination="Los Angeles, CA",
        waypoints=["San Jose, CA", "Fresno, CA"],
        optimize_waypoints=True,
        include_static_map=True,
        travel_mode="DRIVE",
        auto_zoom=True  # Will calculate appropriate zoom
    )
    print(f"Route details: {result.result.get('static_map_url')}")

    # Interactive HTML map
    result = await routes_tool.execute(
        origin="San Francisco, CA",
        destination="Los Angeles, CA",
        waypoints=["San Jose, CA"],
        include_interactive_map=True
    )
    # Access via: result.result['interactive_map_url']
    print(f"Interactive map URL: {result.result['interactive_map_file']}")

    # Mixed format - some addresses, some coordinates
    result = await routes_tool.execute(
        origin="37.7749,-122.4194",  # SF coordinates
        destination="Los Angeles, CA",  # Address (will geocode once)
        waypoints=["37.3382,-121.8863", "Fresno, CA"],  # Mixed
        include_static_map=True,
        include_interactive_map=True
    )
    print(f"Interactive map URL: {result.result['interactive_map_file']}")


if __name__ == "__main__":
    asyncio.run(example_usage())
