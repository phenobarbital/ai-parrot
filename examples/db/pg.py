"""
Comprehensive SQLAgent Example with PostgreSQL (No Vector Store)
================================================================

This example demonstrates how to use AI-Parrot's SQLAgent with PostgreSQL
credentials without vector store support for database introspection and
natural language querying.
"""
from typing import Dict, Any, Optional
import os
import asyncio
import pandas as pd
from navconfig import config
from querysource.conf import async_database_url
from parrot.bots.db.sql import SQLAgent, create_sql_agent


async def main():
    """Main example showcasing SQLAgent capabilities."""

    # =============================================
    # 1. CONFIGURATION AND INITIALIZATION
    # =============================================

    # PostgreSQL credentials as dictionary (matching your format)
    pg_credentials = {
        "host": os.getenv("PG_HOST", "localhost"),
        "port": int(os.getenv("PG_PORT", 5432)),
        "database": os.getenv("PG_DATABASE", "navigator"),
        "username": os.getenv("PG_USER", "postgres"),  # Note: use 'username' not 'user'
        "password": os.getenv("PG_PASSWORD", "password")
    }

    # Alternative: Connection string format
    connection_string = async_database_url

    print("🚀 Initializing SQLAgent with PostgreSQL...")

    # Create SQLAgent without vector store (knowledge_store=None by default)
    sql_agent = SQLAgent(
        name="NavigatorDatabaseAgent",
        credentials=connection_string,  # Use dict credentials
        database_flavor="postgresql",
        schema_name="auth",  # Default PostgreSQL schema
        max_sample_rows=3,  # Limit sample data for faster analysis
        knowledge_store=None,  # Explicitly disable vector store
        auto_analyze_schema=True,  # Analyze schema on initialization
        cache_ttl=3600,  # Cache schema metadata for 1 hour
        # LLM configuration (example)
        llm_client='openai',
        default_model='gpt-4o',
        temperature=0.0,  # Consistent results for database operations
        max_tokens=8192,
        debug=True, # Enable for detailed logging
    )

    # Alternative factory method
    # sql_agent = create_sql_agent(
    #     database_flavor='postgresql',
    #     credentials=connection_string,
    #     schema_name='public'
    # )

    try:
        # Initialize database connection and schema analysis
        print("📊 Connecting to database and analyzing schema...")
        await sql_agent.configure()  # This calls initialize_schema() internally

        print(
            f"✅ Connected to database: {sql_agent.schema_metadata.database_name}"
        )
        print(
            f"📋 Found {len(sql_agent.schema_metadata.tables)} tables"
        )

        # =============================================
        # 2. SCHEMA EXPLORATION
        # =============================================

        await schema_exploration_examples(sql_agent)

        # =============================================
        # 3. NATURAL LANGUAGE QUERYING
        # =============================================

        await natural_language_examples(sql_agent)

        # =============================================
        # 4. MANUAL QUERY GENERATION AND EXECUTION
        # =============================================

        await manual_query_examples(sql_agent)

        # =============================================
        # 5. ADVANCED USAGE PATTERNS
        # =============================================

        await advanced_usage_examples(sql_agent)

        # =============================================
        # 6. ERROR HANDLING EXAMPLES
        # =============================================

        await error_handling_examples(sql_agent)

    except Exception as e:
        print(f"❌ Error during initialization: {e}")
        print("💡 Please check your database credentials and connectivity")

    finally:
        # Always cleanup resources
        print("🧹 Cleaning up resources...")
        await sql_agent.cleanup()
        print("✅ Cleanup completed")


async def schema_exploration_examples(sql_agent: SQLAgent):
    """Demonstrate schema exploration capabilities."""

    print("\n" + "="*50)
    print("📊 SCHEMA EXPLORATION EXAMPLES")
    print("="*50)

    # 1. Search for tables containing specific terms
    print("\n1. Searching for tables containing 'user':")
    user_tables = await sql_agent.search_schema(
        search_term="user",
        search_type="tables",
        limit=5
    )

    for table in user_tables:
        print(f"   📋 Table: {table.get('name', 'Unknown')}")
        if 'content' in table:
            # Print first few lines of table schema
            lines = table['content'].split('\n')[:3]
            for line in lines:
                print(f"      {line}")

    # 2. Search for specific columns
    print("\n2. Searching for columns containing 'email':")
    email_columns = await sql_agent.search_schema(
        search_term="email",
        search_type="columns",
        limit=3
    )

    for column in email_columns:
        if column.get('type') == 'column':
            print(
                f"   📄 Column: {column.get('table_name')}.{column.get('column_name')} ({column.get('column_type')})"
            )

    # 3. Get database metadata summary
    print("\n3. Database metadata summary:")
    if sql_agent.schema_metadata:
        metadata = sql_agent.schema_metadata.metadata
        print(f"   🗄️  Database: {sql_agent.schema_metadata.database_name}")
        print(f"   📊 Total tables: {metadata.get('total_tables', 0)}")
        print(f"   🔍 Schema analyzed: {metadata.get('schema_name')}")
        print(f"   ⏰ Last analyzed: {metadata.get('extraction_timestamp', 'Unknown')}")


