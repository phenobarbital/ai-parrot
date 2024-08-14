import asyncio
from parrot.chatbots.basic import Chatbot
from parrot.llms.groq import GroqLLM
from parrot.llms.vertex import VertexLLM

async def get_agent():
    """Return the New Agent.
    """
    # llm = GroqLLM(
    #     model="llama3-groq-70b-8192-tool-use-preview",
    #     temperature=0.1,
    #     top_k=30,
    #     Top_p=0.6,
    # )
    llm = VertexLLM(
        model='gemini-1.5-flash-001',
        temperature=0.1,
        top_k=30,
        Top_p=0.5,
    )
    agent = Chatbot(
        name='RFPBot',
        # llm=llm
    )
    await agent.configure()
    return agent


async def ask_agent(retrieval, question, memory):
    return await retrieval.question(
        question=question,
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
                    ask_agent(retrieval, query, memory)
                )
                print('::: Response: ', response.response)

        query = input("Type in your query: \n")
