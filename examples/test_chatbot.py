import asyncio
from parrot.bots.troc import AskTROC
from parrot.llms.vertex import VertexLLM

vertex = VertexLLM(
    model="gemini-2.0-flash-001",
    temperature=0.2,
    top_k=30,
    Top_p=0.5,
)

async def get_agent(llm):
    """Return the New Agent.
    """
    agent = AskTROC(
        name='AskPage',
        llm=llm,
        use_vectorstore=True,
    )
    await agent.configure()
    return agent

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    agent = loop.run_until_complete(
        get_agent(llm=vertex)
    )
    print("=== AskPage Chatbot Ready ===")
    print("- Type 'exit', 'quit', or 'bye' to end the session\n")
    query = input(":: Type in your query: \n")
    EXIT_WORDS = ["exit", "quit", "bye"]
    while query not in EXIT_WORDS:
        if query:
            response = loop.run_until_complete(
                agent.conversation(
                    question=query,
                    search_kwargs={"k": 10},
                    memory=agent.get_memory(key='chat_history')
                )
            )
            print('::: Response: ', response)
        query = input("Type in your query: \n")
