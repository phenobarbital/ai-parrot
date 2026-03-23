from typing import Optional, List, Dict, Any
from .abstract import AbstractDBAgent
from .tools import DatabaseSchema, TableMetadata


class MockSQLAgent(AbstractDBAgent):
    """Mock implementation for demonstration purposes."""

    async def connect_database(self) -> None:
        """Mock database connection."""
        print("Connected to mock SQL database")
        self.engine = "mock_engine"

    async def extract_schema_metadata(self) -> DatabaseSchema:
        """Mock schema extraction."""
        # Create mock schema
        mock_tables = [
            TableMetadata(
                name="customers",
                schema="public",
                columns=[
                    {"name": "id", "type": "INTEGER", "nullable": False},
                    {"name": "name", "type": "VARCHAR(100)", "nullable": False},
                    {"name": "email", "type": "VARCHAR(255)", "nullable": True},
                    {"name": "region", "type": "VARCHAR(50)", "nullable": True},
                ],
                primary_keys=["id"],
                foreign_keys=[],
                indexes=[],
                description="Customer information table"
            ),
            TableMetadata(
                name="orders",
                schema="public",
                columns=[
                    {"name": "id", "type": "INTEGER", "nullable": False},
                    {"name": "customer_id", "type": "INTEGER", "nullable": False},
                    {"name": "order_date", "type": "DATE", "nullable": False},
                    {"name": "total_amount", "type": "DECIMAL(10,2)", "nullable": False},
                ],
                primary_keys=["id"],
                foreign_keys=[
                    {
                        "column": "customer_id",
                        "referenced_table": "customers",
                        "referenced_column": "id"
                    }
                ],
                indexes=[],
                description="Customer orders table"
            )
        ]

        return DatabaseSchema(
            database_name="sales_db",
            database_type="postgresql",
            tables=mock_tables,
            views=[],
            functions=[],
            procedures=[],
            metadata={
                "version": "14.5",
                "charset": "UTF8",
                "collation": "en_US.UTF-8",
                "total_tables": len(mock_tables),
                "total_views": 0,
                "schema_analyzed_at": "2024-01-15T10:30:00Z",
                "connection_info": {
                    "host": "localhost",
                    "port": 5432,
                    "database": "sales_db"
                },
                "performance_stats": {
                    "avg_query_time": "15ms",
                    "total_connections": 45,
                    "cache_hit_ratio": 0.95
                }
            }
        )

    async def generate_query(self, natural_language_query: str, target_tables: Optional[List[str]] = None, query_type: str = "SELECT") -> Dict[str, Any]:
        """Mock query generation."""
        return {
            "query": f"SELECT * FROM mock_table WHERE condition = '{natural_language_query}'",
            "explanation": f"Generated mock query for: {natural_language_query}",
            "tables_used": target_tables or ["mock_table"]
        }

    async def execute_query(self, query: str) -> Dict[str, Any]:
        """Mock query execution."""
        return {
            "rows": [{"id": 1, "name": "Mock Result", "value": 42}],
            "row_count": 1,
            "execution_time": 0.001,
            "query": query
        }
