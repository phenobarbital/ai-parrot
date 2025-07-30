import asyncio
from parrot.tools.zipcode import ZipcodeAPIToolkit

async def example_usage():
    # Initialize toolkit
    toolkit = ZipcodeAPIToolkit()

    # Get all available tools
    tools = toolkit.get_tools()
    print(f"Available tools: {[tool.name for tool in tools]}")

    # Example usage of each tool
    try:
        # Get location info
        location = await toolkit.get_zipcode_location("33066")
        print(f"Location info: {location}")

        # Calculate distance
        distance = await toolkit.calculate_zipcode_distance("33066", "10001")
        print(f"Distance: {distance}")

        # Find nearby zipcodes
        nearby = await toolkit.find_zipcodes_in_radius("33066", radius=10)
        print(f"Nearby zipcodes: {len(nearby.get('zip_codes', []))} found")

        # Get city zipcodes
        city_zips = await toolkit.get_city_zipcodes("Miami", "FL")
        print(f"Miami zipcodes: {city_zips}")
    except ValueError as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(example_usage())
