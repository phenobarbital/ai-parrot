import asyncio
from parrot.bots.basic import BasicBot

facts = [
    {
        "content": "Our CEO is Buddy White",
        "metadata": {
            "category": "organization",
            "entity_type": "person",
            "role": "leadership",
            "validated_date": "2024-01-15",
            "confidence": 1.0,
            "source": "HR_database",
            "tags": ["ceo", "executive", "buddy", "leadership"]
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

async def get_agent():
    agent = BasicBot(
        name='AskBuddy',
        use_kb=True,
        kb=facts
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
    user_id= "user_123"  # Example user ID
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
