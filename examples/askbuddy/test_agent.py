import asyncio
from contextlib import asynccontextmanager
from parrot.bots import Agent
from parrot.stores.kb.user import UserInfo
from parrot.stores.kb.hierarchy import EmployeeHierarchyKB
from parrot.interfaces.hierarchy import EmployeeHierarchyManager

facts = [
    {
        "content": "Our CEO is Brett Beveridge",
        "metadata": {
            "category": "organization",
            "entity_type": "person",
            "role": "leadership",
            "validated_date": "2024-01-15",
            "confidence": 1.0,
            "source": "HR_database",
            "tags": ["ceo", "executive", "Brett", "leadership"]
        }
    },
    {
        "content": "The company headquarters is located in Doral, Florida",
        "metadata": {
            "category": "organization",
            "entity_type": "location",
            "confidence": 1.0,
            "tags": ["headquarters", "location", "doral", "florida"]
        }
    },
    {
        "content": "Our fiscal year ends on December 31st",
        "metadata": {
            "category": "finance",
            "entity_type": "policy",
            "confidence": 1.0,
            "tags": ["fiscal", "finance", "calendar"]
        }
    }
]

@asynccontextmanager
async def managed_agent(agent):
    """Context manager for agent lifecycle management."""
    try:
        await agent.configure()
        yield agent
    finally:
        # Cleanup agent resources
        await agent.cleanup()

async def get_agent():
    pse = EmployeeHierarchyManager(
        arango_host='localhost',
        arango_port=8529,
        db_name='navigator',
        username='root',
        password='12345678',
        pg_employees_table='troc.troc_employees'
    )
    agent = Agent(
        name='AskBuddy',
        use_kb=True,
        kb=facts,
        use_kb_selector=True,
    )
    # adding an specialized KB (user information)
    agent.register_kb(UserInfo())
    agent.register_kb(
        EmployeeHierarchyKB(
            permission_service=pse,
            always_active=True
        )
    )
    embed_model = {
        "model": "thenlper/gte-base",
        "model_type": "huggingface"
    }
    agent.define_store(
        vector_store='postgres',
        embedding_model=embed_model,
        dsn="postgresql+asyncpg://troc_pgdata:12345678@127.0.0.1:5432/navigator",
        dimension=768,
        table='employee_information',
        schema='mso',
    )
    await agent.configure()
    return agent


async def ask_agent(agent, question, memory):
    user_id = 35  # Example user ID
    session_id= "session_456"  # Example session ID
    return await agent.conversation(
        user_id=user_id,
        session_id=session_id,
        question=question,
        search_type='ensemble',
        memory=memory
    )

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    try:
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
    finally:
        loop.run_until_complete(agent.cleanup())
        loop.close()
