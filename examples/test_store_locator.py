import asyncio
from parrot.stores.postgres import PgvectorStore



embed_model = {
    "model_name": "thenlper/gte-base",
    "model_type": "transformers"
}


async def create_locator():
    _store = PgvectorStore(
        embedding_model=embed_model,
        dsn="postgresql+asyncpg://troc_pgdata:12345678@127.0.0.1:5432/navigator",
        dimension=768,
        table='stores',
        schema='bestbuy',
        id_column='store_id',
        embedding_column='store_vector'
    )
    async with _store as store:
        # Compute the embedding and update an existing Table.
        await store.create_embedding_table(
            table='stores',
            schema='bestbuy',
            columns=[
                'store_name',
                'location_code',
                'store_id',
                'formatted_address',
                'city',
                'state_code',
                'zipcode',
                'country_code',
            ],
            id_column='store_id',
            embedding_column='store_vector',
            dimension=768
        )

async def test_locator():
    _store = PgvectorStore(
        embedding_model=embed_model,
        dsn="postgresql+asyncpg://troc_pgdata:12345678@127.0.0.1:5432/navigator",
        dimension=768,
        table='stores',
        schema='bestbuy',
        id_column='store_id',
        embedding_column='store_vector',
    )
    async with _store as store:
        # Do a Similarity Search over a existing Store:
        query = "store with Id BBY1030"
        results = await store.similarity_search(
            query,
            limit=None,
            score_threshold=0.10,
            collection='bestbuy.stores',
        )
        for doc in results:
            print('Store > ', doc.page_content, doc.metadata)


if __name__ == "__main__":
    asyncio.run(create_locator())
    asyncio.run(test_locator())
