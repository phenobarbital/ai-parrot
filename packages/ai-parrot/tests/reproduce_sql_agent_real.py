import asyncio
import os
import sys
import logging
import traceback
# from navconfig import config # Assuming this might be available, or we use defaults

from parrot.bots.db.sql import SQLAgent
from parrot.tools.databasequery import DatabaseQueryTool

# Setup basic logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Mock non-essential dependencies that might be missing in the environment
from unittest.mock import MagicMock
sys.modules['weasyprint'] = MagicMock()

async def main():
    print("🚀 Starting SQLAgent Real DB Test...")
    
    # Credentials setup (as per user instruction)
    # Using environment variables or defaults matching the user's snippet
    pg_user = os.getenv("PG_USER", "postgres")
    pg_password = os.getenv("PG_PASSWORD", "password")
    pg_host = os.getenv("PG_HOST", "localhost")
    pg_port = int(os.getenv("PG_PORT", 5432))
    pg_database = os.getenv("PG_DATABASE", "navigator")
    
    print(f"🕵️  Debug Credentials:")
    print(f"    User: {pg_user}")
    print(f"    Host: {pg_host}:{pg_port}")
    print(f"    Database: {pg_database}")
    print(f"    Password: {'*' * len(pg_password) if pg_password else 'NONE'} (first char: {pg_password[0] if pg_password else 'N/A'})")

    pg_credentials = {
        "host": pg_host,
        "port": pg_port,
        "database": pg_database,
        "username": pg_user,
        "password": pg_password
    }
    
    print(f"🔌 Credentials Object: {pg_credentials}")

    try:
        # Initialize SQLAgent
        agent = SQLAgent(
            name="RealTestAgent",
            credentials=pg_credentials,
            database_flavor="postgresql",
            schema_name="auth", # Targeting auth schema as per context
            max_sample_rows=2,
            tools=[DatabaseQueryTool()]
        )
        print("🔗 Configuring agent (and connecting)...")
        await agent.configure()
        print("✅ Configured!")
        
        # We don't need manual connect/extract if configure does it
        # But for debugging let's verify schema is populated
        if agent.schema_metadata:
             print(f"✅ Schema extracted. found {len(agent.schema_metadata.tables)} tables.")
        else:
             print("⚠️ Schema metadata empty after configure.")

        # Test Patterns and Roles
        roles = [
            # "business_user",
            # "data_analyst", 
            # "data_scientist", 
            # "database_admin", 
            # "developer", 
            "query_developer"
        ]
        
        queries = [
            # ("Show me data from auth.users", "SHOW_DATA"),
            ("Generate a query for auth.users", "GENERATE_QUERY"),
            # ("What columns are in auth.users?", "EXPLORE_SCHEMA"),
            ("Explain select * from auth.users", "EXPLAIN_QUERY"),
            ("Optimize select * from auth.users", "OPTIMIZE_QUERY"),
            #("Analyze user registration trends", "ANALYZE_DATA")
        ]

        for role in roles:
            print(f"\n👤 === Testing User Role: {role} ===")
            for query_text, pattern in queries:
                print(f"\n  ❓ Query [{pattern}]: {query_text}")
                try:
                    response = await agent.ask(
                        question=query_text,
                        user_context=f"User Role: {role}", # Passing role as context since user_role might not be expected
                        return_results=True # Try to execute if possible
                    )
                    print(f"  👉 Response Type: {type(response)}")
                    if hasattr(response, 'metadata'):
                        print(f"     Components: {response.metadata.get('components', 'N/A')}")
                        print(f"     Intent: {response.metadata.get('intent', 'N/A')}")
                    
                except Exception as e:
                    print(f"  ❌ Error asking agent: {e}")
                    traceback.print_exc()

    except Exception as e:
        print(f"❌ Critical Error during setup: {e}")
        traceback.print_exc()
    finally:
        if 'agent' in locals():
            # Cleanup if needed (AbstractDBAgent doesn't always have cleanup but good practice)
            pass

if __name__ == "__main__":
    asyncio.run(main())
