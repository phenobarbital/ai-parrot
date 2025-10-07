"""
SQLAgent Quick Start Example - Minimal PostgreSQL Setup
======================================================

A minimal example to get started with SQLAgent and PostgreSQL quickly.
"""

import os
import asyncio
from querysource.conf import async_database_url
from parrot.bots.db.sql import SQLAgent


async def quick_start():
    """Quick start example with minimal configuration."""
    # Create agent (no vector store by default)
    agent = SQLAgent(
        name="QuickAgent",
        credentials=async_database_url,
        database_flavor="postgresql",
        schema_name="auth",
        max_tokens=8192,
        temperature=0
    )

    try:
        # Initialize
        print("Connecting to database...")
        await agent.configure()
        print(f"Connected! Found {len(agent.schema_metadata.tables)} tables")

        # Basic natural language query
        response = await agent.ask(
            "What tables do we have in this database?",
            return_results=True
        )

        print(f"Response: {response.response}")

        # If there's data, show it
        if response.output is not None:
            print(f"Data: {response.output}")

        # Manual query execution
        result = await agent.execute_query(
            "SELECT schemaname, tablename FROM pg_tables WHERE schemaname = 'auth' LIMIT 5"
        )

        if result['success']:
            print(f"Manual query returned {result['row_count']} rows")
            print(result['data'])

        await natural_language_examples(agent)

    finally:
        await agent.cleanup()


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


if __name__ == "__main__":
    asyncio.run(quick_start())
