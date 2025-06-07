import asyncio
import time
import traceback
from langchain_community.vectorstores.utils import DistanceStrategy
from parrot.stores.postgres import PgvectorStore

embed_model = {
    "model_name": "sentence-transformers/all-MiniLM-L12-v2",
    "model_type": "transformers"
}

# Example 1: Using custom embedding column name and COSINE distance
async def create_locator_custom_column():
    _store = PgvectorStore(
        embedding_model=embed_model,
        dsn="postgresql+asyncpg://troc_pgdata:12345678@127.0.0.1:5432/navigator",
        embedding_column="store_vector",  # Custom embedding column name
        distance_strategy="COSINE"  # Distance strategy
    )
    async with _store as store:
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
            embedding_column="store_vector",  # Use custom column name
            dimension=384
        )

# Example 2: Using L2 (Euclidean) distance with custom embedding column
async def test_locator_l2_distance():
    _store = PgvectorStore(
        embedding_model=embed_model,
        dsn="postgresql+asyncpg://troc_pgdata:12345678@127.0.0.1:5432/navigator",
        dimension=384,
        table='stores',
        schema='bestbuy',
        id_column='store_id',
        embedding_column="store_vector",  # Custom column name
        distance_strategy="L2"  # L2/Euclidean distance
    )
    async with _store as store:
        query = "an store near of Naples boulevard, Florida"
        results = await store.similarity_search(
            query,
            limit=5,
            score_threshold=0.51,
            collection='bestbuy.stores',
        )
        for doc in results:
            print('Store (L2) > ', doc.page_content, doc.metadata)

# Example 3: Using Inner Product distance
async def test_locator_inner_product():
    _store = PgvectorStore(
        embedding_model=embed_model,
        dsn="postgresql+asyncpg://troc_pgdata:12345678@127.0.0.1:5432/navigator",
        dimension=384,
        table='products',
        schema='inventory',
        id_column='product_id',
        embedding_column="product_embedding",  # Different column name
        distance_strategy="IP"  # Inner Product
    )
    async with _store as store:
        query = "wireless headphones"
        results = await store.similarity_search(
            query,
            limit=10,
            score_threshold=0.7,
        )
        for doc in results:
            print('Product (IP) > ', doc.page_content, doc.metadata)

# Example 4: Dynamically changing distance strategy
async def test_dynamic_strategy_change():
    _store = PgvectorStore(
        embedding_model=embed_model,
        dsn="postgresql+asyncpg://troc_pgdata:12345678@127.0.0.1:5432/navigator",
        dimension=384,
        table='stores',
        schema='bestbuy',
        id_column='store_id',
        embedding_column="store_vector",
        distance_strategy="COSINE"  # Start with COSINE
    )
    async with _store as store:
        query = "store in Florida state"
        try:
            # Search with COSINE
            print("=== COSINE Results ===")
            try:
                results_cosine = await store.similarity_search(query, limit=3)
                print(f"✅ COSINE found {len(results_cosine)} results")
                for doc in results_cosine:
                    print('COSINE > ', doc.page_content)
            except Exception as e:
                print(f"❌ COSINE failed: {type(e).__name__}: {e}")
                traceback.print_exc()

            # Change to L2 distance
            store.set_distance_strategy(DistanceStrategy.EUCLIDEAN_DISTANCE)
            print("\n=== L2/EUCLIDEAN Results ===")
            results_l2 = await store.similarity_search(query, limit=3)
            for doc in results_l2:
                print('L2 > ', doc.page_content)

            # Change to Inner Product
            store.set_distance_strategy(DistanceStrategy.MAX_INNER_PRODUCT)
            print("\n=== MAX_INNER_PRODUCT Results ===")
            results_ip = await store.similarity_search(query, limit=3)
            for doc in results_ip:
                print('IP > ', doc.page_content)
        except Exception as e:
            print(f"Error during dynamic strategy change: {e}")

# Example 5: Creating tables with different embedding column names
async def create_multiple_tables():
    """Create different tables with different embedding column configurations"""

    # Stores table with 'store_embeddings' column
    stores_config = PgvectorStore(
        embedding_model=embed_model,
        dsn="postgresql+asyncpg://troc_pgdata:12345678@127.0.0.1:5432/navigator",
        embedding_column="store_embeddings",
        distance_strategy="COSINE"
    )

    # Products table with 'product_vectors' column
    products_config = PgvectorStore(
        embedding_model=embed_model,
        dsn="postgresql+asyncpg://troc_pgdata:12345678@127.0.0.1:5432/navigator",
        embedding_column="product_vectors",
        distance_strategy="L2"
    )

    # Reviews table with 'review_embeddings' column
    reviews_config = PgvectorStore(
        embedding_model=embed_model,
        dsn="postgresql+asyncpg://troc_pgdata:12345678@127.0.0.1:5432/navigator",
        embedding_column="review_embeddings",
        distance_strategy="IP"
    )

    # Create all tables
    async with stores_config as store:
        await store.create_embedding_table(
            table='stores',
            schema='retail',
            columns=['store_name', 'address', 'city'],
            id_column='store_id',
            dimension=384
        )

    async with products_config as store:
        await store.create_embedding_table(
            table='products',
            schema='retail',
            columns=['product_name', 'description', 'category'],
            id_column='product_id',
            dimension=384
        )

    async with reviews_config as store:
        await store.create_embedding_table(
            table='reviews',
            schema='retail',
            columns=['review_text', 'rating', 'product_id'],
            id_column='review_id',
            dimension=384
        )

# Performance comparison between distance strategies
async def compare_distance_strategies():
    """Compare performance and results of different distance strategies"""
    _store = PgvectorStore(
        embedding_model=embed_model,
        dsn="postgresql+asyncpg://troc_pgdata:12345678@127.0.0.1:5432/navigator",
        dimension=384,
        table='stores',
        schema='bestbuy',
        id_column='store_id',
        embedding_column="embedding_vec",
        distance_strategy="COSINE"
    )

    query = "electronics store in mall"
    strategies = ["COSINE", "L2", "IP"]

    async with _store as store:
        for strategy in strategies:
            # Update strategy
            strategy_enum = {
                "COSINE": DistanceStrategy.COSINE,
                "L2": DistanceStrategy.EUCLIDEAN_DISTANCE,
                "IP": DistanceStrategy.MAX_INNER_PRODUCT
            }[strategy]

            store.vector_store.set_distance_strategy(strategy_enum)

            # Time the search
            start_time = time.time()
            results = await store.similarity_search(query, limit=5)
            end_time = time.time()

            print(f"\n=== {strategy} Strategy ===")
            print(f"Search time: {end_time - start_time:.4f} seconds")
            print(f"Results found: {len(results)}")
            for i, doc in enumerate(results[:3], 1):
                print(f"{i}. {doc.page_content}")

if __name__ == "__main__":
    # Run examples
    asyncio.run(create_locator_custom_column())
    # asyncio.run(test_locator_l2_distance())
    # asyncio.run(test_locator_inner_product())
    # asyncio.run(test_dynamic_strategy_change())
    # asyncio.run(create_multiple_tables())
    # asyncio.run(compare_distance_strategies())
