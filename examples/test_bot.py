import asyncio
from parrot.bots.basic import BasicBot
from parrot.llms.groq import GroqLLM
from parrot.llms.vertex import VertexLLM

async def get_agent():
    """Return the New Agent.
    """
    llm = GroqLLM(
        model="llama3-groq-70b-8192-tool-use-preview",
        temperature=0.1,
        top_k=30,
        Top_p=0.6,
    )
    llm = VertexLLM(
        model='gemini-1.5-pro',
        temperature=0.1,
        top_k=30,
        Top_p=0.5,
    )
    agent = BasicBot(
        name='Oddie',
        llm=llm
    )
    await agent.configure()
    return agent


async def ask_agent(agent, question, memory):
    return await agent.conversation(
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
    try:
        while query not in EXIT_WORDS:
            if query:
                    response = loop.run_until_complete(
                        ask_agent(agent, query, memory)
                    )
                    print('::: Response: ', response)

            query = input("Type in your query: \n")
    except KeyboardInterrupt:
        print("KeyboardInterrupt received. Shutting down...")
    finally:
        loop = asyncio.get_event_loop()
        loop.run_until_complete(agent.shutdown())
        loop.close()
