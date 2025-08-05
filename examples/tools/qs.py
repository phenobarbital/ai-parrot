import asyncio
from pydantic import BaseModel
from parrot.tools import QuerySourceTool

# Define your data model
class StoreInfo(BaseModel):
    """Model for store information."""
    store_id: str
    store_name: str
    zipcode: str
    city: str

async def test_tool():
    tool = QuerySourceTool()
    # Add to tool
    tool.add_structured_output("StoreInfo", StoreInfo)

    # Use it
    result = await tool.execute(
        query_slug="hisense_stores",
        return_format="structured",
        structured_output_class="StoreInfo",
        limit=10
    )
    print(result)


if __name__ == "__main__":
    asyncio.run(test_tool())
# This code tests the QuerySourceTool with a structured output using Pydantic.
