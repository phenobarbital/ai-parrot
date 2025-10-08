import asyncio
import pandas as pd
from parrot.tools.databasequery import DatabaseQueryTool

async def example_usage():
    # Create tool instance
    db_tool = DatabaseQueryTool()

    # Execute a query and get DataFrame
    result_df = await db_tool.execute(
        database_driver="pg",
        query="SELECT * FROM auth.users WHERE is_active = true LIMIT 1000",
        output_format="pandas",
        max_rows=1000
    )
    if isinstance(result_df, pd.DataFrame):
        print(f"Retrieved {len(result_df)} rows and {len(result_df.columns)} columns.")

    # Execute a query and get JSON
    result_json = await db_tool.execute(
        database_driver="pg",
        query="SELECT count(*) as total_users FROM auth.users",
        output_format="json"
    )
    print(f"Total active users: {result_json.result}")

    # Test connection
    connection_test = db_tool.test_connection("pg")
    print(connection_test)

    # Save result to file
    if isinstance(result_df, pd.DataFrame):
        file_info = db_tool.save_query_result(result_df, "users_export", "csv")
        print(
            f"Saved to: {file_info['file_url']}"
        )


if __name__ == "__main__":
    # This code demonstrates how to use the DatabaseQueryTool to execute queries
    asyncio.run(example_usage())