async def natural_language_examples(sql_agent: SQLAgent):
    """Demonstrate natural language querying with automatic execution."""

    print("\n" + "="*50)
    print("💬 NATURAL LANGUAGE QUERYING EXAMPLES")
    print("="*50)

    # Example queries (adjust based on your actual database schema)
    natural_queries = [
        "Show me the structure of all tables in the database",
        "List the first 5 rows from any user-related table",
        "What are the column names and types for tables that might contain user information?",
        "Show me some sample data from the largest table in the database",
        "Count the total number of records in each table"
    ]

    for i, query in enumerate(natural_queries, 1):
        print(f"\n{i}. Query: '{query}'")
        print("   " + "-"*60)

        try:
            # Ask with automatic query execution
            response = await sql_agent.ask(
                prompt=query,
                user_context="I'm a data analyst exploring this database for the first time.",
                context="Focus on providing clear, readable results with explanations.",
                return_results=True,  # Automatically execute generated queries
                session_id=f"example_session_{i}",
                user_id="data_analyst_user"
            )

            # Print the explanation
            print(f"   💭 Explanation: {response.response}")

            # If there's data, show sample
            if response.output is not None and hasattr(response.output, 'head'):
                print(f"   📊 Sample data ({len(response.output)} rows):")
                print("      " + str(response.output.head(3)).replace('\n', '\n      '))
            elif response.output:
                print(f"   📊 Result: {response.output}")

            # Show any metadata about execution
            if hasattr(response, 'metadata') and response.metadata:
                if response.metadata.get('executed_query'):
                    print(f"   🔍 Executed query: {response.metadata['executed_query'][:100]}...")

        except Exception as e:
            print(f"   ❌ Error: {e}")


async def manual_query_examples(sql_agent: SQLAgent):
    """Demonstrate manual query generation and execution."""

    print("\n" + "="*50)
    print("🔧 MANUAL QUERY GENERATION & EXECUTION")
    print("="*50)

    # 1. Generate query without execution
    print("\n1. Generating query for schema information:")

    query_request = "Get information about all tables including their column counts"

    try:
        query_result = await sql_agent.generate_query(
            natural_language_query=query_request,
            query_type="SELECT"
        )

        print(f"   📝 Generated query:")
        print(f"      {query_result['query']}")
        print(f"   ✅ Validation: {'Passed' if query_result['validation']['valid'] else 'Failed'}")

        if query_result['validation']['valid']:
            # 2. Execute the generated query manually
            print("\n2. Executing the generated query:")
            execution_result = await sql_agent.execute_query(
                query=query_result['query'],
                limit=10
            )

            if execution_result['success']:
                data = execution_result['data']
                print(f"   📊 Results: {execution_result['row_count']} rows")
                print(f"   📋 Columns: {execution_result['columns']}")

                if isinstance(data, pd.DataFrame) and not data.empty:
                    print("   📄 Sample results:")
                    print("      " + str(data.head(3)).replace('\n', '\n      '))
            else:
                print(f"   ❌ Execution failed: {execution_result['error']}")
        else:
            print(f"   ❌ Query validation failed: {query_result['validation']['error']}")

    except Exception as e:
        print(f"   ❌ Error in manual query example: {e}")


