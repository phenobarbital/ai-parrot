import asyncio
import os
import sys
from typing import Optional, Dict, Any, List
from unittest.mock import MagicMock, AsyncMock

# Adjust path to include project root
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Mock navconfig before importing parrot
mock_navconfig = MagicMock()
mock_navconfig.logging = MagicMock()
mock_navconfig.logging.logging = MagicMock()
sys.modules['navconfig'] = mock_navconfig
sys.modules['navconfig.logging'] = mock_navconfig.logging
sys.modules['navconfig.exceptions'] = MagicMock()

# Additional aggressive mocks to bypass environment issues
mock_querysource = MagicMock()
sys.modules['querysource'] = mock_querysource
sys.modules['querysource.conf'] = MagicMock()

mock_nav_auth = MagicMock()
sys.modules['navigator_auth'] = mock_nav_auth
sys.modules['navigator_auth.conf'] = MagicMock()
sys.modules['navigator_auth.decorators'] = MagicMock()
sys.modules['navigator_auth.handlers'] = MagicMock()

sys.modules['navigator_session'] = MagicMock()
sys.modules['datamodel'] = MagicMock()
sys.modules['datamodel.parsers'] = MagicMock()
sys.modules['datamodel.parsers.json'] = MagicMock()
sys.modules['datamodel.exceptions'] = MagicMock()
sys.modules['datamodel.exceptions'].ParserError = Exception
sys.modules['datamodel.models'] = MagicMock()
sys.modules['datamodel.abstract'] = MagicMock()
sys.modules['datamodel.types'] = MagicMock()

# Mock asyncdb to stop dependency chain
sys.modules['asyncdb'] = MagicMock()
sys.modules['asyncdb.models'] = MagicMock()
sys.modules['asyncdb.exceptions'] = MagicMock()

# Mock optional/heavy dependencies causing import chains
sys.modules['pytesseract'] = MagicMock()
sys.modules['cv2'] = MagicMock()

mock_pil = MagicMock()
sys.modules['PIL'] = mock_pil
sys.modules['PIL.PngImagePlugin'] = MagicMock()
sys.modules['PIL.Image'] = MagicMock()

# Mock LLM libraries with submodules
sys.modules['openai'] = MagicMock()
sys.modules['openai.types'] = MagicMock()
sys.modules['openai.types.chat'] = MagicMock()

sys.modules['anthropic'] = MagicMock()
sys.modules['anthropic.types'] = MagicMock()

sys.modules['google'] = MagicMock()
sys.modules['google.genai'] = MagicMock()
sys.modules['google.genai.types'] = MagicMock()
sys.modules['google.generativeai'] = MagicMock()
sys.modules['google.generativeai.types'] = MagicMock()
sys.modules['google.auth'] = MagicMock()
sys.modules['google.oauth2'] = MagicMock()

# Mock other potential missing clients/libs
sys.modules['xai_sdk'] = MagicMock()
sys.modules['xai_sdk.chat'] = MagicMock()
sys.modules['mcp'] = MagicMock()
sys.modules['mcp.types'] = MagicMock()
sys.modules['sse_starlette'] = MagicMock()
sys.modules['sse_starlette.sse'] = MagicMock()
sys.modules['requests_oauthlib'] = MagicMock()
sys.modules['folium'] = MagicMock()
sys.modules['branca'] = MagicMock()

# Mock text/PDF/token libraries
sys.modules['tiktoken'] = MagicMock()
sys.modules['fpdf'] = MagicMock()
sys.modules['pdf2image'] = MagicMock()
sys.modules['pdfminer'] = MagicMock()
sys.modules['pdfminer.high_level'] = MagicMock()
sys.modules['bs4'] = MagicMock()
sys.modules['networkx'] = MagicMock()
sys.modules['markdown'] = MagicMock()
sys.modules['markdown2'] = MagicMock()
sys.modules['psycopg2'] = MagicMock()
sys.modules['aiohttp_sse_client'] = MagicMock()
sys.modules['jira'] = MagicMock()
sys.modules['selenium'] = MagicMock()
sys.modules['undetected_chromedriver'] = MagicMock()
sys.modules['aioquic'] = MagicMock()
sys.modules['aioquic.asyncio'] = MagicMock()
sys.modules['aioquic.asyncio.server'] = MagicMock()
sys.modules['aioquic.quic'] = MagicMock()
sys.modules['aioquic.quic.configuration'] = MagicMock()
sys.modules['aioquic.quic.events'] = MagicMock()
sys.modules['aioquic.tls'] = MagicMock()
sys.modules['aioquic.h3'] = MagicMock()
sys.modules['aioquic.h3.connection'] = MagicMock()
sys.modules['aioquic.h3.events'] = MagicMock()
sys.modules['pylsqpack'] = MagicMock()
sys.modules['aiohttp_swagger3'] = MagicMock()
sys.modules['yaml'] = MagicMock()
sys.modules['notify'] = MagicMock()
sys.modules['notify.models'] = MagicMock()
sys.modules['notify.providers'] = MagicMock()
sys.modules['notify.providers.email'] = MagicMock()
sys.modules['notify.providers.slack'] = MagicMock()
sys.modules['notify.providers.telegram'] = MagicMock()
sys.modules['notify.providers.teams'] = MagicMock()

# Also mock imports that might come from parrot.bots.abstract
sys.modules['pytector'] = MagicMock()
sys.modules['navigator_api'] = MagicMock()

mock_navigator = MagicMock()
sys.modules['navigator'] = mock_navigator
sys.modules['navigator.conf'] = MagicMock()
sys.modules['navigator.views'] = MagicMock()

# Mock compiled extensions that might mismatch python version
mock_exceptions = MagicMock()
mock_exceptions.ConfigError = Exception
sys.modules['parrot.exceptions'] = mock_exceptions

