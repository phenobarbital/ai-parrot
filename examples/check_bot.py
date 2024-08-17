import asyncio
from pymilvus import connections
from parrot.chatbots.basic import Chatbot
from parrot.llms.groq import GroqLLM



_HOST = '127.0.0.1'
_PORT = '19530'

def create_connection():
    print(f"\nCreate connection...")
    connections.connect('test', host=_HOST, port=_PORT)
    print(f"\nList connections:")
    print(connections.list_connections())
    connections.disconnect('test')

async def get_agent(agent_name: str):
    """Return the New Agent.
    """
    llm = GroqLLM(
        model="llama3-groq-70b-8192-tool-use-preview",
        temperature=0.1,
        top_k=30,
        Top_p=0.6,
    )
    agent = Chatbot(
        name=agent_name,
        llm=llm
    )
    await agent.configure()
    return agent

if __name__ == "__main__":
    # Test Connections created by bot
    create_connection()
    loop = asyncio.get_event_loop()
    agent = loop.run_until_complete(
        get_agent('RFPBot')
    )
    print(
        'Agent: ', agent, agent.chatbot_id
    )
    create_connection()
