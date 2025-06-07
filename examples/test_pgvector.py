"""
Test script for custom PgVectorStore functionality.
Tests table creation, document insertion, and similarity search.
"""

import asyncio
import uuid
from typing import List
from sqlalchemy import text
from langchain_core.documents import Document
from parrot.stores.postgres import PgvectorStore



embed_model = {
    "model": "thenlper/gte-base",
    "model_type": "transformers"
}

async def create_store():
    table = 'test_table'
    schema = 'troc'
    id_column = 'id'
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
            tablename = f"{schema}.{table}"
            await store.prepare_embedding_table(
                tablename=tablename,
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
        documents = create_test_documents()
        print("Testing document addition...")

        try:
            # Add documents to the vector store
            added_ids = await store.add_documents(documents)

            print(f"Successfully added {len(documents)} documents")
            return added_ids

        except Exception as e:
            print(f"Error adding documents: {e}")
            raise

if __name__ == "__main__":
    # asyncio.run(create_store())
    asyncio.run(save_store())
    # asyncio.run(test_store())
