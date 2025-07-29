import asyncio
from parrot.bots.chatbot import Chatbot

async def get_agent(agent_name: str):
    """Return the New Agent.
    """
    agent = Chatbot(
        name=agent_name,
        tools=['MathTool'],
        use_tools=True
    )
    await agent.configure()
    return agent

if __name__ == "__main__":
    # Test Connections created by bot
    loop = asyncio.get_event_loop()
    agent = loop.run_until_complete(
        get_agent('RFPBot')
    )
    print(
        'Agent: ', agent, agent.chatbot_id
    )
    # make a simple conversation request:
    response = loop.run_until_complete(
        agent.conversation("use the tool for calculate 245*38/3")
    )
    print('Response: ', response.output)
