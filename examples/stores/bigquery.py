import asyncio
from parrot.stores.bigquery import BigQueryStore
from parrot.stores.models import Document

async def test_store():
    # Initialize the store
    bq = BigQueryStore(
        dataset="vectors",
        table="documents",
        embedding_model="sentence-transformers/all-mpnet-base-v2"
    )

    # create the dataset if it doesn't exist
    async with bq as store:
        if not await store.dataset_exists('vectors'):
            await store.create_dataset('vectors')

        # Create a collection
        await store.create_collection("my_docs", dimension=768)

        # Add documents
        documents = [Document(page_content="Hello world", metadata={"type": "greeting"})]
        await store.add_documents(documents, table="my_docs")

        # Search
        results = await store.similarity_search("hello", table="my_docs", limit=5)
        print('Search results:', results)

        # Drop the collection
        await store.drop_collection("my_docs")


if __name__ == "__main__":
    asyncio.run(test_store())
    # This will run the test_store function when the script is executed
