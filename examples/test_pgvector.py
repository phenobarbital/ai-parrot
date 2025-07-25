"""
Test script for custom PgVectorStore functionality.
Tests table creation, document insertion, and similarity search.
"""

import asyncio
import uuid
from typing import List
from sqlalchemy import text
from parrot.stores.models import Document
from parrot.stores.pg import PgVectorStore



embed_model = {
    "model": "thenlper/gte-base",
    "model_type": "huggingface"
}

async def create_store():
    table = 'test_table'
    schema = 'troc'
    id_column = 'id'
    _store = PgVectorStore(
        embedding_model=embed_model,
        dsn="postgresql+asyncpg://troc_pgdata:12345678@127.0.0.1:5432/navigator",
        dimension=768,
        table=table,
        schema=schema,
        id_column=id_column,
        embedding_column='embedding'
    )

    async with _store as store:
        # First: Create sample Table:
        print(f"Creating test table {schema}.{table}...")
        create_table_sql = f"""
        CREATE TABLE IF NOT EXISTS {schema}.{table} (
            {id_column} VARCHAR PRIMARY KEY,
            description TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
        async with store.engine().begin() as conn:
            await conn.execute(text(create_table_sql))
            # Second: prepare the table for embedding:
            await store.prepare_embedding_table(
                table=table,
                schema=schema,
                conn=conn,
                embedding_column='embedding',
                id_column=id_column,
                dimension=768
            )


def create_test_documents() -> List[Document]:
    """Create sample documents for testing."""
    print("Creating test documents...")

    test_data = [
        {
            "id": str(uuid.uuid4()),
            "content": "Python is a high-level programming language known for its simplicity and readability.",
            "metadata": {"category": "programming", "language": "python", "topic": "basics"}
        },
        {
            "id": str(uuid.uuid4()),
            "content": "Machine learning is a subset of artificial intelligence that enables computers to learn without being explicitly programmed.",
            "metadata": {"category": "ai", "topic": "machine_learning", "difficulty": "intermediate"}
        },
        {
            "id": str(uuid.uuid4()),
            "content": "PostgreSQL is a powerful, open-source object-relational database system with strong emphasis on extensibility and SQL compliance.",
            "metadata": {"category": "database", "type": "relational", "topic": "postgresql"}
        },
        {
            "id": str(uuid.uuid4()),
            "content": "Vector databases are specialized databases designed to store and query high-dimensional vectors efficiently.",
            "metadata": {"category": "database", "type": "vector", "topic": "embeddings"}
        },
        {
            "id": str(uuid.uuid4()),
            "content": "Natural language processing (NLP) involves the interaction between computers and human language to process and analyze text data.",
            "metadata": {"category": "ai", "topic": "nlp", "difficulty": "advanced"}
        }
    ]

    documents = [
        Document(
            id=item["id"],
            page_content=item["content"],
            metadata=item["metadata"]
        )
        for item in test_data
    ]

    print(f"Created {len(documents)} test documents")
    return documents

async def save_store():
    table = 'test_table'
    schema = 'troc'
    id_column = 'id'
    _store = PgVectorStore(
        embedding_model=embed_model,
        dsn="postgresql+asyncpg://troc_pgdata:12345678@127.0.0.1:5432/navigator",
        dimension=768,
        table=table,
        schema=schema,
        id_column=id_column,
        embedding_column='embedding'
    )

    async with _store as store:
        documents = create_test_documents()
        print("Testing document addition...")

        try:
            # Add documents to the vector store
            added_ids = await store.add_documents(
                table=table,
                schema=schema,
                documents=documents
            )

            print(f"Successfully added {len(documents)} documents")
            return added_ids

        except Exception as e:
            print(f"Error adding documents: {e}")
            raise

async def test_store():
    table = 'test_table'
    schema = 'troc'
    id_column = 'id'
    _store = PgVectorStore(
        embedding_model=embed_model,
        dsn="postgresql+asyncpg://troc_pgdata:12345678@127.0.0.1:5432/navigator",
        dimension=768,
        table=table,
        schema=schema,
        id_column=id_column,
        embedding_column='embedding'
    )

    async with _store as store:
        # find similar documents
        """Test similarity search functionality."""
        print("\nTesting similarity search...")

        test_queries = [
            "programming languages and coding",
            "artificial intelligence and learning",
            "database systems and storage",
            "text processing and language"
        ]
        for query in test_queries:
            print(f"\n--- Searching for: '{query}' ---")
            try:
                # Perform similarity search
                results = await store.similarity_search(
                    query,
                    limit=3
                )
                print('RESULT > ', results)
                print(f"Found {len(results)} results:")
                # SearchResult objects
                for i, doc in enumerate(results, 1):
                    print(f"{i}. {doc.content[:100]}...")
                    print(f"   Metadata: {doc.metadata}")
                    print()

            except Exception as e:
                print('TYPE > ', type(e))
                print(
                    f"Error during search: {e}"
                )
            # repeat but using L2:
            try:
                results = await store.similarity_search(
                    query,
                    limit=5,
                    metric='L2',
                    score_threshold=1.5,
                    additional_columns=['created_at']
                )
                print('RESULT > ', results)
                print(f"Found {len(results)} results:")
                for i, doc in enumerate(results, 1):
                    print(f"{i}. {doc.content[:100]}...")
                    print(f"   Metadata: {doc.metadata}")
                    print(f"   Created At: {doc.metadata.get('created_at')}")

            except Exception as e:
                print('TYPE > ', type(e))
                print(
                    f"Error during search: {e}"
                )
            # Doing MMR relevance search:# Basic MMR search with balanced relevance/diversity
            results = await store.mmr_search(
                query=query,
                k=10,
                lambda_mult=0.5  # Balanced approach
            )
            print(f"Found {len(results)} results:")

            # More diverse results (less redundancy)
            diverse_results = await store.mmr_search(
                query=query,
                k=5,
                lambda_mult=0.3,  # Favor diversity
                fetch_k=50,       # Consider more candidates
                metadata_filters={"category": "research"}
            )
            print(f"Found {len(diverse_results)} diverse results:")

            # More relevant results (less diversity consideration)
            relevant_results = await store.mmr_search(
                query=query,
                k=8,
                lambda_mult=0.8,  # Favor relevance
                metric="COSINE"
            )
            print(f"Found {len(relevant_results)} relevant results:")

async def test_store_with_score():
    table = 'test_table'
    schema = 'troc'
    id_column = 'id'
    _store = PgVectorStore(
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
            "programming languages and coding",
            "artificial intelligence and learning",
            "database systems and storage",
            "text processing and language"
        ]
        for query in test_queries:
            print(f"\n--- Searching for: '{query}' ---")
            try:
                # Perform similarity search with scores
                results = await store.similarity_search_with_score(
                    query,
                    limit=3,
                    score_threshold=0.16
                )
                print(f"Found {len(results)} results:")
                for i, (doc, score) in enumerate(results, 1):
                    print(f"{i}. {doc.page_content[:100]}... (Score: {score})")
                    print(f"   Metadata: {doc.metadata}")
                    print()

            except Exception as e:
                print(f"Error during search: {e}")

async def drop_store():
    # clean up the store
    table = 'test_table'
    schema = 'troc'
    id_column = 'id'
    _store = PgVectorStore(
        embedding_model=embed_model,
        dsn="postgresql+asyncpg://troc_pgdata:12345678@127.0.0.1:5432/navigator",
        dimension=768,
        table=table,
        schema=schema,
        id_column=id_column,
        embedding_column='embedding'
    )
    async with _store as store:
        await store.drop_collection(table=table, schema=schema)


async def main():
    # await create_store()
    # await save_store()
    await test_store()
    # await test_store_with_score()
    # await drop_store()

if __name__ == "__main__":
    asyncio.run(main())
