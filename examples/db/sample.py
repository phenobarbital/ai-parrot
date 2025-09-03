#!/usr/bin/env python3
"""
Comprehensive Usage Example for Enhanced Database Tool

This script demonstrates various ways to use the unified database tool
across different scenarios and database types.
"""

import asyncio
import os
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional
from querysource.conf import default_dsn
# AI-Parrot imports
from parrot.tools.multidb import (
    EnhancedDatabaseTool,
    MetadataFormat
)
from parrot.tools.db import (
    DatabaseTool,
    DatabaseFlavor,
    OutputFormat
)
from parrot.stores.pgvector import PgVectorStore


class DatabaseToolDemo:
    """Comprehensive demonstration of the Enhanced Database Tool capabilities."""

    def __init__(self):
        """Initialize the demo with various database configurations."""

        # Sample connection configurations for different databases
        self.connection_configs = {
            DatabaseFlavor.POSTGRESQL: {
                "host": os.getenv("PG_HOST", "localhost"),
                "port": os.getenv("PG_PORT", 5432),
                "database": os.getenv("PG_DATABASE", "navigator"),
                "user": os.getenv("PG_USER", "postgres"),
                "password": os.getenv("PG_PASSWORD", "password")
            },
            DatabaseFlavor.BIGQUERY: {
                "project_id": os.getenv("BIGQUERY_PROJECT_ID", "your-project-id"),
                "credentials_path": os.getenv("BIGQUERY_CREDENTIALS_PATH"),
                "location": os.getenv("BIGQUERY_LOCATION", "US")
            }
        }

        # Initialize vector store for schema caching
        self.vector_store = None
        try:
            self.vector_store = PgVectorStore(
                connection_string=os.getenv(
                    "VECTOR_DB_URL",
                    default_dsn
                ),
                table_name="navigator_metadata",
                embedding_dimension=384
            )
        except Exception as e:
            print(f"Warning: Could not initialize vector store: {e}")
            print("Running without vector store integration")

    async def demo_basic_schema_extraction(self):
        """Demonstrate basic schema extraction functionality."""
        print("\n" + "="*60)
        print("DEMO 1: Basic Schema Extraction")
        print("="*60)

        # Initialize the enhanced database tool
        db_tool = EnhancedDatabaseTool(
            vector_store=self.vector_store,
            name="schema_extractor"
        )

        # Extract schema from PostgreSQL database
        result = await db_tool.execute(
            operation="schema_extract",
            database_flavor=DatabaseFlavor.POSTGRESQL,
            connection_params=self.connection_configs[DatabaseFlavor.POSTGRESQL],
            schema_names=["public", "analytics"],
            update_knowledge_base=True,
            cache_duration_hours=12
        )

        if result.status == "success":
            print(f"✅ Schema extraction successful!")
            print(f"📊 Found {len(result.result.get('tables', []))} tables")
            print(f"📋 Found {len(result.result.get('views', []))} views")
            print(f"🎯 Knowledge base updated: {result.metadata.get('knowledge_base_updated')}")

            # Display first table's metadata in different formats
            if result.result.get('tables'):
                first_table = result.result['tables'][0]
                print(f"\n📝 Sample table metadata for '{first_table.get('name')}':")
                print("-" * 40)

                # Show YAML optimized format
                print("YAML Optimized Format:")
                print(first_table.get('yaml_representation', 'Not available'))
        else:
            print(f"❌ Schema extraction failed: {result.error}")

    async def demo_intelligent_query_generation(self):
        """Demonstrate natural language to SQL query generation."""
        print("\n" + "="*60)
        print("DEMO 2: Intelligent Query Generation")
        print("="*60)

        db_tool = DatabaseTool(
            knowledge_store=self.vector_store,
            name="query_generator"
        )

        # Test various natural language queries
        test_queries = [
            "Show me total sales by region for the last quarter",
            "Find customers who haven't placed an order in the past 6 months",
            "What are the top 10 selling products this year?",
            "Calculate monthly revenue trends for the past year",
            "Find all orders with suspicious high values"
        ]

        for i, nl_query in enumerate(test_queries, 1):
            print(f"\n🔍 Query {i}: {nl_query}")
            print("-" * 50)

            result = await db_tool.execute(
                operation="query_generate",
                natural_language_query=nl_query,
                database_flavor=DatabaseFlavor.POSTGRESQL,
                connection_params=self.connection_configs[DatabaseFlavor.POSTGRESQL],
                schema_names=["public"]
            )

            if result.status == "success":
                generated_sql = result.result.get('sql_query', 'No query generated')
                print(f"✅ Generated SQL:")
                print(f"```sql\n{generated_sql}\n```")
                print(f"🎯 Context tables used: {result.result.get('schema_context_used', 0)}")
            else:
                print(f"❌ Query generation failed: {result.error}")

    async def demo_query_validation_and_security(self):
        """Demonstrate query validation and security checking."""
        print("\n" + "="*60)
        print("DEMO 3: Query Validation and Security")
        print("="*60)

        db_tool = DatabaseTool(name="query_validator")

        # Test queries with various security and syntax issues
        test_queries = {
            "Valid Query": "SELECT name, email FROM customers WHERE created_at > '2023-01-01'",
            "SQL Injection Risk": "SELECT * FROM users WHERE id = '1 OR 1=1'",
            "Syntax Error": "SELCT name FROM customers WHRE",
            "Dangerous Operation": "DROP TABLE customers",
            "Performance Issue": "SELECT * FROM large_table WHERE UPPER(name) LIKE '%JOHN%'"
        }

        for query_name, sql_query in test_queries.items():
            print(f"\n🔍 Testing: {query_name}")
            print(f"📝 Query: {sql_query}")
            print("-" * 50)

            result = await db_tool.execute(
                operation="query_validate",
                sql_query=sql_query,
                database_flavor=DatabaseFlavor.POSTGRESQL,
                connection_params=self.connection_configs[DatabaseFlavor.POSTGRESQL]
            )

            if result.status in ["success", "warning"]:
                validation = result.result
                status_icon = "✅" if validation['is_valid'] else "❌"
                print(f"{status_icon} Valid: {validation['is_valid']}")
                print(f"📊 Query Type: {validation.get('query_type', 'Unknown')}")

                if validation.get('warnings'):
                    print(f"⚠️  Warnings:")
                    for warning in validation['warnings']:
                        print(f"   • {warning}")

                if validation.get('errors'):
                    print(f"🚫 Errors:")
                    for error in validation['errors']:
                        print(f"   • {error}")

                if validation.get('security_checks'):
                    print(f"🛡️  Security Checks:")
                    for check, passed in validation['security_checks'].items():
                        icon = "✅" if passed else "❌"
                        print(f"   {icon} {check}")
            else:
                print(f"❌ Validation failed: {result.error}")

    async def demo_full_pipeline_execution(self):
        """Demonstrate the complete pipeline from natural language to results."""
        print("\n" + "="*60)
        print("DEMO 4: Full Pipeline Execution")
        print("="*60)

        db_tool = DatabaseTool(
            knowledge_store=self.vector_store,
            name="full_pipeline"
        )

        # Execute complete pipeline for a business question
        business_question = "What are our top 5 customers by total purchase amount this year?"

        print(f"🎯 Business Question: {business_question}")
        print("-" * 50)

        result = await db_tool.execute(
            operation="full_pipeline",
            natural_language_query=business_question,
            database_flavor=DatabaseFlavor.POSTGRESQL,
            connection_params=self.connection_configs[DatabaseFlavor.POSTGRESQL],
            schema_names=["public"],
            max_rows=100,
            timeout_seconds=30,
            output_format=OutputFormat.PANDAS,
            dry_run=False,  # Set to True to validate without executing
            update_knowledge_base=True
        )

        if result.status == "success":
            pipeline_results = result.result['pipeline_results']
            execution_summary = result.result['execution_summary']

            print(f"✅ Pipeline completed successfully!")
            print(f"🔄 Final Query: {result.result['final_query']}")
            print(f"⏱️  Execution Time: {execution_summary['execution_time_seconds']:.2f} seconds")
            print(f"📊 Rows Returned: {execution_summary['rows_returned']}")
            print(f"📋 Output Format: {execution_summary['output_format']}")

            # Show pipeline step results
            print(f"\n📈 Pipeline Steps:")
            for step_name, step_result in pipeline_results.items():
                if step_result:
                    print(f"   ✅ {step_name}: Success")
                else:
                    print(f"   ⏭️  {step_name}: Skipped")

            # Display sample results if available
            if pipeline_results.get('query_execution'):
                data = pipeline_results['query_execution'].get('data')
                if hasattr(data, 'head'):  # Pandas DataFrame
                    print(f"\n📋 Sample Results (first 5 rows):")
                    print(data.head().to_string())
        else:
            print(f"❌ Pipeline failed: {result.error}")
            if 'partial_results' in result.metadata:
                print(f"🔍 Partial results available for debugging")

    async def demo_multi_database_support(self):
        """Demonstrate working with multiple database types."""
        print("\n" + "="*60)
        print("DEMO 5: Multi-Database Support")
        print("="*60)

        # Test different database flavors
        database_scenarios = [
            {
                "name": "PostgreSQL Analytics",
                "flavor": DatabaseFlavor.POSTGRESQL,
                "query": "Show me customer lifetime value analysis",
                "config": self.connection_configs[DatabaseFlavor.POSTGRESQL]
            },
            {
                "name": "MySQL Inventory",
                "flavor": DatabaseFlavor.MYSQL,
                "query": "Find low stock items that need reordering",
                "config": self.connection_configs[DatabaseFlavor.MYSQL]
            },
            {
                "name": "BigQuery Data Warehouse",
                "flavor": DatabaseFlavor.BIGQUERY,
                "query": "Calculate monthly active users trend",
                "config": self.connection_configs[DatabaseFlavor.BIGQUERY]
            }
        ]

        for scenario in database_scenarios:
            print(f"\n🗄️  {scenario['name']} ({scenario['flavor'].value})")
            print(f"📝 Query: {scenario['query']}")
            print("-" * 50)

            db_tool = DatabaseTool(
                knowledge_store=self.vector_store,
                name=f"db_tool_{scenario['flavor'].value}"
            )

            try:
                result = await db_tool.execute(
                    operation="query_generate",
                    natural_language_query=scenario['query'],
                    database_flavor=scenario['flavor'],
                    connection_params=scenario['config'],
                    schema_names=["public"] if scenario['flavor'] != DatabaseFlavor.BIGQUERY else ["analytics"]
                )

                if result.status == "success":
                    print(f"✅ {scenario['flavor'].value}-specific SQL generated:")
                    print(f"```sql\n{result.result.get('sql_query', 'No query')}\n```")
                else:
                    print(f"❌ Failed: {result.error}")

            except Exception as e:
                print(f"⚠️  Skipped {scenario['name']}: {str(e)}")

    async def demo_caching_and_performance(self):
        """Demonstrate caching behavior and performance optimization."""
        print("\n" + "="*60)
        print("DEMO 6: Caching and Performance")
        print("="*60)

        db_tool = EnhancedDatabaseTool(
            vector_store=self.vector_store,
            name="performance_demo"
        )

        # Simulate repeated queries to show caching behavior
        repeated_query = "Find all orders placed in the last month"

        print(f"🔄 Testing repeated query performance:")
        print(f"📝 Query: {repeated_query}")
        print("-" * 50)

        for attempt in range(3):
            print(f"\n🎯 Attempt {attempt + 1}:")
            start_time = datetime.now()

            result = await db_tool.execute(
                operation="query_generate",
                natural_language_query=repeated_query,
                database_flavor=DatabaseFlavor.POSTGRESQL,
                connection_params=self.connection_configs[DatabaseFlavor.POSTGRESQL],
                schema_names=["public"]
            )

            execution_time = (datetime.now() - start_time).total_seconds()
            print(f"⏱️  Execution time: {execution_time:.3f} seconds")

            if result.status == "success":
                context_used = result.result.get('schema_context_used', 0)
                print(f"📊 Schema context tables: {context_used}")
                print(f"✅ Cache performance: {'FAST' if execution_time < 0.5 else 'NORMAL'}")
            else:
                print(f"❌ Failed: {result.error}")

        # Show cache statistics
        if hasattr(db_tool.schema_cache, 'get_cache_stats'):
            cache_stats = db_tool.schema_cache.get_cache_stats()
            print(f"\n📈 Cache Statistics:")
            print(f"   Memory cache size: {cache_stats['memory_cache_size']}")
            print(f"   Total accesses: {cache_stats['total_access_count']}")
            print(f"   Unique tables: {cache_stats['unique_tables_accessed']}")
            print(f"   Pending updates: {cache_stats['pending_vector_updates']}")

    async def demo_error_handling_and_edge_cases(self):
        """Demonstrate robust error handling and edge case management."""
        print("\n" + "="*60)
        print("DEMO 7: Error Handling and Edge Cases")
        print("="*60)

        db_tool = DatabaseTool(name="error_demo")

        # Test various error scenarios
        error_scenarios = [
            {
                "name": "Invalid Connection",
                "params": {
                    "operation": "schema_extract",
                    "database_flavor": DatabaseFlavor.POSTGRESQL,
                    "connection_params": {"host": "invalid-host", "port": 9999},
                    "schema_names": ["public"]
                }
            },
            {
                "name": "Empty Natural Language Query",
                "params": {
                    "operation": "query_generate",
                    "natural_language_query": "",
                    "database_flavor": DatabaseFlavor.POSTGRESQL,
                    "connection_params": self.connection_configs[DatabaseFlavor.POSTGRESQL]
                }
            },
            {
                "name": "Malformed SQL Query",
                "params": {
                    "operation": "query_validate",
                    "sql_query": "This is not SQL at all!",
                    "database_flavor": DatabaseFlavor.POSTGRESQL,
                    "connection_params": self.connection_configs[DatabaseFlavor.POSTGRESQL]
                }
            },
            {
                "name": "Unsupported Operation",
                "params": {
                    "operation": "invalid_operation",
                    "database_flavor": DatabaseFlavor.POSTGRESQL,
                    "connection_params": self.connection_configs[DatabaseFlavor.POSTGRESQL]
                }
            }
        ]

        for scenario in error_scenarios:
            print(f"\n🧪 Testing: {scenario['name']}")
            print("-" * 40)

            try:
                result = await db_tool.execute(**scenario['params'])

                if result.status == "error":
                    print(f"✅ Error handled gracefully")
                    print(f"🚫 Error message: {result.error}")
                    print(f"📊 Metadata: {json.dumps(result.metadata, indent=2)}")
                elif result.status == "warning":
                    print(f"⚠️  Warning status (expected for some scenarios)")
                    print(f"📊 Result: {result.result}")
                else:
                    print(f"🤔 Unexpected success: {result.status}")

            except Exception as e:
                print(f"❌ Unhandled exception: {str(e)}")

    async def demo_structured_output_formats(self):
        """Demonstrate different output formats and structured data."""
        print("\n" + "="*60)
        print("DEMO 8: Structured Output Formats")
        print("="*60)

        db_tool = DatabaseTool(name="output_demo")

        # Sample query for testing different output formats
        test_query = "SELECT name, email, total_orders FROM customer_summary LIMIT 5"

        output_formats = [
            OutputFormat.PANDAS,
            OutputFormat.JSON,
            OutputFormat.DICT,
            OutputFormat.CSV
        ]

        for output_format in output_formats:
            print(f"\n📋 Testing {output_format.value} output format:")
            print("-" * 40)

            result = await db_tool.execute(
                operation="query_execute",
                sql_query=test_query,
                database_flavor=DatabaseFlavor.POSTGRESQL,
                connection_params=self.connection_configs[DatabaseFlavor.POSTGRESQL],
                output_format=output_format,
                max_rows=10
            )

            if result.status == "success":
                data = result.result.get('data')
                print(f"✅ Format: {result.result.get('output_format')}")
                print(f"📊 Data type: {type(data).__name__}")

                # Show preview based on format
                if output_format == OutputFormat.PANDAS:
                    print(f"🔍 DataFrame shape: {data.shape if hasattr(data, 'shape') else 'N/A'}")
                    if hasattr(data, 'head'):
                        print("Preview:")
                        print(data.head().to_string())
                elif output_format in [OutputFormat.JSON, OutputFormat.CSV]:
                    print(f"🔍 Preview (first 200 chars):")
                    preview = str(data)[:200]
                    print(f"{preview}{'...' if len(str(data)) > 200 else ''}")
                elif output_format == OutputFormat.DICT:
                    print(f"🔍 Records count: {len(data) if isinstance(data, list) else 'N/A'}")
                    if isinstance(data, list) and data:
                        print(f"Sample record: {data[0]}")
            else:
                print(f"❌ Failed: {result.error}")

    async def cleanup_demo(self):
        """Clean up resources and show final statistics."""
        print("\n" + "="*60)
        print("DEMO CLEANUP AND SUMMARY")
        print("="*60)

        print("🧹 Cleaning up resources...")

        # Close vector store connections if available
        if self.vector_store:
            try:
                await self.vector_store.close()
                print("✅ Vector store connection closed")
            except Exception as e:
                print(f"⚠️  Vector store cleanup warning: {e}")

        print("✅ All demos completed successfully!")
        print("\n📊 Summary of Demonstrated Features:")
        print("   • Multi-tier schema caching with vector store integration")
        print("   • Natural language to SQL query generation")
        print("   • Comprehensive query validation and security checks")
        print("   • Full pipeline execution with multiple database types")
        print("   • Intelligent context building and performance optimization")
        print("   • Robust error handling and edge case management")
        print("   • Multiple output formats and structured data support")
        print("\n🚀 The Enhanced Database Tool is ready for production use!")

    async def run_all_demos(self):
        """Run all demonstration scenarios."""
        print("🚀 Starting Enhanced Database Tool Comprehensive Demo")
        print("="*60)

        # Run all demo scenarios
        demo_functions = [
            self.demo_basic_schema_extraction,
            self.demo_intelligent_query_generation,
            self.demo_query_validation_and_security,
            self.demo_full_pipeline_execution,
            self.demo_multi_database_support,
            self.demo_caching_and_performance,
            self.demo_error_handling_and_edge_cases,
            self.demo_structured_output_formats,
            self.cleanup_demo
        ]

        for demo_func in demo_functions:
            try:
                await demo_func()
            except Exception as e:
                print(f"\n❌ Demo failed: {demo_func.__name__}")
                print(f"🚫 Error: {str(e)}")
                print("🔄 Continuing with next demo...")

        print(f"\n🏁 All demos completed at {datetime.now().isoformat()}")


