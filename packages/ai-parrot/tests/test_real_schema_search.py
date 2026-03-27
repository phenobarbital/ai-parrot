import asyncio
import os
import logging
from parrot.bots.db.sql import SQLAgent
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def main():
    # Get credentials from env
    credentials = {
        "user": os.getenv("PG_USER", "postgres"),
        "password": os.getenv("PG_PASSWORD", "postgres"),
        "host": os.getenv("PG_HOST", "localhost"),
        "port": os.getenv("PG_PORT", "5432"),
        "database": os.getenv("PG_DATABASE", "navigator")
    }

    agent = SQLAgent(
        name="RealSQLAgent",
        credentials=credentials,
        database_flavor="postgresql",
        schema_name="public"
    )

    await agent.configure()

    print("\n--- Testing Schema Search ---\n")

    # Test 1: Search for 'users' (simple name)
    print("Search: 'users'")
    results = await agent.search_schema("users")
    print(f"Results: {len(results)}")
    for r in results:
        print(f" - {r['type']}: {r.get('schema', '')}.{r['name']}")

    # Test 2: Search for 'auth.users' (qualified name)
    print("\nSearch: 'auth.users'")
    results = await agent.search_schema("auth.users")
    print(f"Results: {len(results)}")
    for r in results:
        print(f" - {r['type']}: {r.get('schema', '')}.{r['name']}")

    # Test 2b: Search for 'auth.users' AGAIN (should hit cache)
    print("\nSearch: 'auth.users' (AGAIN - Expecting Cache Hit)")
    start_time = asyncio.get_event_loop().time()
    results = await agent.search_schema("auth.users")
    end_time = asyncio.get_event_loop().time()
    print(f"Results: {len(results)} (Time: {end_time - start_time:.4f}s)")
    for r in results:
        print(f" - {r['type']}: {r.get('schema', '')}.{r['name']}")

    # Test 3: Search for 'email' (column name)
    print("\nSearch: 'email'")
    results = await agent.search_schema("email", search_type="columns")
    print(f"Results: {len(results)}")
    for r in results:
        print(f" - {r['type']}: {r.get('schema', '')}.{r.get('table', '')}.{r['name']}")
    
    await agent.cleanup()

if __name__ == "__main__":
    asyncio.run(main())
