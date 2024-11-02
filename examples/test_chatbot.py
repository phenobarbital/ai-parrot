import asyncio
from parrot.bots.asktroc import AskTROC
from parrot.llms.vertex import VertexLLM

async def get_agent():
    """Return the New Agent.
    """
    llm = VertexLLM(
        model='gemini-1.5-pro',
        temperature=0.2,
        top_k=30,
        Top_p=0.5,
    )
    agent = AskTROC(
        name='AskPage',
        llm=llm
    )
    await agent.configure()
    return agent


async def ask_agent(retrieval, question, memory):
    return await retrieval.conversation(
        question=question,
        search_kwargs={"k": 10},
        memory=memory
    )

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    agent = loop.run_until_complete(get_agent())
    query = input("Type in your query: \n")
    EXIT_WORDS = ["exit", "quit", "bye"]
    memory = agent.get_memory(key='chat_history')
    while query not in EXIT_WORDS:
        if query:
            with agent.get_retrieval() as retrieval:
                response = loop.run_until_complete(
                    ask_agent(agent, query, memory)
                )
                print('::: Response: ', response)
        query = input("Type in your query: \n")
