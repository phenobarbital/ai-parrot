import asyncio
from navconfig import BASE_DIR
from querysource.conf import default_dsn
from parrot.tools.nextstop import StoreInfo, EmployeeToolkit


async def test_tool():
    toolkit = StoreInfo(dsn=default_dsn, program="hisense")
    # Get all tools (automatic)
    tools = toolkit.get_tools()
    print(f"Available tools: {[tool.name for tool in tools]}")

    # List tool names
    tool_names = toolkit.list_tool_names()
    print(f"Tool names: {tool_names}")
    # Use tools directly
    store_info = await toolkit.get_store_information("BBY0225")
    print(store_info)
    traffic_data = await toolkit.get_foot_traffic("BBY1220", output_format="structured")
    print(traffic_data)
    # Get as pandas DataFrame
    traffic_df = await toolkit.get_foot_traffic("BBY1220", output_format="pandas")
    print(traffic_df.head())

    # Search for stores in a specific city and state
    stores_in_florida = await toolkit.search_stores(city="Estero", state_name="Florida")
    print(stores_in_florida)

    # Search by ZIP code
    stores = await toolkit.search_stores(zipcode="33928")
    print(stores)

    # Get Visit Information:
    visit_info = await toolkit.get_visit_information(store_id="BBY1220")
    print(visit_info)

async def test_employee_tool():
    toolkit = EmployeeToolkit(dsn=default_dsn, program="hisense")
    # Get all tools (automatic)
    tools = toolkit.get_tools()
    print(f"Available tools: {[tool.name for tool in tools]}")
    # List tool names
    tool_names = toolkit.list_tool_names()
    print(f"Tool names: {tool_names}")
    # Get by Employee visits:
    employee_visits = await toolkit.get_by_employee_visits(
        email='nsackett@hisenseretail.com'
    )
    print(employee_visits)


if __name__ == "__main__":
    asyncio.run(test_tool())
