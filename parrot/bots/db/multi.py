"""
Database Agents Integration Guide for AI-Parrot.

This module provides examples and utilities for integrating and using
the different database agents (SQL, InfluxDB, Elasticsearch) together.
"""

import asyncio
from typing import Dict, Any, List, Optional
from pathlib import Path
import json
from pydantic import Field
import argparse
# Import all database agents
from .abstract import AbstractDBAgent
from .sql import SQLDbAgent, create_sql_agent
from .influx import InfluxDBAgent, create_influxdb_agent
from .elastic import ElasticDbAgent, create_elasticsearch_agent

# Import base components
from ..abstract import AbstractBot
from ...stores.abstract import AbstractStore
from ...tools.abstract import AbstractTool, ToolResult, AbstractToolArgsSchema
from ...stores import supported_stores


class MultiDatabaseAgent(AbstractBot):
    """
    Multi-Database Agent that can work with multiple database types simultaneously.

    This agent coordinates between different database agents and can route queries
    to the appropriate database based on the natural language request.
    """

    def __init__(
        self,
        name: str = "MultiDatabaseAgent",
        database_configs: Dict[str, Dict[str, Any]] = None,
        knowledge_store: AbstractStore = None,
        **kwargs
    ):
        """
        Initialize Multi-Database Agent.

        Args:
            name: Agent name
            database_configs: Configuration for each database type
            knowledge_store: Shared knowledge store for all databases
        """
        super().__init__(name=name, **kwargs)

        self.database_configs = database_configs or {}
        self.knowledge_store = knowledge_store
        self.database_agents: Dict[str, AbstractDBAgent] = {}

        # Initialize database agents
        asyncio.create_task(self._initialize_database_agents())

    async def _initialize_database_agents(self):
        """Initialize all configured database agents."""
        for db_name, config in self.database_configs.items():
            try:
                agent = await self._create_database_agent(db_name, config)
                self.database_agents[db_name] = agent
                self.logger.info(f"Initialized {config['type']} agent: {db_name}")
            except Exception as e:
                self.logger.error(f"Failed to initialize {db_name}: {e}")

    async def _create_database_agent(self, db_name: str, config: Dict[str, Any]) -> AbstractDBAgent:
        """Create a database agent based on configuration."""
        db_type = config.get('type', '').lower()

        if db_type in ['postgresql', 'mysql', 'sqlserver']:
            agent = create_sql_agent(
                database_flavor=db_type,
                connection_string=config['connection_string'],
                schema_name=config.get('schema_name'),
                knowledge_store=self.knowledge_store,
                name=f"{db_name}_agent"
            )
        elif db_type == 'influxdb':
            agent = create_influxdb_agent(
                url=config['url'],
                token=config['token'],
                org=config['org'],
                bucket=config.get('bucket'),
                knowledge_store=self.knowledge_store,
                name=f"{db_name}_agent"
            )
        elif db_type == 'elasticsearch':
            agent = create_elasticsearch_agent(
                url=config.get('url'),
                username=config.get('username'),
                password=config.get('password'),
                api_key=config.get('api_key'),
                cloud_id=config.get('cloud_id'),
                knowledge_store=self.knowledge_store,
                name=f"{db_name}_agent"
            )
        else:
            raise ValueError(f"Unsupported database type: {db_type}")

        # Initialize the agent
        await agent.initialize_schema()
        return agent

    async def route_query_to_database(
        self,
        natural_language_query: str,
        preferred_database: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Route a natural language query to the most appropriate database.

        Args:
            natural_language_query: Natural language description of the query
            preferred_database: Specific database to use (optional)

        Returns:
            Query result with routing information
        """
        if preferred_database and preferred_database in self.database_agents:
            # Use specified database
            agent = self.database_agents[preferred_database]
            result = await agent.generate_query(natural_language_query)
            result['routed_to'] = preferred_database
            result['routing_reason'] = 'user_specified'
            return result

        # Auto-route based on query content
        best_agent, routing_reason = await self._determine_best_agent(natural_language_query)

        if best_agent:
            result = await best_agent.generate_query(natural_language_query)
            result['routed_to'] = self._get_agent_name(best_agent)
            result['routing_reason'] = routing_reason
            return result
        else:
            raise ValueError("No suitable database agent found for the query")

    async def _determine_best_agent(self, query: str) -> tuple[Optional[AbstractDBAgent], str]:
        """Determine the best database agent for a query."""
        query_lower = query.lower()

        # Time-series keywords suggest InfluxDB
        time_series_keywords = [
            'time series', 'over time', 'last hour', 'last day', 'last week',
            'trend', 'monitoring', 'metrics', 'sensor', 'measurement',
            'aggregateWindow', 'mean()', 'sum()', 'count()', 'range'
        ]

        # Document/search keywords suggest Elasticsearch
        document_keywords = [
            'search', 'text search', 'full text', 'documents', 'logs',
            'match', 'analyze', 'aggregation', 'bucket', 'terms'
        ]

        # SQL keywords suggest SQL database
        sql_keywords = [
            'join', 'table', 'foreign key', 'primary key', 'index',
            'transaction', 'acid', 'relational', 'normalize'
        ]

        # Score each agent type
        scores = {}

        for agent_name, agent in self.database_agents.items():
            score = 0

            if isinstance(agent, InfluxDBAgent):
                score += sum(1 for keyword in time_series_keywords if keyword in query_lower)
            elif isinstance(agent, ElasticDbAgent):
                score += sum(1 for keyword in document_keywords if keyword in query_lower)
            elif isinstance(agent, SQLDbAgent):
                score += sum(1 for keyword in sql_keywords if keyword in query_lower)

            scores[agent_name] = score

        if not scores:
            return None, "no_agents_available"

        # Return agent with highest score
        best_agent_name = max(scores, key=scores.get)
        best_score = scores[best_agent_name]

        if best_score > 0:
            return self.database_agents[best_agent_name], f"keyword_match_score_{best_score}"

        # If no clear winner, use first available agent
        first_agent_name = next(iter(self.database_agents))
        return self.database_agents[first_agent_name], "default_fallback"

    def _get_agent_name(self, agent: AbstractDBAgent) -> str:
        """Get the name/key of an agent."""
        for name, stored_agent in self.database_agents.items():
            if stored_agent is agent:
                return name
        return "unknown"

    async def search_across_databases(
        self,
        search_term: str,
        databases: Optional[List[str]] = None
    ) -> Dict[str, List[Dict[str, Any]]]:
        """Search for schema information across multiple databases."""
        results = {}

        target_databases = databases or list(self.database_agents.keys())

        for db_name in target_databases:
            if db_name in self.database_agents:
                try:
                    agent = self.database_agents[db_name]
                    search_results = await agent.search_schema(search_term)
                    results[db_name] = search_results
                except Exception as e:
                    self.logger.warning(f"Search failed for {db_name}: {e}")
                    results[db_name] = []

        return results

    async def get_database_summary(self) -> Dict[str, Any]:
        """Get a summary of all connected databases."""
        summary = {
            "total_databases": len(self.database_agents),
            "databases": {}
        }

        for db_name, agent in self.database_agents.items():
            try:
                if hasattr(agent, 'schema_metadata') and agent.schema_metadata:
                    metadata = agent.schema_metadata
                    summary["databases"][db_name] = {
                        "type": metadata.database_type,
                        "name": metadata.database_name,
                        "tables_count": len(metadata.tables),
                        "views_count": len(metadata.views),
                        "status": "connected"
                    }
                else:
                    summary["databases"][db_name] = {
                        "type": "unknown",
                        "status": "no_metadata"
                    }
            except Exception as e:
                summary["databases"][db_name] = {
                    "status": "error",
                    "error": str(e)
                }

        return summary

    async def close_all_connections(self):
        """Close all database connections."""
        for agent in self.database_agents.values():
            try:
                await agent.close()
            except Exception as e:
                self.logger.warning(f"Error closing agent connection: {e}")


# Configuration examples and utilities
class DatabaseConfigBuilder:
    """Helper class to build database configurations."""

    @staticmethod
    def postgresql_config(
        host: str,
        port: int = 5432,
        database: str = None,
        username: str = None,
        password: str = None,
        schema: str = "public"
    ) -> Dict[str, Any]:
        """Build PostgreSQL configuration."""
        connection_string = f"postgresql://{username}:{password}@{host}:{port}/{database}"
        return {
            "type": "postgresql",
            "connection_string": connection_string,
            "schema_name": schema
        }

    @staticmethod
    def mysql_config(
        host: str,
        port: int = 3306,
        database: str = None,
        username: str = None,
        password: str = None
    ) -> Dict[str, Any]:
        """Build MySQL configuration."""
        connection_string = f"mysql://{username}:{password}@{host}:{port}/{database}"
        return {
            "type": "mysql",
            "connection_string": connection_string
        }

    @staticmethod
    def influxdb_config(
        url: str,
        token: str,
        org: str,
        bucket: str = None
    ) -> Dict[str, Any]:
        """Build InfluxDB configuration."""
        return {
            "type": "influxdb",
            "url": url,
            "token": token,
            "org": org,
            "bucket": bucket
        }

    @staticmethod
    def elasticsearch_config(
        url: str = None,
        username: str = None,
        password: str = None,
        api_key: str = None,
        cloud_id: str = None
    ) -> Dict[str, Any]:
        """Build Elasticsearch configuration."""
        config = {"type": "elasticsearch"}

        if cloud_id:
            config["cloud_id"] = cloud_id
        else:
            config["url"] = url

        if api_key:
            config["api_key"] = api_key
        else:
            config["username"] = username
            config["password"] = password

        return config


# Example usage and integration patterns
async def example_multi_database_usage():
    """Example of using multiple database agents together."""

    # Build database configurations
    db_configs = {
        "main_db": DatabaseConfigBuilder.postgresql_config(
            host="localhost",
            database="myapp",
            username="user",
            password="pass"
        ),
        "metrics_db": DatabaseConfigBuilder.influxdb_config(
            url="http://localhost:8086",
            token="my-token",
            org="my-org",
            bucket="metrics"
        ),
        "search_db": DatabaseConfigBuilder.elasticsearch_config(
            url="http://localhost:9200",
            username="elastic",
            password="password"
        )
    }

    # Create multi-database agent
    multi_agent = MultiDatabaseAgent(
        name="CompanyDataAgent",
        database_configs=db_configs
    )

    # Wait for initialization
    await asyncio.sleep(2)

    # Example queries
    queries = [
        "Show me all users created in the last month",  # Should route to SQL
        "What's the average CPU usage over the last hour?",  # Should route to InfluxDB
        "Search for documents containing 'error' in the logs",  # Should route to Elasticsearch
    ]

    for query in queries:
        try:
            result = await multi_agent.route_query_to_database(query)
            print(f"Query: {query}")
            print(f"Routed to: {result['routed_to']}")
            print(f"Reason: {result['routing_reason']}")
            print(f"Generated query: {result['query']}")
            print("-" * 50)
        except Exception as e:
            print(f"Error processing query '{query}': {e}")

    # Search across all databases
    search_results = await multi_agent.search_across_databases("user")
    print("Search results for 'user':")
    for db_name, results in search_results.items():
        print(f"{db_name}: {len(results)} results")

    # Get database summary
    summary = await multi_agent.get_database_summary()
    print("Database summary:", json.dumps(summary, indent=2))

    # Clean up
    await multi_agent.close_all_connections()


async def example_individual_agent_usage():
    """Example of using individual database agents."""

    # SQL Agent example
    print("=== SQL Agent Example ===")
    sql_agent = create_sql_agent(
        database_flavor='postgresql',
        connection_string='postgresql://user:pass@localhost/db',
        schema_name='public'
    )

    await sql_agent.initialize_schema()

    sql_result = await sql_agent.generate_query(
        "Find all orders with total amount greater than 1000"
    )
    print(f"SQL Query: {sql_result['query']}")

    # InfluxDB Agent example
    print("\n=== InfluxDB Agent Example ===")
    influx_agent = create_influxdb_agent(
        url='http://localhost:8086',
        token='my-token',
        org='my-org',
        bucket='sensors'
    )

    await influx_agent.initialize_schema()

    influx_result = await influx_agent.generate_query(
        "Show average temperature by location over the last 24 hours"
    )
    print(f"Flux Query: {influx_result['query']}")

    # Elasticsearch Agent example
    print("\n=== Elasticsearch Agent Example ===")
    es_agent = create_elasticsearch_agent(
        url='http://localhost:9200',
        username='elastic',
        password='password'
    )

    await es_agent.initialize_schema()

    es_result = await es_agent.generate_query(
        "Find all log entries with status code 500 from the last hour"
    )
    print(f"Elasticsearch Query: {json.dumps(es_result['query'], indent=2)}")

    # Clean up
    await sql_agent.close()
    await influx_agent.close()
    await es_agent.close()


# Integration with AI-Parrot's existing components
class DatabaseAgentToolkit:
    """
    Toolkit for integrating database agents with AI-Parrot's tool system.
    Provides a unified interface for database operations across different database types.
    """

    def __init__(self, multi_agent: MultiDatabaseAgent):
        self.multi_agent = multi_agent

    def get_tools(self) -> List:
        """Get all database tools for use with AI-Parrot agents."""
        class DatabaseQueryArgs(AbstractToolArgsSchema):
            query: str = Field(description="Natural language database query")
            database: Optional[str] = Field(default=None, description="Specific database to use")
            execute: bool = Field(default=False, description="Whether to execute the generated query")

        class DatabaseSearchArgs(AbstractToolArgsSchema):
            search_term: str = Field(description="Term to search for in database schemas")
            databases: Optional[List[str]] = Field(default=None, description="Specific databases to search")

        class DatabaseQueryTool(AbstractTool):
            """Tool for generating and executing database queries."""
            name = "database_query"
            description = "Generate and optionally execute database queries from natural language"
            args_schema = DatabaseQueryArgs

            def __init__(self, toolkit):
                super().__init__()
                self.toolkit = toolkit

            async def _execute(
                self,
                query: str,
                database: Optional[str] = None,
                execute: bool = False
            ) -> ToolResult:
                try:
                    # Generate query
                    result = await self.toolkit.multi_agent.route_query_to_database(query, database)

                    if execute:
                        # Execute the generated query
                        routed_agent = self.toolkit.multi_agent.database_agents[result['routed_to']]
                        execution_result = await routed_agent.execute_query(result['query'])
                        result['execution_result'] = execution_result

                    return ToolResult(
                        status="success",
                        result=result,
                        metadata={
                            "natural_language_query": query,
                            "database_used": result.get('routed_to'),
                            "executed": execute
                        }
                    )
                except Exception as e:
                    return ToolResult(
                        status="error",
                        result=None,
                        error=str(e),
                        metadata={"query": query}
                    )

        class DatabaseSearchTool(AbstractTool):
            """Tool for searching across multiple databases."""
            name = "database_search"
            description = "Search for tables, fields, and schema information across databases"
            args_schema = DatabaseSearchArgs

            def __init__(self, toolkit):
                super().__init__()
                self.toolkit = toolkit

            async def _execute(
                self,
                search_term: str,
                databases: Optional[List[str]] = None
            ) -> ToolResult:
                try:
                    results = await self.toolkit.multi_agent.search_across_databases(
                        search_term,
                        databases
                    )

                    return ToolResult(
                        status="success",
                        result=results,
                        metadata={
                            "search_term": search_term,
                            "databases_searched": list(results.keys()),
                            "total_results": sum(len(r) for r in results.values())
                        }
                    )
                except Exception as e:
                    return ToolResult(
                        status="error",
                        result=None,
                        error=str(e),
                        metadata={"search_term": search_term}
                    )

        return [
            DatabaseQueryTool(self),
            DatabaseSearchTool(self)
        ]


# Configuration management
class DatabaseAgentConfig:
    """Configuration management for database agents."""

    def __init__(self, config_file: Optional[Path] = None):
        self.config_file = config_file or Path("database_agents.json")
        self.config_data = self._load_config()

    def _load_config(self) -> Dict[str, Any]:
        """Load configuration from file."""
        if self.config_file.exists():
            with open(self.config_file, 'r') as f:
                return json.load(f)
        return {"databases": {}, "settings": {}}

    def save_config(self):
        """Save configuration to file."""
        with open(self.config_file, 'w') as f:
            json.dump(self.config_data, f, indent=2)

    def add_database(self, name: str, config: Dict[str, Any]):
        """Add a database configuration."""
        self.config_data["databases"][name] = config
        self.save_config()

    def remove_database(self, name: str):
        """Remove a database configuration."""
        if name in self.config_data["databases"]:
            del self.config_data["databases"][name]
            self.save_config()

    def get_database_configs(self) -> Dict[str, Dict[str, Any]]:
        """Get all database configurations."""
        return self.config_data.get("databases", {})

    def set_setting(self, key: str, value: Any):
        """Set a configuration setting."""
        if "settings" not in self.config_data:
            self.config_data["settings"] = {}
        self.config_data["settings"][key] = value
        self.save_config()

    def get_setting(self, key: str, default: Any = None) -> Any:
        """Get a configuration setting."""
        return self.config_data.get("settings", {}).get(key, default)


# Factory for creating agents from configuration
class DatabaseAgentFactory:
    """Factory for creating database agents from configuration."""

    @staticmethod
    async def create_from_config(config_file: Optional[Path] = None) -> MultiDatabaseAgent:
        """Create MultiDatabaseAgent from configuration file."""
        config_manager = DatabaseAgentConfig(config_file)
        db_configs = config_manager.get_database_configs()

        if not db_configs:
            raise ValueError("No database configurations found")

        # Create knowledge store if configured
        knowledge_store = None
        knowledge_config = config_manager.get_setting("knowledge_store")
        if knowledge_config:
            knowledge_store = await DatabaseAgentFactory._create_knowledge_store(knowledge_config)

        return MultiDatabaseAgent(
            database_configs=db_configs,
            knowledge_store=knowledge_store
        )

    @staticmethod
    async def _create_knowledge_store(config: Dict[str, Any]):
        """Create knowledge store from configuration."""
        # This would integrate with AI-Parrot's existing store system

        store_type = config.get("type", "pgvector")
        if store_type in supported_stores:
            store_class = supported_stores[store_type]
            return store_class(**config.get("params", {}))

        return None


# Example configuration file structure
EXAMPLE_CONFIG = {
    "databases": {
        "main_postgres": {
            "type": "postgresql",
            "connection_string": "postgresql://user:pass@localhost:5432/myapp",
            "schema_name": "public"
        },
        "metrics_influx": {
            "type": "influxdb",
            "url": "http://localhost:8086",
            "token": "${INFLUX_TOKEN}",
            "org": "my-org",
            "bucket": "metrics"
        },
        "logs_elastic": {
            "type": "elasticsearch",
            "url": "http://localhost:9200",
            "username": "elastic",
            "password": "${ELASTIC_PASSWORD}"
        }
    },
    "settings": {
        "knowledge_store": {
            "type": "pgvector",
            "params": {
                "connection_string": "postgresql://user:pass@localhost:5432/knowledge",
                "collection_name": "database_schemas"
            }
        },
        "default_query_timeout": 30,
        "max_sample_records": 10,
        "auto_analyze_schema": True
    }
}


# Integration with AI-Parrot's existing bot system
def integrate_with_parrot_bot(bot: AbstractBot, database_configs: Dict[str, Dict[str, Any]]):
    """
    Integrate database agents with an existing AI-Parrot bot.

    Args:
        bot: Existing AI-Parrot bot instance
        database_configs: Database configurations
    """
    async def initialize_db_integration():
        # Create multi-database agent
        multi_agent = MultiDatabaseAgent(
            name=f"{bot.name}_DatabaseAgent",
            database_configs=database_configs,
            knowledge_store=getattr(bot, 'knowledge_store', None)
        )

        # Wait for initialization
        await asyncio.sleep(2)

        # Create toolkit
        toolkit = DatabaseAgentToolkit(multi_agent)

        # Add database tools to the bot
        for tool in toolkit.get_tools():
            bot.add_tool(tool)

        # Store reference for cleanup
        bot._database_multi_agent = multi_agent

        return multi_agent

    # Add initialization as a startup task
    asyncio.create_task(initialize_db_integration())


# Command-line interface for testing and management
async def cli_example():
    """Example CLI interface for database agents."""
    parser = argparse.ArgumentParser(description="Database Agents CLI")
    parser.add_argument("--config", type=Path, help="Configuration file path")
    parser.add_argument("--query", type=str, help="Natural language query to execute")
    parser.add_argument("--search", type=str, help="Search term for schema exploration")
    parser.add_argument("--list-databases", action="store_true", help="List all configured databases")
    parser.add_argument("--execute", action="store_true", help="Execute generated queries")

    args = parser.parse_args()

    try:
        # Create agent from configuration
        multi_agent = await DatabaseAgentFactory.create_from_config(args.config)

        if args.list_databases:
            summary = await multi_agent.get_database_summary()
            print("Configured Databases:")
            for db_name, info in summary["databases"].items():
                print(f"  {db_name}: {info['type']} ({info['status']})")

        if args.query:
            print(f"Processing query: {args.query}")
            result = await multi_agent.route_query_to_database(args.query)
            print(f"Routed to: {result['routed_to']}")
            print(f"Generated query: {result['query']}")

            if args.execute:
                agent = multi_agent.database_agents[result['routed_to']]
                execution_result = await agent.execute_query(result['query'])
                if execution_result.get('success'):
                    print(f"Results: {len(execution_result.get('data', []))} rows")
                else:
                    print(f"Execution failed: {execution_result.get('error')}")

        if args.search:
            print(f"Searching for: {args.search}")
            results = await multi_agent.search_across_databases(args.search)
            for db_name, search_results in results.items():
                print(f"{db_name}: {len(search_results)} matches")

        await multi_agent.close_all_connections()

    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    # Example usage
    print("Database Agents Integration Example")
    print("===================================")

    # You can run different examples:
    # asyncio.run(example_multi_database_usage())
    # asyncio.run(example_individual_agent_usage())
    # asyncio.run(cli_example())

    print("Run with: python -m parrot.agents.database.integration --help")
