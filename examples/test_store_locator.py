import asyncio
from parrot.stores.postgres import PgvectorStore



embed_model = {
    "model_name": "sentence-transformers/all-MiniLM-L12-v2",
    "model_type": "transformers"
}


async def create_locator():
    _store = PgvectorStore(
        embedding_model=embed_model,
        dsn="postgresql+asyncpg://troc_pgdata:12345678@127.0.0.1:5432/navigator"
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
            dimension=384
        )

async def test_locator():
    _store = PgvectorStore(
        embedding_model=embed_model,
        dsn="postgresql+asyncpg://troc_pgdata:12345678@127.0.0.1:5432/navigator",
        dimension=384,
        table='stores',
        schema='bestbuy',
        id_column='store_id'
    )
    async with _store as store:
        # Do a Similarity Search over a existing Store:
        query = "address of Estero store, in FL"
        results = await store.similarity_search(
            query,
            limit=None,
            score_threshold=0.5,
            collection='bestbuy.stores',
        )
        for doc in results:
            print('Store > ', doc.page_content, doc.metadata)


if __name__ == "__main__":
    asyncio.run(test_locator())
