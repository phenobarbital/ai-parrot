"""
SQL Database Agent Implementation for AI-Parrot.

Concrete implementation of AbstractDbAgent for SQL databases
with support for PostgreSQL, MySQL, and SQL Server.
"""

from typing import Dict, Any, List, Optional, Union
import re
from urllib.parse import urlparse
from datetime import datetime
from pydantic import Field
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text, MetaData, inspect, Table, Column
from sqlalchemy.engine.reflection import Inspector
from sqlalchemy.dialects import postgresql, mysql, mssql
from sqlalchemy.exc import SQLAlchemyError

from .dbagent import (
    AbstractDBAgent,
    DatabaseSchema,
    TableMetadata,
    QueryGenerationArgs
)
from ...tools.abstract import AbstractTool, ToolResult, AbstractToolArgsSchema
from ...models import AIMessage


class SQLQueryExecutionArgs(AbstractToolArgsSchema):
    """Arguments for SQL query execution."""
    query: str = Field(description="SQL query to execute")
    limit: int = Field(default=100, description="Maximum number of rows to return")
    dry_run: bool = Field(default=False, description="Validate query without executing")


class SQLDbAgent(AbstractDBAgent):
    """
    SQL Database Agent for introspection and query generation.

    Supports PostgreSQL, MySQL, and SQL Server with async operations.
    """

    # Database flavor mappings
    DIALECT_MAPPING = {
        'postgresql': 'postgresql+asyncpg',
        'postgres': 'postgresql+asyncpg',
        'mysql': 'mysql+aiomysql',
        'sqlserver': 'mssql+aioodbc',
        'mssql': 'mssql+aioodbc'
    }

    def __init__(
        self,
        name: str = "SQLDatabaseAgent",
        connection_string: str = None,
        database_flavor: str = "postgresql",
        schema_name: str = "public",
        max_sample_rows: int = 5,
        **kwargs
    ):
        """
        Initialize SQL Database Agent.

        Args:
            name: Agent name
            connection_string: Database connection string
            database_flavor: Database type (postgresql, mysql, sqlserver)
            schema_name: Target schema name
            max_sample_rows: Maximum rows to sample from each table
        """
        self.database_flavor = database_flavor.lower()
        self.max_sample_rows = max_sample_rows
        self.async_session_maker = None

        # Validate database flavor
        if self.database_flavor not in self.DIALECT_MAPPING:
            raise ValueError(f"Unsupported database flavor: {database_flavor}")

        super().__init__(
            name=name,
            connection_string=connection_string,
            schema_name=schema_name,
            **kwargs
        )

        # Add SQL-specific tools
        self._setup_sql_tools()

    def _setup_sql_tools(self):
        """Setup SQL-specific tools."""
        # Add query execution tool
        execution_tool = SQLQueryExecutionTool(agent=self)
        self.tool_manager.register_tool(execution_tool)

    async def connect_database(self) -> None:
        """Connect to the SQL database using SQLAlchemy async engine."""
        if not self.connection_string:
            raise ValueError("Connection string is required")

        try:
            # Parse connection string to determine dialect
            parsed = urlparse(self.connection_string)

            # Adjust connection string for async drivers if needed
            if not any(
                async_driver in self.connection_string for async_driver in
                ['asyncpg', 'aiomysql', 'aioodbc']
            ):
                connection_string = self._adapt_connection_string_for_async(
                    self.connection_string
                )
            else:
                connection_string = self.connection_string

            # Create async engine
            self.engine = create_async_engine(
                connection_string,
                echo=False,  # Set to True for SQL debugging
                pool_pre_ping=True,
                pool_recycle=3600
            )

            # Create session maker
            self.async_session_maker = sessionmaker(
                self.engine,
                class_=AsyncSession,
                expire_on_commit=False
            )

            # Test connection
            async with self.engine.begin() as conn:
                await conn.execute(text("SELECT 1"))

            self.logger.info(f"Successfully connected to {self.database_flavor} database")

        except Exception as e:
            self.logger.error(f"Failed to connect to database: {e}")
            raise

    def _adapt_connection_string_for_async(self, connection_string: str) -> str:
        """Adapt synchronous connection string for async drivers."""
        parsed = urlparse(connection_string)

        if parsed.scheme.startswith('postgresql'):
            return connection_string.replace('postgresql://', 'postgresql+asyncpg://')
        elif parsed.scheme.startswith('mysql'):
            return connection_string.replace('mysql://', 'mysql+aiomysql://')
        elif parsed.scheme.startswith('mssql'):
            return connection_string.replace('mssql://', 'mssql+aioodbc://')

        return connection_string

    async def extract_schema_metadata(self) -> DatabaseSchema:
        """Extract complete schema metadata from SQL database."""
        if not self.engine:
            await self.connect_database()

        try:
            async with self.engine.begin() as conn:
                # Get database name
                db_name_query = await self._get_database_name_query()
                result = await conn.execute(text(db_name_query))
                database_name = result.scalar()

                # Extract tables metadata
                tables = await self._extract_tables_metadata(conn)

                # Extract views metadata
                views = await self._extract_views_metadata(conn)

                # Extract functions and procedures (database-specific)
                functions = await self._extract_functions_metadata(conn)
                procedures = await self._extract_procedures_metadata(conn)

                schema_metadata = DatabaseSchema(
                    database_name=database_name or "unknown",
                    database_type=self.database_flavor,
                    tables=tables,
                    views=views,
                    functions=functions,
                    procedures=procedures,
                    metadata={
                        "schema_name": self.schema_name,
                        "extraction_timestamp": datetime.now().isoformat(),
                        "total_tables": len(tables),
                        "total_views": len(views)
                    }
                )

                self.logger.info(
                    f"Extracted metadata for {len(tables)} tables and {len(views)} views"
                )

                return schema_metadata

        except Exception as e:
            self.logger.error(f"Failed to extract schema metadata: {e}")
            raise

    async def _get_database_name_query(self) -> str:
        """Get database name query based on database flavor."""
        if self.database_flavor == 'postgresql':
            return "SELECT current_database()"
        elif self.database_flavor == 'mysql':
            return "SELECT database()"
        elif self.database_flavor in ['sqlserver', 'mssql']:
            return "SELECT DB_NAME()"
        else:
            return "SELECT 'unknown' as database_name"

    async def _extract_tables_metadata(self, conn) -> List[TableMetadata]:
        """Extract metadata for all tables in the schema."""
        tables = []
        table_query = ""
        # Get table names
        if self.database_flavor == 'postgresql':
            table_query = """
                SELECT table_name, table_type
                FROM information_schema.tables
                WHERE table_schema = :schema_name
                AND table_type = 'BASE TABLE'
                ORDER BY table_name
            """
        elif self.database_flavor == 'mysql':
            table_query = """
                SELECT table_name, table_type
                FROM information_schema.tables
                WHERE table_schema = :schema_name
                AND table_type = 'BASE TABLE'
                ORDER BY table_name
            """
        elif self.database_flavor in ['sqlserver', 'mssql']:
            table_query = """
                SELECT table_name, table_type
                FROM information_schema.tables
                WHERE table_schema = :schema_name
                AND table_type = 'BASE TABLE'
                ORDER BY table_name
            """

        result = await conn.execute(
            text(table_query), {"schema_name": self.schema_name}
        )
        table_rows = result.fetchall()

        for row in table_rows:
            table_name = row[0]

            # Extract detailed table metadata
            table_metadata = await self._extract_single_table_metadata(conn, table_name)
            tables.append(table_metadata)

        return tables

    async def _extract_single_table_metadata(self, conn, table_name: str) -> TableMetadata:
        """Extract detailed metadata for a single table."""
        # Get column information
        columns = await self._get_table_columns(conn, table_name)

        # Get primary keys
        primary_keys = await self._get_primary_keys(conn, table_name)

        # Get foreign keys
        foreign_keys = await self._get_foreign_keys(conn, table_name)

        # Get indexes
        indexes = await self._get_indexes(conn, table_name)

        # Get sample data
        sample_data = await self._get_sample_data(conn, table_name)

        # Get table description/comment
        description = await self._get_table_description(conn, table_name)

        return TableMetadata(
            name=table_name,
            schema=self.schema_name,
            columns=columns,
            primary_keys=primary_keys,
            foreign_keys=foreign_keys,
            indexes=indexes,
            description=description,
            sample_data=sample_data
        )

    async def _get_table_columns(self, conn, table_name: str) -> List[Dict[str, Any]]:
        """Get column information for a table."""
        if self.database_flavor == 'postgresql':
            query = """
                SELECT
                    column_name,
                    data_type,
                    is_nullable,
                    column_default,
                    character_maximum_length,
                    numeric_precision,
                    numeric_scale,
                    col_description(pgc.oid, ordinal_position) as column_comment
                FROM information_schema.columns isc
                LEFT JOIN pg_class pgc ON pgc.relname = isc.table_name
                WHERE table_schema = :schema_name
                AND table_name = :table_name
                ORDER BY ordinal_position
            """
        elif self.database_flavor == 'mysql':
            query = """
                SELECT
                    column_name,
                    data_type,
                    is_nullable,
                    column_default,
                    character_maximum_length,
                    numeric_precision,
                    numeric_scale,
                    column_comment
                FROM information_schema.columns
                WHERE table_schema = :schema_name
                AND table_name = :table_name
                ORDER BY ordinal_position
            """
        else:  # SQL Server
            query = """
                SELECT
                    column_name,
                    data_type,
                    is_nullable,
                    column_default,
                    character_maximum_length,
                    numeric_precision,
                    numeric_scale,
                    NULL as column_comment
                FROM information_schema.columns
                WHERE table_schema = :schema_name
                AND table_name = :table_name
                ORDER BY ordinal_position
            """

        result = await conn.execute(text(query), {
            "schema_name": self.schema_name,
            "table_name": table_name
        })

        columns = []
        for row in result.fetchall():
            columns.append({
                "name": row[0],
                "type": row[1],
                "nullable": row[2] == "YES",
                "default": row[3],
                "max_length": row[4],
                "precision": row[5],
                "scale": row[6],
                "description": row[7] if len(row) > 7 else None
            })

        return columns

    async def _get_primary_keys(self, conn, table_name: str) -> List[str]:
        """Get primary key columns for a table."""
        if self.database_flavor == 'postgresql':
            query = """
                SELECT column_name
                FROM information_schema.key_column_usage
                WHERE table_schema = :schema_name
                AND table_name = :table_name
                AND constraint_name IN (
                    SELECT constraint_name
                    FROM information_schema.table_constraints
                    WHERE table_schema = :schema_name
                    AND table_name = :table_name
                    AND constraint_type = 'PRIMARY KEY'
                )
                ORDER BY ordinal_position
            """
        else:  # MySQL and SQL Server have similar syntax
            query = """
                SELECT column_name
                FROM information_schema.key_column_usage
                WHERE table_schema = :schema_name
                AND table_name = :table_name
                AND constraint_name = 'PRIMARY'
                ORDER BY ordinal_position
            """

        result = await conn.execute(text(query), {
            "schema_name": self.schema_name,
            "table_name": table_name
        })

        return [row[0] for row in result.fetchall()]

    async def _get_foreign_keys(self, conn, table_name: str) -> List[Dict[str, Any]]:
        """Get foreign key information for a table."""
        # Implementation varies by database, simplified version here
        query = """
            SELECT
                kcu.column_name,
                ccu.table_schema AS referenced_table_schema,
                ccu.table_name AS referenced_table_name,
                ccu.column_name AS referenced_column_name
            FROM information_schema.key_column_usage kcu
            JOIN information_schema.constraint_column_usage ccu
                ON kcu.constraint_name = ccu.constraint_name
            WHERE kcu.table_schema = :schema_name
            AND kcu.table_name = :table_name
            AND kcu.constraint_name IN (
                SELECT constraint_name
                FROM information_schema.table_constraints
                WHERE table_schema = :schema_name
                AND table_name = :table_name
                AND constraint_type = 'FOREIGN KEY'
            )
        """

        result = await conn.execute(text(query), {
            "schema_name": self.schema_name,
            "table_name": table_name
        })

        foreign_keys = []
        for row in result.fetchall():
            foreign_keys.append({
                "column": row[0],
                "referenced_table_schema": row[1],
                "referenced_table": row[2],
                "referenced_column": row[3]
            })

        return foreign_keys

    async def _get_indexes(self, conn, table_name: str) -> List[Dict[str, Any]]:
        """Get index information for a table (simplified implementation)."""
        # This is a simplified implementation - full implementation would be database-specific
        return []

    async def _get_sample_data(self, conn, table_name: str) -> List[Dict[str, Any]]:
        """Get sample data from a table."""
        try:
            query = f"""
                SELECT * FROM {self.schema_name}.{table_name}
                LIMIT {self.max_sample_rows}
            """

            result = await conn.execute(text(query))
            rows = result.fetchall()
            columns = result.keys()

            sample_data = []
            for row in rows:
                sample_data.append(dict(zip(columns, row)))

            return sample_data

        except Exception as e:
            self.logger.warning(f"Could not get sample data for {table_name}: {e}")
            return []

    async def _get_table_description(self, conn, table_name: str) -> Optional[str]:
        """Get table description/comment."""
        # Implementation varies by database
        return None

    async def _extract_views_metadata(self, conn) -> List[TableMetadata]:
        """Extract metadata for database views."""
        # Similar to tables but for views - simplified implementation
        return []

    async def _extract_functions_metadata(self, conn) -> List[Dict[str, Any]]:
        """Extract database functions metadata."""
        return []

    async def _extract_procedures_metadata(self, conn) -> List[Dict[str, Any]]:
        """Extract database stored procedures metadata."""
        return []

    async def generate_query(
        self,
        natural_language_query: str,
        target_tables: Optional[List[str]] = None,
        query_type: str = "SELECT"
    ) -> Dict[str, Any]:
        """
        Generate SQL query from natural language using LLM with schema context.
        """
        try:
            # Search for relevant schema information
            schema_context = await self._get_schema_context_for_query(
                natural_language_query, target_tables
            )

            # Build prompt for LLM
            prompt = self._build_query_generation_prompt(
                natural_language_query=natural_language_query,
                schema_context=schema_context,
                query_type=query_type,
                database_flavor=self.database_flavor
            )

            # Generate query using LLM
            response = await self.llm.ask(
                prompt=prompt,
                model=self.llm.model,
                temperature=0.1  # Low temperature for more deterministic results
            )

            # Extract SQL query from response
            generated_query = self._extract_sql_from_response(response.output)

            # Validate query syntax
            validation_result = await self._validate_query_syntax(generated_query)

            result = {
                "query": generated_query,
                "query_type": query_type,
                "tables_used": self._extract_tables_from_query(generated_query),
                "schema_context_used": len(schema_context),
                "validation": validation_result,
                "natural_language_input": natural_language_query
            }

            return result

        except Exception as e:
            self.logger.error(f"Failed to generate query: {e}")
            raise

    async def _get_schema_context_for_query(
        self,
        natural_language_query: str,
        target_tables: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """Get relevant schema context for query generation."""
        if target_tables:
            # If specific tables are mentioned, get their metadata
            context = []
            for table_name in target_tables:
                table_info = await self.search_schema(
                    search_term=table_name,
                    search_type="tables",
                    limit=1
                )
                if table_info:
                    context.extend(table_info)
            return context
        else:
            # Search based on natural language query
            return await self.search_schema(
                search_term=natural_language_query,
                search_type="all",
                limit=5
            )

    def _build_query_generation_prompt(
        self,
        natural_language_query: str,
        schema_context: List[Dict[str, Any]],
        query_type: str,
        database_flavor: str
    ) -> str:
        """Build prompt for LLM query generation."""
        prompt = f"""
You are an expert SQL developer working with a {database_flavor} database.
Generate a {query_type} SQL query based on the natural language request and the provided schema information.

Natural Language Request: {natural_language_query}

Available Schema Information:
"""

        for i, context in enumerate(schema_context[:3], 1):  # Limit context to avoid token limits
            prompt += f"\n{i}. {context.get('content', '')}\n"

        prompt += f"""

Requirements:
1. Generate a valid {database_flavor} SQL query
2. Use proper {database_flavor} syntax and functions
3. Include appropriate WHERE clauses, JOINs, and filters based on the request
4. Return only the SQL query without explanations or markdown formatting
5. Ensure the query is optimized and follows best practices
6. Use table aliases for better readability when joining multiple tables

Query Type: {query_type}
Database: {database_flavor}

SQL Query:"""

        return prompt

    def _extract_sql_from_response(self, response_text: str) -> str:
        """Extract SQL query from LLM response."""
        # Remove markdown code blocks if present
        if "```sql" in response_text:
            lines = response_text.split('\n')
            sql_lines = []
            in_sql_block = False

            for line in lines:
                if line.strip().startswith("```sql"):
                    in_sql_block = True
                    continue
                elif line.strip() == "```" and in_sql_block:
                    break
                elif in_sql_block:
                    sql_lines.append(line)

            return '\n'.join(sql_lines).strip()
        else:
            # Clean up the response
            return response_text.strip()

    def _extract_tables_from_query(self, query: str) -> List[str]:
        """Extract table names from SQL query (simplified implementation)."""
        # Simple regex to find table names after FROM and JOIN keywords
        pattern = r'(?:FROM|JOIN)\s+(?:[\w\.]*\.)?(\w+)'
        matches = re.findall(pattern, query.upper())

        return list(set(matches))

    async def _validate_query_syntax(self, query: str) -> Dict[str, Any]:
        """Validate SQL query syntax without executing it."""
        try:
            explain_query = ""
            async with self.engine.begin() as conn:
                # Use EXPLAIN to validate syntax without execution
                if self.database_flavor == 'postgresql':
                    explain_query = f"EXPLAIN {query}"
                elif self.database_flavor == 'mysql':
                    explain_query = f"EXPLAIN {query}"
                elif self.database_flavor in ['sqlserver', 'mssql']:
                    # SQL Server doesn't support EXPLAIN, use SET NOEXEC ON
                    explain_query = f"SET NOEXEC ON; {query}; SET NOEXEC OFF;"

                await conn.execute(text(explain_query))

                return {
                    "valid": True,
                    "error": None,
                    "message": "Query syntax is valid"
                }

        except Exception as e:
            return {
                "valid": False,
                "error": str(e),
                "message": "Query syntax validation failed"
            }

    async def execute_query(self, query: str, limit: int = 100) -> Dict[str, Any]:
        """Execute SQL query against the database."""
        try:
            async with self.async_session_maker() as session:
                # Add LIMIT clause if not present for SELECT queries
                if query.strip().upper().startswith('SELECT') and 'LIMIT' not in query.upper():
                    query = f"{query.rstrip(';')} LIMIT {limit}"

                result = await session.execute(text(query))

                if query.strip().upper().startswith('SELECT'):
                    # For SELECT queries, return data
                    rows = result.fetchall()
                    columns = list(result.keys())

                    data = []
                    for row in rows:
                        data.append(dict(zip(columns, row)))

                    return {
                        "success": True,
                        "data": data,
                        "columns": columns,
                        "row_count": len(data),
                        "query": query
                    }
                else:
                    # For non-SELECT queries, commit and return affected rows
                    await session.commit()
                    return {
                        "success": True,
                        "affected_rows": result.rowcount,
                        "query": query,
                        "message": f"Query executed successfully. {result.rowcount} rows affected."
                    }

        except Exception as e:
            self.logger.error(f"Query execution failed: {e}")
            return {
                "success": False,
                "error": str(e),
                "query": query
            }

    async def close(self):
        """Close database connections."""
        if self.engine:
            await self.engine.dispose()


class SQLQueryExecutionTool(AbstractTool):
    """Tool for executing SQL queries against the database."""

    name = "execute_sql_query"
    description = "Execute SQL queries against the connected database"
    args_schema = SQLQueryExecutionArgs

    def __init__(self, agent: SQLDbAgent, **kwargs):
        super().__init__(**kwargs)
        self.agent = agent

    async def _execute(
        self,
        query: str,
        limit: int = 100,
        dry_run: bool = False
    ) -> ToolResult:
        """Execute SQL query or perform dry run validation."""
        try:
            if dry_run:
                # Only validate syntax
                validation = await self.agent._validate_query_syntax(query)
                return ToolResult(
                    status="success" if validation["valid"] else "error",
                    result=validation,
                    metadata={
                        "query": query,
                        "dry_run": True,
                        "limit": limit
                    }
                )
            else:
                # Execute query
                result = await self.agent.execute_query(query, limit)
                return ToolResult(
                    status="success" if result["success"] else "error",
                    result=result,
                    error=result.get("error"),
                    metadata={
                        "query": query,
                        "dry_run": False,
                        "limit": limit
                    }
                )

        except Exception as e:
            return ToolResult(
                status="error",
                result=None,
                error=str(e),
                metadata={"query": query}
            )


# Factory function for creating SQL agents with different flavors
def create_sql_agent(
    database_flavor: str,
    connection_string: str,
    schema_name: str = None,
    **kwargs
) -> SQLDbAgent:
    """
    Factory function to create SQL database agents for different flavors.

    Args:
        database_flavor: Database type ('postgresql', 'mysql', 'sqlserver')
        connection_string: Database connection string
        schema_name: Target schema name (defaults based on database type)
        **kwargs: Additional arguments for the agent

    Returns:
        Configured SQLDbAgent instance
    """
    # Set default schema names based on database flavor
    if schema_name is None:
        if database_flavor.lower() in ['postgresql', 'postgres']:
            schema_name = 'public'
        elif database_flavor.lower() == 'mysql':
            # MySQL doesn't use schemas in the same way, use database name
            schema_name = 'mysql'
        elif database_flavor.lower() in ['sqlserver', 'mssql']:
            schema_name = 'dbo'
        else:
            schema_name = 'public'

    return SQLDbAgent(
        database_flavor=database_flavor,
        connection_string=connection_string,
        schema_name=schema_name,
        **kwargs
    )


# Example usage patterns
"""
# PostgreSQL Example
pg_agent = create_sql_agent(
    database_flavor='postgresql',
    connection_string='postgresql://user:pass@localhost/dbname',
    schema_name='public'
)

# MySQL Example
mysql_agent = create_sql_agent(
    database_flavor='mysql',
    connection_string='mysql://user:pass@localhost/dbname'
)

# SQL Server Example
sqlserver_agent = create_sql_agent(
    database_flavor='sqlserver',
    connection_string='mssql://user:pass@server/database'
)

# Usage
await pg_agent.initialize_schema()

# Generate query from natural language
result = await pg_agent.generate_query(
    "Show me all products with inventory greater than 100 ordered by name"
)

# Execute the generated query
execution_result = await pg_agent.execute_query(result['query'])
"""
