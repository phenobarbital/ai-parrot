import asyncio
from langchain_core.documents import Document
from parrot.stores.postgres import PgvectorStore

embed_model = {
    "model": "thenlper/gte-base",
    "model_type": "transformers"
}

async def test_store_with_score():
    table = 'primo_info'
    schema = 'primo'
    id_column = 'primo_id'
    _store = PgvectorStore(
        embedding_model=embed_model,
        dsn="postgresql+asyncpg://troc_pgdata:12345678@127.0.0.1:5432/navigator",
        dimension=768,
        table=table,
        schema=schema,
        id_column=id_column,
        embedding_column='embedding'
    )

    async with _store as store:
        # find similar documents with score
        """Test similarity search functionality with scores."""
        print("\nTesting similarity search with scores...")

        test_queries = [
            "what is primo water?",
            "products and services of primo water",
            "I have a problem with a refill station",
            "what is readyfresh?",
            "how to contact primo water customer service",
            "what is a water source?",
            "how to become a primo water distributor",
            "payment options for primo water",
            "example brands"
        ]
        for query in test_queries:
            print(f"\n--- Searching for: '{query}' ---")
            try:
                # Perform similarity search with scores
                results = await store.similarity_search_with_score(
                    query,
                    limit=1
                )
                print(f"Found {len(results)} results:")
                for i, (doc, score) in enumerate(results, 1):
                    print(f"{i}. {doc.page_content[:100]}... (Score: {score})")
                    print(f"   Metadata: {doc.metadata}")
                    print()

            except Exception as e:
                print(f"Error during search: {e}")

if __name__ == "__main__":
    asyncio.run(test_store_with_score())
