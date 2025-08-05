from parrot.tools.bby import BestBuyToolkit, BestBuyProductAvailabilityInput

toolkit = BestBuyToolkit()
sample_tool = toolkit._get_availability_tool()


async def test_tool():
    payload = {
        "location_id": "767",
        "zipcode": "33928",
        "sku": "6428376"
    }
    question = BestBuyProductAvailabilityInput(**payload)
    print(f"Question: {question}")
    print(f"Tool: {sample_tool.name}")
    print(f"Description: {sample_tool.description}")

    result = await sample_tool.arun(payload)
    print(f"Result: {result}")


if __name__ == "__main__":
    import asyncio
    asyncio.run(test_tool())
