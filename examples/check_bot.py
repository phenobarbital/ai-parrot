import asyncio
from parrot.bots.chatbot import Chatbot

async def get_agent(agent_name: str):
    """Return the New Agent.
    """
    agent = Chatbot(
        name=agent_name,
        tools=['MathTool'],
        use_tools=True,
        llm='groq',
        model="moonshotai/kimi-k2-instruct",
        # llm='claude',
        # model='claude-3-5-sonnet-20241022',
        # llm="openai",
        # model="gpt-4o",
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
        agent.conversation("use the tool for calculate (245*38/3)-5")
    )
    print('Response: ', response.output)
    print("Has tools:", response.has_tools)
    print("Tool calls:", [f"{tc.name}({tc.arguments}) = {tc.result}" for tc in response.tool_calls])
    print("Total execution time:", sum(tc.execution_time for tc in response.tool_calls))
