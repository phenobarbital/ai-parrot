"""
Example usage of BigQueryAgent for Google BigQuery.

This script demonstrates how to:
1. Initialize a BigQueryAgent with credentials
2. Extract schema metadata from datasets and tables  
3. Generate SQL queries from natural language
4. Execute queries against BigQuery
"""

import asyncio
from parrot.bots.db import BigQueryAgent


async def main():
    """Main example function."""
    
    # Example 1: Initialize with explicit credentials
    print("=" * 60)
    print("Example 1: Initialize BigQueryAgent with credentials")
    print("=" * 60)
    
    agent = BigQueryAgent(
        name="MyBigQueryAgent",
        project_id="your-gcp-project-id",
        credentials_file="/path/to/service-account-key.json",
        dataset="your_dataset"
    )
    
    print(f"Agent created: {agent.name}")
    print(f"Project: {agent.project_id}")
    
    # Example 2: Initialize with default credentials from config
    print("\n" + "=" * 60)
    print("Example 2: Initialize with default credentials")
    print("=" * 60)
    
    # This will use credentials from environment variables:
    # GOOGLE_APPLICATION_CREDENTIALS, GOOGLE_CLOUD_PROJECT
    agent_with_defaults = BigQueryAgent(
        name="BigQueryAgentWithDefaults"
    )
    
    print(f"Agent created with defaults: {agent_with_defaults.name}")
    
    # Example 3: Connect and extract schema
    print("\n" + "=" * 60)
    print("Example 3: Extract schema metadata")
    print("=" * 60)
    
    try:
        # Connect to BigQuery
        await agent.connect_database()
        print("✓ Connected to BigQuery")
        
        # Extract schema metadata
        schema = await agent.extract_schema_metadata()
        print(f"✓ Extracted schema for {len(schema.tables)} tables")
        
        # Display table information
        for table in schema.tables[:3]:  # Show first 3
            print(f"\nTable: {table.schema}.{table.name}")
            print(f"  Columns: {[col['name'] for col in table.columns[:5]]}")
            print(f"  Description: {table.description[:60]}...")
            
    except Exception as e:
        print(f"✗ Error during schema extraction: {e}")
    
    # Example 4: Generate query from natural language
    print("\n" + "=" * 60)
    print("Example 4: Generate SQL query from natural language")
    print("=" * 60)
    
    try:
        query_result = await agent.generate_query(
            natural_language_query="Show total sales by product category for the last quarter",
            target_tables=["sales"]
        )
        
        print(f"Generated query:")
        print(f"  Type: {query_result['query_type']}")
        print(f"  Query:\n{query_result['query']}")
        
    except Exception as e:
        print(f"✗ Error generating query: {e}")
    
    # Example 5: Execute query
    print("\n" + "=" * 60)
    print("Example 5: Execute BigQuery query")
    print("=" * 60)
    
    try:
        # Execute a simple query
        query = f"""
            SELECT 
                column1, 
                column2, 
                COUNT(*) as count
            FROM `{agent.project_id}.your_dataset.your_table`
            WHERE date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
            GROUP BY column1, column2
            ORDER BY count DESC
        """
        
        result = await agent.execute_query(query, limit=10)
        
        if result["success"]:
            print(f"✓ Query executed successfully")
            print(f"  Rows returned: {result['record_count']}")
            print(f"  Bytes processed: {result.get('total_bytes_processed', 0):,}")
            print(f"  Bytes billed: {result.get('total_bytes_billed', 0):,}")
            
            # Display first few rows
            if result["data"]:
                print(f"\n  First row:")
                for key, value in list(result["data"][0].items())[:5]:
                    print(f"    {key}: {value}")
        else:
            print(f"✗ Query failed: {result.get('error')}")
            
    except Exception as e:
        print(f"✗ Error executing query: {e}")
    
    # Example 6: Use agent in agentic mode
    print("\n" + "=" * 60)
    print("Example 6: Natural language query with agentic mode")
    print("=" * 60)
    
    try:
        response = await agent.ask(
            prompt="What are the top 10 products by revenue in the sales table?",
            user_id="example_user",
            session_id="example_session"
        )
        
        print(f"✓ Agent response:")
        print(f"  {response.output or response.response}")
        
    except Exception as e:
        print(f"✗ Error in agentic query: {e}")
    
    # Example 7: Explore datasets
    print("\n" + "=" * 60)
    print("Example 7: Using exploration tools")
    print("=" * 60)
    
    try:
        # Get exploration tool
        exploration_tool = agent.tool_manager.get_tool("explore_bigquery_datasets")
        
        if exploration_tool:
            # Explore a specific dataset
            result = await exploration_tool._execute(
                dataset="your_dataset",
                show_sample_data=False
            )
            
            if result.status == "success":
                print(f"✓ Exploration successful")
                print(f"  Datasets: {result.result['datasets']}")
                print(f"  Total tables: {result.result['total_tables']}")
        
    except Exception as e:
        print(f"✗ Error in exploration: {e}")
    
    # Cleanup
    await agent.close()
    print("\n" + "=" * 60)
    print("✓ Connection closed")
    print("=" * 60)


if __name__ == "__main__":
    print("\nBigQuery Agent Example")
    print("=" * 60)
    print("Configure credentials via environment variables or config")
    print("=" * 60)
    
    # Uncomment to run:
    # asyncio.run(main())
    
    print("\n✓ Example script loaded")
