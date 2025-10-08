"""
Enhanced SQL Database Agent Implementation for AI-Parrot.

Concrete implementation of AbstractDbAgent for SQL databases with support for:
- PostgreSQL, MySQL, and SQL Server
- Dictionary and string credentials
- Dual DSN generation for SQLAlchemy and asyncdb
- DatabaseQueryTool integration for query validation and execution
"""

from typing import Dict, Any, List, Optional, Union
import re
from urllib.parse import urlparse, quote_plus
from datetime import datetime
import pandas as pd
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text
from .abstract import AbstractDBAgent
from .tools import DatabaseSchema, TableMetadata
from ...models import AIMessage
from ...tools.databasequery import DatabaseQueryTool
from ...tools import ToolResult


class SQLAgent(AbstractDBAgent):
    """
    SQL Database Agent with dual DSN support and DatabaseQueryTool integration.

    Supports PostgreSQL, MySQL, and SQL Server with both dictionary and string credentials.
    """

    # Database flavor mappings for SQLAlchemy
    SQLALCHEMY_DIALECT_MAPPING = {
        'postgresql': 'postgresql+asyncpg',
        'pg': 'postgresql+asyncpg',
        'postgres': 'postgresql+asyncpg',
        'mysql': 'mysql+aiomysql',
        'sqlserver': 'mssql+aioodbc',
        'mssql': 'mssql+aioodbc'
    }

    # Default ports for databases
    DEFAULT_PORTS = {
        'postgresql': 5432,
        'postgres': 5432,
        'mysql': 3306,
        'sqlserver': 1433,
        'mssql': 1433
    }

    def __init__(
        self,
        name: str = "SQLAgent",
        credentials: Union[str, Dict[str, Any]] = None,
        database_flavor: str = "postgresql",
        schema_name: str = "public",
        max_sample_rows: int = 2,
        **kwargs
    ):
        """
        Initialize SQL Database Agent.

        Args:
            name: Agent name
            credentials: Connection credentials (dict or connection string)
            database_flavor: Database type (postgresql, mysql, sqlserver)
            schema_name: Target schema name
            max_sample_rows: Maximum rows to sample from each table
        """
        self.database_flavor = database_flavor.lower()
        self.max_sample_rows = max_sample_rows
        self.async_session_maker = None

        # DSN strings for different purposes
        self.discovery_dsn = None  # SQLAlchemy format for schema discovery
        self.dsn = None            # asyncdb format for DatabaseQueryTool
        self.credentials = None
        self.connection_dict = None
        if isinstance(credentials, dict):
            self.connection_dict = credentials

        # Validate database flavor
        if self.database_flavor not in self.SQLALCHEMY_DIALECT_MAPPING:
            raise ValueError(
                f"Unsupported database flavor: {database_flavor}"
            )

        super().__init__(
            name=name,
            credentials=credentials,
            schema_name=schema_name,
            **kwargs
        )

        # Process credentials and generate DSNs
        self._process_credentials(credentials)

        # Add SQL-specific tools
        self._setup_sql_tools()

    def _dsn_for_sqlalchemy(self, connection_string: str) -> str:
        """Adapt connection string for SQLAlchemy async drivers."""
        parsed = urlparse(connection_string)

        if parsed.scheme.startswith('postgresql') and '+asyncpg' not in parsed.scheme:
            return connection_string.replace('postgresql://', 'postgresql+asyncpg://')
        elif parsed.scheme.startswith('postgres') and '+asyncpg' not in parsed.scheme:
            return connection_string.replace('postgres://', 'postgresql+asyncpg://')
        elif parsed.scheme.startswith('mysql') and '+aiomysql' not in parsed.scheme:
            return connection_string.replace('mysql://', 'mysql+aiomysql://')
        elif parsed.scheme.startswith('mssql') and '+aioodbc' not in parsed.scheme:
            return connection_string.replace('mssql://', 'mssql+aioodbc://')

        return connection_string

    def _dsn_for_asyncdb(self, connection_string: str) -> str:
        """Adapt connection string for asyncdb format."""
        parsed = urlparse(connection_string)

        # Check if already in asyncdb format:
        if parsed.scheme in ['postgres', 'mysql', 'mssql']:
            return connection_string

        # Convert SQLAlchemy formats to asyncdb formats
        if parsed.scheme.startswith('postgresql'):
            return connection_string.replace(
                'postgresql+asyncpg://', 'postgres://'
            ).replace('postgresql://', 'postgres://')
        elif parsed.scheme.startswith('mysql'):
            return connection_string.replace(
                'mysql+aiomysql://', 'mysql://'
            ).replace('mysql://', 'mysql://')
        elif parsed.scheme.startswith('mssql'):
            return connection_string.replace(
                'mssql+aioodbc://', 'mssql://'
            ).replace('mssql://', 'mssql://')

        return connection_string

    def _process_credentials(self, credentials: Union[str, Dict[str, Any]]) -> None:
        """
        Process credentials and generate both discovery_dsn and dsn.

        Args:
            credentials: Either connection string or dictionary with connection params
        """
        if isinstance(credentials, str):
            # Connection string provided
            self.connection_string = credentials
            self.discovery_dsn = self._dsn_for_sqlalchemy(credentials)
            self.dsn = self._dsn_for_asyncdb(credentials)
            self.credentials = {}
        elif isinstance(credentials, dict):
            # Dictionary credentials provided
            self.connection_dict = credentials
            self.discovery_dsn = self._build_sqlalchemy_dsn_from_dict(credentials)
            self.dsn = self._build_asyncdb_dsn_from_dict(credentials)
            self.connection_string = self.discovery_dsn
            self.credentials = credentials
        else:
            raise ValueError(
                "Credentials must be either a connection string or dictionary"
            )

    def _build_sqlalchemy_dsn_from_dict(self, creds: Dict[str, Any]) -> str:
        """
        Build SQLAlchemy DSN from credentials dictionary.

        Args:
            creds: Dictionary with keys like host, port, database, username, password

        Returns:
            SQLAlchemy-compatible connection string
        """
        # Extract credentials with defaults
        host = creds.get('host', 'localhost')
        port = creds.get('port', self.DEFAULT_PORTS.get(self.database_flavor, 5432))
        database = creds.get('database', creds.get('dbname', 'postgres'))
        username = creds.get('username', creds.get('user', 'postgres'))
        password = creds.get('password', creds.get('pwd', ''))

        # URL encode password to handle special characters
        encoded_password = quote_plus(str(password)) if password else ''

        # Get SQLAlchemy dialect
        dialect = self.SQLALCHEMY_DIALECT_MAPPING[self.database_flavor]

        # Build connection string
        if encoded_password:
            dsn = f"{dialect}://{username}:{encoded_password}@{host}:{port}/{database}"
        else:
            dsn = f"{dialect}://{username}@{host}:{port}/{database}"

        # Add any additional parameters
        params = []
        for key, value in creds.items():
            if key not in ['host', 'port', 'database', 'dbname', 'username', 'user', 'password', 'pwd']:
                params.append(f"{key}={value}")

        if params:
            dsn += "?" + "&".join(params)

        return dsn

    def _build_asyncdb_dsn_from_dict(self, creds: Dict[str, Any]) -> str:
        """
        Build asyncdb DSN from credentials dictionary.

        Args:
            creds: Dictionary with connection parameters

        Returns:
            asyncdb-compatible connection string (postgres://...)
        """
        # Extract credentials
        host = creds.get('host', 'localhost')
        port = creds.get('port', self.DEFAULT_PORTS.get(self.database_flavor, 5432))
        database = creds.get('database', creds.get('dbname', 'postgres'))
        username = creds.get('username', creds.get('user', 'postgres'))
        password = creds.get('password', creds.get('pwd', ''))

        # URL encode password
        encoded_password = quote_plus(str(password)) if password else ''

        # Get asyncdb scheme (postgres for PostgreSQL regardless of flavor name)
        if self.database_flavor in ['postgresql', 'postgres']:
            scheme = 'postgres'
        elif self.database_flavor == 'mysql':
            scheme = 'mysql'
        elif self.database_flavor in ['sqlserver', 'mssql']:
            scheme = 'mssql'
        else:
            scheme = 'postgres'  # Default fallback

        # Build DSN
        if encoded_password:
            dsn = f"{scheme}://{username}:{encoded_password}@{host}:{port}/{database}"
        else:
            dsn = f"{scheme}://{username}@{host}:{port}/{database}"

        return dsn

    def _setup_sql_tools(self):
        """Setup SQL-specific tools including DatabaseQueryTool."""
        # The DatabaseQueryTool should already be registered in the parent class
        # We just need to ensure it's configured properly
        pass

    async def connect_database(self) -> None:
        """Connect to the SQL database using SQLAlchemy async engine."""
        if not self.discovery_dsn:
            raise ValueError("Discovery DSN is required")

        try:
            # Create async engine for schema discovery
            self.engine = create_async_engine(
                self.discovery_dsn,
                echo=False,
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

            self.logger.info(
                f"Successfully connected to {self.database_flavor} database using SQLAlchemy"
            )

            # Test DatabaseQueryTool connection
            await self._test_database_query_tool()

        except Exception as e:
            self.logger.error(f"Failed to connect to database: {e}")
            raise

    async def _test_database_query_tool(self) -> None:
        """Test DatabaseQueryTool connection."""
        try:
            # Get database query tool from registered tools
            db_tool = self.tool_manager.get_tool('DatabaseQueryTool')
            if db_tool:
                # Test with a simple query
                test_result = await db_tool.execute(
                    driver='pg' if self.database_flavor in ['postgresql', 'postgres', 'pg'] else self.database_flavor,
                    query="SELECT 1 as test_column LIMIT 1",
                    dsn=self.dsn,
                    credentials=self.credentials or None,
                    output_format='native'
                )

                if test_result.status == "success":
                    self.logger.debug(
                        "DatabaseQueryTool connection test successful"
                    )
                else:
                    self.logger.warning(
                        f"DatabaseQueryTool test failed: {test_result.error}"
                    )
            else:
                self.logger.warning(
                    "DatabaseQueryTool not found in registered tools"
                )

        except Exception as e:
            self.logger.warning(
                f"DatabaseQueryTool test failed: {e}"
            )

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

                # Extract views metadata (simplified for now)
                views = []

                schema_metadata = DatabaseSchema(
                    database_name=database_name or "unknown",
                    database_type=self.database_flavor,
                    tables=tables,
                    views=views,
                    functions=[],
                    procedures=[],
                    metadata={
                        "schema_name": self.schema_name,
                        "extraction_timestamp": datetime.now().isoformat(),
                        "total_tables": len(tables),
                        "total_views": len(views),
                        "discovery_dsn": self.discovery_dsn,
                        "asyncdb_dsn": self.dsn
                    }
                )

                self.logger.info(
                    f"Extracted metadata for {len(tables)} tables"
                )

                return schema_metadata

        except Exception as e:
            self.logger.error(f"Failed to extract schema metadata: {e}")
            raise

    async def _get_database_name_query(self) -> str:
        """Get database name query based on database flavor."""
        if self.database_flavor in ['postgresql', 'postgres']:
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

        # Get table names
        if self.database_flavor in ['postgresql', 'postgres']:
            table_query = """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = :schema_name
                AND table_type = 'BASE TABLE'
                ORDER BY table_name
            """
        elif self.database_flavor == 'mysql':
            table_query = """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = :schema_name
                AND table_type = 'BASE TABLE'
                ORDER BY table_name
            """
        else:  # SQL Server
            table_query = """
                SELECT table_name
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

        # Get sample data using DatabaseQueryTool
        sample_data = await self._get_sample_data_via_tool(table_name)

        return TableMetadata(
            name=table_name,
            schema=self.schema_name,
            columns=columns,
            primary_keys=primary_keys,
            foreign_keys=foreign_keys,
            indexes=[],  # Simplified for now
            description=None,  # Simplified for now
            sample_data=sample_data
        )

    async def _get_table_columns(self, conn, table_name: str) -> List[Dict[str, Any]]:
        """Get column information for a table."""
        if self.database_flavor in ['postgresql', 'postgres']:
            query = """
                SELECT
                    column_name,
                    data_type,
                    is_nullable,
                    column_default,
                    character_maximum_length,
                    numeric_precision,
                    numeric_scale
                FROM information_schema.columns
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
                    numeric_scale
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
                    numeric_scale
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
                "scale": row[6]
            })

        return columns

    async def _get_primary_keys(self, conn, table_name: str) -> List[str]:
        """Get primary key columns for a table."""
        if self.database_flavor in ['postgresql', 'postgres']:
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
        else:  # MySQL and SQL Server
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

    async def _get_sample_data_via_tool(self, table_name: str) -> List[Dict[str, Any]]:
        """Get sample data using DatabaseQueryTool."""
        try:
            # Get database query tool
            db_tool = self.tool_manager.get_tool('DatabaseQueryTool')
            if not db_tool:
                self.logger.warning("DatabaseQueryTool not found")
                return []

            # Build sample query
            full_table_name = f'"{self.schema_name}"."{table_name}"' if self.schema_name != 'public' else f'"{table_name}"'
            sample_query = f"SELECT * FROM {full_table_name} LIMIT {self.max_sample_rows}"

            # Execute query
            result = await db_tool.execute(
                driver='pg' if self.database_flavor in ['postgresql', 'postgres'] else self.database_flavor,
                query=sample_query,
                dsn=self.dsn,
                credentials=self.connection_dict,
                output_format='json'
            )
            if result.status == "success":
                return result.result
            else:
                self.logger.warning(f"Could not get sample data for {table_name}: {result.error}")
                return []

        except Exception as e:
            self.logger.warning(f"Error getting sample data for {table_name}: {e}")
            return []

    async def generate_query(
        self,
        natural_language_query: str,
        target_tables: Optional[List[str]] = None,
        query_type: str = "SELECT"
    ) -> Dict[str, Any]:
        """Generate SQL query from natural language and validate it."""
        try:
            # Get schema context
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
            response = await self._llm.ask(
                prompt=prompt,
                model=self._llm_model,
                temperature=0.0  # Zero temperature for deterministic results
            )

            # Extract SQL query from response
            generated_query = self._extract_sql_from_response(str(response.output))

            # Validate query using DatabaseQueryTool with LIMIT 0
            validation_result = await self._validate_query_with_tool(generated_query)

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

    async def _validate_query_with_tool(self, query: str) -> Dict[str, Any]:
        """Validate query using DatabaseQueryTool with LIMIT 0."""
        try:
            # Get database query tool
            db_tool = None
            for tool in self.tools:
                if isinstance(tool, DatabaseQueryTool):
                    db_tool = tool
                    break

            if not db_tool:
                return {
                    "valid": False,
                    "error": "DatabaseQueryTool not available",
                    "method": "tool_validation"
                }

            # Modify query to add LIMIT 0 for validation (no data returned)
            if query.strip().upper().startswith('SELECT'):
                validation_query = f"SELECT * FROM ({query.rstrip(';')}) AS validation_subquery LIMIT 0"
            else:
                # For non-SELECT queries, we can't easily validate without risk
                validation_query = query

            # Execute validation query
            result = await db_tool.execute(
                driver='pg' if self.database_flavor in ['postgresql', 'postgres'] else self.database_flavor,
                query=validation_query,
                dsn=self.dsn,
                credentials=self.connection_dict,
                output_format='native'
            )

            return {
                "valid": result.status == "success",
                "error": result.error if result.status == "error" else None,
                "method": "database_query_tool",
                "validation_query": validation_query
            }

        except Exception as e:
            return {
                "valid": False,
                "error": str(e),
                "method": "tool_validation"
            }

    async def execute_query(self, query: str, limit: int = 200) -> Dict[str, Any]:
        """Execute SQL query and return results using DatabaseQueryTool."""
        try:
            # Get database query tool
            db_tool = self.tool_manager.get_tool('DatabaseQueryTool')
            if not db_tool:
                db_tool = None

            if not db_tool:
                return {
                    "success": False,
                    "error": "DatabaseQueryTool not available",
                    "query": query
                }

            # Add limit for SELECT queries if not present
            execution_query = query
            result = None
            if query.strip().upper().startswith('SELECT') and 'LIMIT' not in query.upper():
                execution_query = f"{query.rstrip(';')} LIMIT {limit}"

            # Execute query (return a ToolResult)
            result = await db_tool.execute(
                driver='pg' if self.database_flavor in ['postgresql', 'postgres'] else self.database_flavor,
                query=execution_query,
                dsn=self.dsn,
                credentials=self.connection_dict,
                output_format='pandas'
            )

            if result.status == "success":
                data = result.result
                columns = data.columns.tolist() if not data.empty else []
                row_count = len(data) if not data.empty else 0
                return {
                    "success": True,
                    "data": data,
                    "columns": columns,
                    "row_count": row_count,
                    "query": execution_query,
                    "tool_used": "DatabaseQueryTool",
                    "raw_result": result
                }
            else:
                return {
                    "success": False,
                    "error": result.error,
                    "query": execution_query,
                    "tool_used": "DatabaseQueryTool",
                    "raw_result": result
                }

        except Exception as e:
            self.logger.error(f"Query execution failed: {e}")
            return {
                "success": False,
                "error": str(e),
                "query": query,
                "tool_used": "DatabaseQueryTool",
                "raw_result": None
            }

    async def _get_schema_context_for_query(
        self,
        natural_language_query: str,
        target_tables: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """Get relevant schema context for query generation."""
        if target_tables:
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
Generate a clean, efficient {query_type} SQL query based on the natural language request and schema information.

Natural Language Request: {natural_language_query}

Available Schema Information:
"""

        for i, context in enumerate(schema_context[:3], 1):
            prompt += f"\n{i}. {context.get('content', '')}\n"

        prompt += f"""
Requirements:
1. Generate valid {database_flavor} SQL with clean formatting
2. Use appropriate {database_flavor} syntax and functions
3. Use simple column names unless JOINs require qualification
4. Use table aliases for readability in JOINs
5. Only use double quotes for identifiers with special characters
6. Include appropriate WHERE clauses and filters
7. Optimize for performance and readability
8. Return ONLY the SQL query without explanations or formatting

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
            return response_text.strip()

    async def ask(
        self,
        prompt: str,
        user_context: str = "",
        context: str = "",
        return_results: bool = True,  # New parameter to control query execution
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        use_conversation_history: bool = True,
        **kwargs
    ) -> AIMessage:
        """
        Enhanced ask method that can automatically execute generated SQL queries.

        Args:
            prompt: The user's question about the database
            user_context: User-specific context for database interaction
            context: Additional context about data location, schema guidance
            return_results: If True, automatically execute generated SQL queries and return data
            session_id: Session identifier for conversation history
            user_id: User identifier
            use_conversation_history: Whether to use conversation history
            **kwargs: Additional arguments for LLM

        Returns:
            AIMessage: The response from the LLM, potentially enhanced with query results
        """
        # First, get the standard response from the parent method
        response = await super().ask(
            prompt=prompt,
            user_context=user_context,
            context=context,
            session_id=session_id,
            user_id=user_id,
            use_conversation_history=use_conversation_history,
            **kwargs
        )

        # If return_results is False, return the response as-is
        if not return_results:
            return response

        # Try to extract and execute SQL queries from the response
        try:
            response_text = str(response.output) if response.output else ""

            # Extract SQL queries from the response
            sql_queries = self._extract_queries(response_text)

            if sql_queries:
                # Execute the first/main SQL query
                main_query = sql_queries[0]
                self.logger.debug(
                    f"Auto-executing extracted query: {main_query[:100]}..."
                )

                # Execute the query
                result = await self.execute_query(
                    query=main_query
                )
                # Preserve original response
                response.response = response_text
                # is the dataframe:
                response.output = result.get('data', None)
                response.raw_response = result # Preserve raw ToolResult

                # Add execution metadata if response has metadata attribute
                if hasattr(response, 'metadata') and response.metadata:
                    response.metadata.update({
                        'auto_executed_query': True,
                        'executed_query': main_query,
                        'execution_success': result.get('status') == 'success',
                        'row_count': result.get('row_count', 0),
                        'columns': result.get('columns', []),
                        'error': result.get('error', None)
                    })

        except Exception as e:
            self.logger.warning(
                f"Failed to auto-execute query: {e}"
            )
            # Don't fail the entire request, just log the warning
            # The user still gets the explanation even if execution fails

        return response

    def _extract_queries(self, response_text: str) -> List[str]:
        """
        Extract SQL queries from LLM response text.

        Args:
            response_text: The full response text from the LLM

        Returns:
            List of extracted SQL queries
        """
        queries = []

        # Method 1: Extract from markdown code blocks
        sql_pattern = r'```sql\n(.*?)\n```'
        matches = re.findall(sql_pattern, response_text, re.DOTALL | re.IGNORECASE)

        for match in matches:
            cleaned_query = match.strip()
            if cleaned_query and not cleaned_query.lower().startswith('--'):
                queries.append(cleaned_query)

        # Method 2: If no markdown blocks, look for SQL-like patterns
        if not queries:
            # Look for common SQL patterns
            sql_keywords = r'\b(SELECT|WITH|SHOW|DESCRIBE|EXPLAIN)\b'
            lines = response_text.split('\n')
            current_query = []
            in_query = False

            for line in lines:
                line = line.strip()
                if re.search(sql_keywords, line, re.IGNORECASE):
                    in_query = True
                    current_query = [line]
                elif in_query:
                    if line.endswith(';') or not line:
                        if line.endswith(';'):
                            current_query.append(line)
                        query = '\n'.join(current_query).strip()
                        if query:
                            queries.append(query)
                        in_query = False
                        current_query = []
                    else:
                        current_query.append(line)

        # Clean up queries
        cleaned_queries = []
        for query in queries:
            # Remove common prefixes/suffixes
            query = re.sub(r'^```sql\s*', '', query, flags=re.IGNORECASE)
            query = re.sub(r'\s*```$', '', query)
            query = query.strip()

            # Basic validation - should contain SELECT, WITH, etc.
            if re.search(r'\b(SELECT|WITH|SHOW|DESCRIBE|EXPLAIN)\b', query, re.IGNORECASE):
                cleaned_queries.append(query)

        return cleaned_queries

    def _extract_tables_from_query(self, query: str) -> List[str]:
        """Extract table names from SQL query."""
        pattern = r'(?:FROM|JOIN)\s+(?:[\w\.]*\.)?(\w+)'
        matches = re.findall(pattern, query.upper())
        return list(set(matches))

    async def cleanup(self) -> None:
        """Cleanup resources."""
        if self.engine:
            await self.engine.dispose()
        await super().cleanup()




# Factory function for creating enhanced SQL agents
def create_sql_agent(
    database_flavor: str,
    credentials: Union[str, Dict[str, Any]],
    schema_name: str = None,
    **kwargs
) -> SQLAgent:
    """
    Factory function to create SQL database agents.

    Args:
        database_flavor: Database type ('postgresql', 'mysql', 'sqlserver')
        credentials: Connection credentials (string or dict)
        schema_name: Target schema name
        **kwargs: Additional arguments

    Returns:
        Configured SQLAgent instance
    """
    # Set default schema names
    if schema_name is None:
        if database_flavor.lower() in ['postgresql', 'postgres']:
            schema_name = 'public'
        elif database_flavor.lower() == 'mysql':
            schema_name = 'mysql'
        elif database_flavor.lower() in ['sqlserver', 'mssql']:
            schema_name = 'dbo'
        else:
            schema_name = 'public'

    return SQLAgent(
        database_flavor=database_flavor,
        credentials=credentials,
        schema_name=schema_name,
        **kwargs
    )


# Example usage
"""
# Dictionary credentials example
pg_creds = {
    'host': 'localhost',
    'port': 5432,
    'database': 'sales_db',
    'username': 'user',
    'password': 'password'
}

pg_agent = create_sql_agent(
    database_flavor='postgresql',
    credentials=pg_creds,
    schema_name='public'
)

# Connection string example
mysql_agent = create_sql_agent(
    database_flavor='mysql',
    credentials='mysql://user:pass@localhost/dbname'
)

# Usage
await pg_agent.initialize_schema()

# Generate and execute query
query_result = await pg_agent.generate_query(
    "Show me all customers from the East region with their order totals"
)

execution_result = await pg_agent.execute_query(query_result['query'])
print(f"Query: {execution_result['query']}")
print(f"Data: {execution_result['data']}")
"""
