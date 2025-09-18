import asyncio
from querysource.conf import async_default_dsn
from parrot.bots.database import AbstractDBAgent, SQLAgent
from parrot.bots.database.models import UserRole


async def test_agent():
    agent = AbstractDBAgent(dsn=async_default_dsn, allowed_schemas=["auth","public"])
    await agent.configure()

    async with agent:
        response = await agent.ask(
            'get username and email of active employees',
            user_role="data_analyst"
        )
        print('--- Basic Response ---')
        print(response)

async def sql_agent():

    print('Generating SQLAgent...')

    sql_agent = SQLAgent(dsn=async_default_dsn, allowed_schemas=["auth", "hisense"], client_id="hisense")

    await sql_agent.configure()

    async with sql_agent:
        response = await sql_agent.ask(
            "Return for documentation in markdown format the metadata of table inventory in schema hisense",
            # "get all superusers in users",
            # 'Get top-10 products by pricing',
            # 'Get top-10 TV LEDs products by pricing',
            # 'which products have better review average?',
            # 'how many products have Lowest Price below 300?',
            # 'which is the highest price of a product_type LED TV from table products?, important: pricing is a varchar column with format like $1,999.00',
            user_role=# UserRole.DATA_ANALYST
                # UserRole.BUSINESS_USER
                # UserRole.DATA_ENGINEER
                # UserRole.DB_ADMIN
                UserRole.DEVELOPER
                # UserRole.DATA_SCIENTIST
        )
        print('--- SQL Agent Response ---')
        print(response)


if __name__ == "__main__":
    asyncio.run(sql_agent())