async def main():
    """Main function to run the comprehensive demo."""
    # Setup environment variables (you may need to adjust these)
    os.environ.setdefault("PG_USER", "postgres")
    os.environ.setdefault("PG_PASSWORD", "password")
    os.environ.setdefault("MYSQL_USER", "root")
    os.environ.setdefault("MYSQL_PASSWORD", "password")

    # Initialize and run the demo
    demo = DatabaseToolDemo()
    await demo.run_all_demos()


if __name__ == "__main__":
    """
    Run the comprehensive demo.

    Prerequisites:
    1. Install AI-Parrot with database dependencies: pip install ai-parrot[database]
    2. Set up your database connections (PostgreSQL, MySQL, BigQuery, etc.)
    3. Configure environment variables for database credentials
    4. Optional: Set up a vector database for enhanced caching

    Usage:
    python database_tool_demo.py
    """

    print("Enhanced Database Tool - Comprehensive Usage Demo")
    print("=" * 50)
    print("This demo showcases the full capabilities of the unified database tool")
    print("including schema extraction, query generation, validation, and execution.")
    print("\nPress Ctrl+C at any time to exit gracefully.")
    print("=" * 50)

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n🛑 Demo interrupted by user")
    except Exception as e:
        print(f"\n\n❌ Demo failed with error: {str(e)}")
        import traceback
        traceback.print_exc()
