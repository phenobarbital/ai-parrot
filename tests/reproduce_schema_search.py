from parrot.bots.db.abstract import AbstractDBAgent, TableMetadata, DatabaseSchema
import asyncio

class MockAgent(AbstractDBAgent):
    async def configure(self): pass
    async def connect_database(self): pass
    async def extract_schema_metadata(self): pass
    async def execute_query(self, query): pass
    async def explain_query(self, query): pass
    async def generate_query(self, *args, **kwargs): pass
    async def ask(self, *args, **kwargs): pass

async def main():
    agent = MockAgent(name="test")
    # Manually populate schema
    agent.schema_metadata = DatabaseSchema(
        database_name="test_db",
        database_type="postgres",
        tables=[
            TableMetadata(
                name="users",
                schema="auth",
                columns=[],
                primary_keys=[],
                foreign_keys=[],
                indexes=[]
            )
        ],
        views=[],
        functions=[],
        procedures=[],
        metadata={}
    )
    
    # Test 1: Search for simple name
    print(f"Searching for 'users'...")
    results = await agent.search_schema("users")
    print(f"Results for 'users': {len(results)}")
    
    # Test 2: Search for qualified name
    print(f"Searching for 'auth.users'...")
    results = await agent.search_schema("auth.users")
    print(f"Results for 'auth.users': {len(results)}")

    if len(results) == 0:
        print("FAILURE: 'auth.users' not found!")
    else:
        print("SUCCESS: 'auth.users' found!")

if __name__ == "__main__":
    asyncio.run(main())