async def advanced_usage_examples(sql_agent: SQLAgent):
    """Demonstrate advanced usage patterns."""

    print("\n" + "="*50)
    print("🚀 ADVANCED USAGE EXAMPLES")
    print("="*50)

    # 1. Conversation history usage
    print("\n1. Using conversation history:")

    session_id = "advanced_session"
    user_id = "analyst_user"

    queries = [
        "What tables do we have that might contain customer information?",
        "Based on the previous answer, show me the structure of the most relevant table",
        "Now show me a few sample records from that table"
    ]

    for i, query in enumerate(queries, 1):
        print(f"\n   Query {i}: {query}")

        try:
            response = await sql_agent.ask(
                prompt=query,
                session_id=session_id,
                user_id=user_id,
                use_conversation_history=True,
                user_context="I'm analyzing customer data patterns and need to understand the data structure."
            )

            print(f"   💭 Response: {str(response.response)[:150]}...")

        except Exception as e:
            print(f"   ❌ Error: {e}")

    # 2. Query with specific context
    print("\n2. Query with specific business context:")

    try:
        business_context = """
        Context: We're preparing a quarterly business report and need to understand:
        - Data quality and completeness
        - Available metrics for analysis
        - Time-based data for trend analysis
        """

        response = await sql_agent.ask(
            prompt="What data do we have that would be useful for quarterly business reporting?",
            user_context="I'm a business analyst preparing quarterly reports for senior management.",
            context=business_context,
            return_results=True
        )

        print(f"   💼 Business Analysis Response:")
        print(f"      {response.response}")

    except Exception as e:
        print(f"   ❌ Error in business context example: {e}")

    # 3. Query validation without execution
    print("\n3. Query validation (dry run):")

    test_queries = [
        "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'auth'",
        "SELECT invalid_column FROM nonexistent_table",  # This should fail validation
    ]

    for query in test_queries:
        try:
            # Use validation from query generation
            result = await sql_agent.generate_query(
                natural_language_query=f"Execute this query: {query}",
                query_type="SELECT"
            )

            validation = result['validation']
            status = "✅ Valid" if validation['valid'] else "❌ Invalid"
            print(f"   {status}: {query[:50]}...")

            if not validation['valid']:
                print(f"      Error: {validation['error']}")

        except Exception as e:
            print(f"   ❌ Validation error: {e}")


async def error_handling_examples(sql_agent: SQLAgent):
    """Demonstrate error handling patterns."""

    print("\n" + "="*50)
    print("🚨 ERROR HANDLING EXAMPLES")
    print("="*50)

    # 1. Invalid SQL query
    print("\n1. Handling invalid SQL:")

    try:
        result = await sql_agent.execute_query(
            "SELECT invalid_syntax FROM WHERE"  # Intentionally broken SQL
        )

        if not result['success']:
            print(f"   ❌ Expected error caught: {result['error']}")
        else:
            print("   ⚠️  Query unexpectedly succeeded")

    except Exception as e:
        print(f"   ❌ Exception during invalid query: {e}")

    # 2. Non-existent table
    print("\n2. Handling non-existent table:")

    try:
        result = await sql_agent.execute_query(
            'SELECT * FROM definitely_does_not_exist_table LIMIT 1'
        )

        if not result['success']:
            print(f"   ❌ Expected error for missing table: {result['error']}")
        else:
            print("   ⚠️  Query unexpectedly succeeded")

    except Exception as e:
        print(f"   ❌ Exception during missing table query: {e}")

    # 3. Ambiguous natural language query
    print("\n3. Handling ambiguous natural language:")

    try:
        response = await sql_agent.ask(
            prompt="Show me stuff",  # Very vague request
            return_results=False  # Don't execute, just explain
        )

        print(f"   💭 Agent response to vague query: {response.response}")

    except Exception as e:
        print(f"   ❌ Error handling vague query: {e}")

    # 4. Connection testing
    print("\n4. Connection health check:")

    try:
        # Test with a simple query
        result = await sql_agent.execute_query("SELECT 1 as health_check")

        if result['success']:
            print("   ✅ Database connection is healthy")
        else:
            print(f"   ❌ Database connection issue: {result['error']}")

    except Exception as e:
        print(f"   ❌ Connection test failed: {e}")


def setup_logging():
    """Setup logging for better debugging."""
    import logging

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # Reduce sqlalchemy logging noise
    logging.getLogger('sqlalchemy.engine').setLevel(logging.WARNING)


if __name__ == "__main__":
    """
    Usage Instructions:

    1. Set environment variables:
       export PG_HOST=localhost
       export PG_PORT=5432
       export PG_DATABASE=navigator
       export PG_USER=postgres
       export PG_PASSWORD=your_password

    2. Or modify the pg_credentials dictionary directly

    3. Ensure you have the required dependencies:
       - asyncpg (for PostgreSQL async support)
       - sqlalchemy[asyncio]
       - pandas

    4. Run the example:
       python sqlagent_example.py
    """

    print("🎯 AI-Parrot SQLAgent PostgreSQL Example")
    print("=" * 50)

    # Setup logging for debugging
    setup_logging()

    # Run the main example
    asyncio.run(main())
