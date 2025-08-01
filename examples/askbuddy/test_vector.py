import asyncio
from parrot.stores.postgres import PgVectorStore

async def test_search():
    """Test search functionality."""
    embed_model = {
        "model": "thenlper/gte-base",
        "model_type": "huggingface"
    }
    # Define the table and schema
    table = 'employee_information'
    schema = 'mso'
    _store = PgVectorStore(
        embedding_model=embed_model,
        dsn="postgresql+asyncpg://troc_pgdata:12345678@127.0.0.1:5432/navigator",
        table=table,
        schema=schema,
        dimension=768,
        embedding_column='embedding'
    )
    async with _store as store:
        # find similar documents with MMR
        """Test MMR functionality."""
        print("\nTesting Similarity search...")
        query = "Maximum paid time off to be taken"
        results = await store.similarity_search(query)
        print("Similarity Search Results:")
        for result in results:
            print(f" - {result}")

        # find similar documents with MMR
        print("\nTesting MMR search...")
        results = await store.mmr_search(query)
        print("MMR Search Results:")
        for result in results:
            print(f" - {result}")


if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(test_search())
    loop.close()
