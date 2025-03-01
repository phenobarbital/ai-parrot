import asyncio
from langchain.docstore.document import Document
from navconfig import BASE_DIR
from parrot.stores.faiss import FaissStore
from parrot.stores.chroma import ChromaStore
from parrot.stores.duck import DuckDBStore
from parrot.stores.postgres import PgvectorStore


embed_model = {
    "model_name": "sentence-transformers/all-mpnet-base-v2",
    "model_type": "transformers"
}

async def test_store(use: str):
    _store = None
    if use == 'faiss':
        _store = FaissStore(index_path=BASE_DIR.joinpath("faiss_index"), embedding_model=embed_model)
    if use == 'chroma':
        _store = ChromaStore(embedding_model=embed_model, ephemeral=True)
    if use == 'duck':
        _store = DuckDBStore(embedding_model=embed_model, database=":memory:")
    if use == 'postgres':
        _store = PgvectorStore(embedding_model=embed_model, dsn="postgresql+asyncpg://troc_pgdata:12345678@127.0.0.1:5432/navigator", drop=True)
    print('Store selected: ', _store)
    # Create two LangChain documents
    doc1 = Document(page_content="LangChain is a framework for building language models.")
    doc2 = Document(page_content="Milvus is a vector database for efficient similarity search.")
    doc3 = Document(page_content="Langchain works with Milvus.")
    # Create a list of documents
    documents = [doc1, doc2, doc3]
    async with _store:
        # Add documents to the store
        await _store.add_documents(documents)
        # Perform similarity search
        query = "Language models and databases"
        results = await _store.similarity_search(query, limit=2)
        for result in results:
            print(result)

if __name__ == "__main__":
    asyncio.run(test_store(use='postgres'))