sys.modules['parrot.utils'] = MagicMock()
mock_utils_types = MagicMock()
mock_utils_types.SafeDict = dict
sys.modules['parrot.utils.types'] = mock_utils_types

# Manually stub parrot.utils in case it was already imported partially
import types
utils_module = types.ModuleType('parrot.utils')
utils_module.types = mock_utils_types
utils_module.SafeDict = dict
sys.modules['parrot.utils'] = utils_module

mock_helpers = MagicMock()
sys.modules['parrot.utils.helpers'] = mock_helpers
utils_module.helpers = mock_helpers

# Mock handlers.models to provide a real class for type hinting
mock_handlers_models = MagicMock()
class PseudoBotModel:
    pass
mock_handlers_models.BotModel = PseudoBotModel
sys.modules['parrot.handlers.models'] = mock_handlers_models

from parrot.bots.database.sql import SQLAgent
from parrot.bots.database.models import UserRole, QueryIntent
from parrot.bots.database.models import TableMetadata

async def run_test():
    print("=" * 80)
    print(" SQLAgent Comprehensive Test (Patterns & Roles)")
    print("=" * 80)

    # 1. Setup SQLAgent
    # Try with default local credentials, but fallback to mocking if connection fails
    dsn = "postgresql+asyncpg://postgres:postgres@localhost:5432/postgres"
    
    print(f"Initializing SQLAgent with DSN: {dsn}")
    
    agent = SQLAgent(
        dsn=dsn,
        allowed_schemas=["public", "auth"],
        primary_schema="auth",
        auto_analyze_schema=False, # We will mock or trigger manually
        debug=True
    )

    # Mock the LLM to avoid API calls and ensure deterministic output
    mock_llm = MagicMock()
    mock_llm.tool_manager = MagicMock()
    # Mock ask to return a dummy Agent message
    async def mock_ask(prompt, **kwargs):
        return f"LLM Response to: {prompt[:50]}..."
    mock_llm.ask = AsyncMock(side_effect=mock_ask)
    agent._llm = mock_llm

    # Mock DB Connection to guarantee run without real DB
    print("\n[Setup] Mocking Database Engine and Schema Tool for reliability...")
    agent.engine = MagicMock()
    agent.session_maker = MagicMock()
    
    # Mock Schema Tool
    mock_schema_tool = AsyncMock()
    
    # Mock Table Metadata for 'auth.users'
    users_table = TableMetadata(
        schema="auth",
        tablename="users",
        table_type="BASE TABLE",
        full_name='"auth"."users"',
        columns=[
            {"name": "id", "type": "uuid", "nullable": False},
            {"name": "email", "type": "varchar", "nullable": True},
            {"name": "created_at", "type": "timestamp", "nullable": False}
        ],
        primary_keys=["id"],
        row_count=100
    )
    
    mock_schema_tool.get_table_details.return_value = users_table
    mock_schema_tool.search_schema.return_value = [users_table]
    mock_schema_tool.analyze_all_schemas.return_value = {"auth": 1, "public": 0}
    
    agent.schema_tool = mock_schema_tool
    agent.schema_analyzed = True
    
    # Mock Metadata Cache
    agent.metadata_cache = AsyncMock()
    agent.metadata_cache.get_table_metadata.return_value = users_table
    agent.metadata_cache.get_hot_tables.return_value = [("auth", "users", 10)]

    # Mock _process_query to avoid complicated internal logic and just return route info
    # We want to test routing and role logic primarily
    original_process_query = agent._process_query
    
    async def mocked_process_query(*args, **kwargs):
        route = kwargs.get('route')
        return {
            "query": "SELECT * FROM auth.users LIMIT 5", 
            "data": [{"id": 1, "email": "test@example.com"}],
            "execution_plan": "Seq Scan on users...",
            "components_included": route.components
        }, "LLM Explanation"

    agent._process_query = AsyncMock(side_effect=mocked_process_query)


    # 2. Test Loop
    roles = [
        UserRole.BUSINESS_USER,
        UserRole.DATA_ANALYST,
        UserRole.DATA_SCIENTIST,
        UserRole.DATABASE_ADMIN,
        UserRole.DEVELOPER,
        UserRole.QUERY_DEVELOPER
    ]

    patterns = [
        ("SHOW_DATA", "Show me the first 5 users"),
        ("GENERATE_QUERY", "Get users created last month"),
        ("EXPLORE_SCHEMA", "What columns are in auth.users?"),
        ("EXPLAIN_METADATA", "Describe the auth.users table"),
        ("OPTIMIZE_QUERY", "Optimize select * from auth.users"),
        ("ANALYZE_DATA", "Analyze user registration trends")
    ]

    for role in roles:
        print(f"\n\n🔶 Testing Role: {role.value.upper()}")
        print("-" * 60)
        
        for intent_name, query in patterns:
            print(f"\n  🔹 Pattern: {intent_name}")
            print(f"     Query: {query}")
            
            try:
                # We call ask() but we are mainly interested in the ROUTING decision
                # which happens inside. To see it, we can inspect the call to query_router.route
                # OR we can inspect the logger if configured.
                # Since we mocked _process_query, we can trust that ask() reaches that point 
                # if routing succeeds.
                
                # Check what route the router produces
                route = await agent.query_router.route(query, role)
                print(f"     ✅ Route Intent: {route.intent}")
                print(f"     ✅ Components : {route.components}")
                
                # Execute ask to ensure end-to-end flow works (even with mocks)
                response = await agent.ask(query, user_role=role)
                
                print(f"     ✅ Agent Response Type: {type(response)}")
                
            except Exception as e:
                print(f"     ❌ FAILED: {e}")
                import traceback
                traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(run_test())
