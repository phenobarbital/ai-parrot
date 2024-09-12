import asyncio
from parrot.chatbots.basic import Chatbot
from parrot.llms.vertex import VertexLLM


async def get_agent():
    """Return the New Agent.
    """
    llm = VertexLLM(
        model='gemini-1.5-pro',
        temperature=0.1,
        top_k=30,
        Top_p=0.6,
    )
    agent = Chatbot(
        name='AskBuddy',
        llm=llm
    )
    await agent.configure()
    # Create the Collection
    if agent.store.collection_exists('employee_information'):
        await agent.store.delete_collection('employee_information')
    await agent.store.create_collection(  # pylint: disable=E1120
        collection_name='employee_information',
        dimension=768,
        index_type="IVF_SQ8",
        metric_type='L2'
    )


if __name__ == "__main__":
    agent = asyncio.run(get_agent())
