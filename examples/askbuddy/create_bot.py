import asyncio
from parrot.bots.basic import BasicBot


async def get_agent():
    """Return the New Agent.
    """
    agent = BasicBot(
        name='AskBuddy'
    )
    embed_model = {
        "model": "thenlper/gte-base",
        "model_type": "huggingface"
    }
    agent.define_store(
        vector_store='postgres',
        embedding_model=embed_model,
        dsn="postgresql+asyncpg://troc_pgdata:12345678@127.0.0.1:5432/navigator",
        dimension=768,
    )
    await agent.configure()
    # Create the Collection
    if agent.store.collection_exists(
        table='employee_information',
        schema='mso'
    ):
        await agent.store.delete_collection(
            table='employee_information',
            schema='mso'
        )
    await agent.store.create_collection(  # pylint: disable=E1120
        table='employee_information',
        schema='mso',
        dimension=768,
        index_type="COSINE",
        metric_type='L2'
    )


if __name__ == "__main__":
    agent = asyncio.run(get_agent())
