import asyncio
from parrot.bots.agent import BasicAgent
from parrot.tools.retail.bby import BestBuyToolkit
from parrot.tools.zipcode import ZipcodeAPIToolkit


async def create_agent():
    toolkit = BestBuyToolkit()
    zp = ZipcodeAPIToolkit()
    bby = toolkit.get_tools()
    # zp_tools = zp.get_tools()
    system_prompt = """
    You are a helpful shopping assistant specialized in checking product information and availability at Best Buy stores.
    Your goal is to help users find out if a product information, or if is available at a specific store.
    Use the tools available to check product information (based on search or product name) and availability based on the store location, zip code, and product SKU.

    IMPORTANT:

    When searching for products and you find MULTIPLE RESULTS, you must:
    1. List ALL products found in a clear, formatted table with complete details for each product
    2. Include ALL fields returned by the tool for EVERY product (sku, name, price, reviews, etc.)
    3. DO NOT summarize or omit any products from the list
    4. After listing all products, provide a brief summary of the options and ask the user which specific product they're interested in


    When reporting availability, include ALL details from the tool response including:
    1. Complete store information (name, address, city, state, zip, hours)
    2. Complete product availability details (in-store availability, pickup eligibility, quantity, etc.)
    3. Format this information clearly for the user in your response.
    """
    agent = BasicAgent(
        name='BestBuyAgent',
        system_prompt=system_prompt,
        tools=[bby, zp]
    )
    await agent.configure()
    return agent


if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    agent = loop.run_until_complete(create_agent())
    query = input("Type in your query: \n")
    EXIT_WORDS = ["exit", "quit", "bye"]
    while query not in EXIT_WORDS:
        if query:
            response = loop.run_until_complete(
                agent.invoke(query)
            )
            print('::: Response: ', response)
        query = input("Type in your query: \n")
