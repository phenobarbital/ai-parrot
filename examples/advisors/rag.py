import asyncio
from parrot.bots.basic import BasicBot


async def get_agent():
    agent = BasicBot(
        name='AskGorilla',
        llm="google:gemini-2.5-flash",
        max_tokens=8912,
        temperature=0.2,
        backstory="""
You are an AI assistant that helps users find products from Gorilla Shed's
catalog. Use the product information provided to answer user queries accurately.
        """
    )
    embed_model = {
        "model": "BAAI/bge-base-en-v1.5",
        "model_type": "huggingface"
    }
    agent.define_store(
        vector_store='postgres',
        embedding_model=embed_model,
        dsn="postgresql+asyncpg://troc_pgdata:12345678@127.0.0.1:5432/navigator",
        dimension=768,
        table='products',
        schema='gorillashed',
    )
    await agent.configure()
    return agent


async def ask_agent(agent, question, memory):
    user_id = 35  # Example user ID
    session_id = "session_456"  # Example session ID
    return await agent.ask(
        user_id=user_id,
        session_id=session_id,
        question=question,
        search_type='ensemble',
        memory=memory
    )

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    agent = loop.run_until_complete(get_agent())
    query = input("Type in your query: \n")
    EXIT_WORDS = ["exit", "quit", "bye"]
    memory = agent.get_conversation_memory(
        storage_type='memory'
    )
    while query not in EXIT_WORDS:
        if query:
            response = loop.run_until_complete(
                ask_agent(agent, query, memory)
            )
            print('::: Response: ', response.response)
        query = input("Type in your query: \n")
