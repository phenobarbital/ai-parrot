import asyncio
from parrot.bots.jira_specialist import JiraSpecialist

async def main():
    agent = JiraSpecialist()
    await agent.configure()
    # call the method:
    response = await agent.extract_all_tickets(
        max_tickets=None,
        chunk_size=100,
        chunk_delay=2.0
    )

if __name__ == '__main__':
    asyncio.run(main())
    