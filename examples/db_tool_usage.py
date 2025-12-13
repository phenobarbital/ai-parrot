
import asyncio
import os
import logging
from parrot.tools.db import DatabaseTool, DatabaseFlavor
from parrot.bots.agent import BasicAgent
from navconfig import config

# Configure logging
logging.basicConfig(level=logging.INFO)

# Dummy connection params for example
CONNECTION_PARAMS = {
    "host": "localhost",
    "port": 5432,
    "username": "postgres",
    "password": "12345678",
    "database": "test"
}

async def manual_usage():
    print("\n" + "="*50)
    print("MANUAL USAGE OF DATABASE TOOL")
    print("="*50)
    
    # Initialize tool with LLM (using string for Factory)
    # Using 'groq:llama-3.3-70b-versatile' as a powerful default for SQL generation
    db_tool = DatabaseTool(
        default_connection_params={DatabaseFlavor.POSTGRESQL: CONNECTION_PARAMS},
        llm="google:gemini-2.5-flash" 
    )

    # 1. Schema Extract
    print("\n---> [Manual] Step 1: Extracting Schema for employees...")
    # Note: In a real scenario, this would connect to the DB. 
    # If the DB doesn't exist, it might fail or return mock/empty data depending on AsyncDB impl.
    try:
        schema_res = await db_tool.execute(
            operation="schema_extract",
            database_flavor=DatabaseFlavor.POSTGRESQL,
            connection_params=CONNECTION_PARAMS,
            schema_names=["public"]
        )
        print(f"Schema Extract Result: {schema_res.status}")
    except Exception as e:
        print(
            f"Schema Extract Skipped/Failed (expected if DB not reachable): {e}"
        )

    # 2. Query Generation
    nl_query = "Extract status=Active employees from department_code 001400 and 001450"
    print(
        f"\n---> [Manual] Step 2: Generating Query for: '{nl_query}'"
    )
    
    gen_res = await db_tool.execute(
        operation="query_generate",
        natural_language_query=nl_query,
        database_flavor=DatabaseFlavor.POSTGRESQL,
        connection_params=CONNECTION_PARAMS
    )
    
    if gen_res.status == "success":
        sql_query = gen_res.result["sql_query"]
        print(f"Generated SQL: {sql_query}")
        
        # 3. Explain Query
        print(f"\n---> [Manual] Step 3: Explaining Query...")
        explain_res = await db_tool.execute(
            operation="explain_query",
            sql_query=sql_query,
            database_flavor=DatabaseFlavor.POSTGRESQL,
            connection_params=CONNECTION_PARAMS
        )
        
        if explain_res.status == "success":
             print("\nPlan Analysis from LLM:")
             print("-" * 20)
             print(explain_res.result["analysis"])
             print("-" * 20)
        else:
             print(
                f"Explain failed: {explain_res.error}"
            )
    else:
        print(
            f"Generation failed: {gen_res.error}"
        )


async def agent_usage():
    print("\n" + "="*50)
    print("AGENT USAGE WITH DATABASE TOOL")
    print("="*50)
    
    # Initialize Tool
    db_tool = DatabaseTool(
        default_connection_params={DatabaseFlavor.POSTGRESQL: CONNECTION_PARAMS},
        llm="google:gemini-2.5-flash"
    )
    
    # Initialize Agent
    agent = BasicAgent(
        llm="google:gemini-2.5-flash",
        tools=[db_tool]
    )

    await agent.configure()
    
    async with agent:
        # Prompt the agent to do the tasks
        instruction = (
            "1. Extract schema for table employees on postgresql.\n"
            "2. Create a query for extracting status=Active employees from department_code 001400 and 001450.\n"
            "3. Explain the query you just created."
        )
        print(f"\n---> [Agent] Asking Agent to:\n{instruction}")
        
        response = await agent.ask(instruction)
        
        print("\n---> [Agent] Final Response:")
        print(response.output)

if __name__ == "__main__":
    async def main():
        try:
            await manual_usage()
            await agent_usage()
        except Exception as e:
            print(f"An error occurred: {e}")

    asyncio.run(main())
