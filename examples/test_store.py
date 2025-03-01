import asyncio
from langchain.docstore.document import Document
from navconfig import BASE_DIR
from parrot.stores.faiss import FaissStore


embed_model = {
    "model_name": "sentence-transformers/all-mpnet-base-v2",
    "model_type": "transformers"
}

async def test_store():
    faiss_store = FaissStore(index_path=BASE_DIR.joinpath("faiss_index"), embedding_model=embed_model)
    # Create two LangChain documents
    doc1 = Document(page_content="LangChain is a framework for building language models.")
    doc2 = Document(page_content="Milvus is a vector database for efficient similarity search.")
    doc3 = Document(page_content="Langchain works with Milvus.")
    # Create a list of documents
    documents = [doc1, doc2, doc3]
    async with faiss_store:
        # Add documents to the store
        await faiss_store.add_documents(documents)
        # Perform similarity search
        query = "Language models and databases"
        results = await faiss_store.similarity_search(query, limit=2)
        for result in results:
            print(result)

if __name__ == "__main__":
    asyncio.run(test_store())
