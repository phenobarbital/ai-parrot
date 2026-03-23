"""
Elasticsearch/OpenSearch Tool for AI-Parrot
Enables AI agents to query Elasticsearch indices, search logs, and extract metrics
"""
from typing import Optional, List, Dict, Any, Literal
from datetime import datetime, timedelta, timezone
from enum import Enum
import re
import json
from pydantic import Field, field_validator
from navconfig import config
from asyncdb import AsyncDB
from asyncdb.drivers.elastic import ElasticConfig
from .abstract import (
    AbstractTool,
    AbstractToolArgsSchema,
    ToolResult
)


class ElasticsearchOperation(str, Enum):
    """Available Elasticsearch operations"""
    SEARCH = "search"
    QUERY_LOGS = "query_logs"
    GET_METRICS = "get_metrics"
    AGGREGATE = "aggregate"
    LIST_INDICES = "list_indices"
    GET_DOCUMENT = "get_document"
    COUNT_DOCUMENTS = "count_documents"
    ANALYZE_LOGS = "analyze_logs"


class ElasticsearchToolArgs(AbstractToolArgsSchema):
    """Arguments schema for Elasticsearch operations"""

    operation: ElasticsearchOperation = Field(
        ...,
        description=(
            "Elasticsearch operation to perform:\n"
            "- 'search': Execute a search query using Elasticsearch DSL\n"
            "- 'query_logs': Query logs with filters and time ranges (Logstash format)\n"
            "- 'get_metrics': Extract metrics from log entries\n"
            "- 'aggregate': Perform aggregations on data\n"
            "- 'list_indices': List all available indices\n"
            "- 'get_document': Get a specific document by ID\n"
            "- 'count_documents': Count documents matching criteria\n"
            "- 'analyze_logs': Analyze log patterns and extract insights"
        )
    )

    # Index parameters
    index: Optional[str] = Field(
        None,
        description="Elasticsearch index name (e.g., 'logstash-*', 'app-logs-2024')"
    )

    # Query parameters
    query: Optional[Dict[str, Any]] = Field(
        None,
        description=(
            "Elasticsearch query DSL as a dictionary. "
            "Example: {'match': {'message': 'error'}}"
        )
    )

    query_string: Optional[str] = Field(
        None,
        description=(
            "Simple query string for searching. "
            "Examples: 'status:500', 'error AND timeout', 'user:john'"
        )
    )

    # Log-specific parameters
    log_level: Optional[Literal["DEBUG", "INFO", "WARN", "ERROR", "FATAL"]] = Field(
        None,
        description="Filter logs by level (for Logstash-formatted logs)"
    )

    message_filter: Optional[str] = Field(
        None,
        description="Filter log messages containing this text"
    )

    # Time range parameters
    start_time: Optional[str] = Field(
        None,
        description=(
            "Start time for query (ISO format or relative like '-1h', '-30m', '-7d'). "
            "Examples: '2024-01-01T00:00:00', '-1h', '-24h'"
        )
    )

    end_time: Optional[str] = Field(
        None,
        description="End time for query (ISO format or 'now'). Default: now"
    )

    # Aggregation parameters
    aggregation: Optional[Dict[str, Any]] = Field(
        None,
        description=(
            "Elasticsearch aggregation specification. "
            "Example: {'terms': {'field': 'status.keyword', 'size': 10}}"
        )
    )

    metric_field: Optional[str] = Field(
        None,
        description="Field to extract metrics from (e.g., 'response_time', 'cpu_usage')"
    )

    metric_type: Optional[Literal["avg", "sum", "min", "max", "count", "percentiles"]] = Field(
        "avg",
        description="Type of metric aggregation to perform"
    )

    # General parameters
    size: Optional[int] = Field(
        100,
        description="Maximum number of results to return (default: 100)"
    )

    sort: Optional[List[Dict[str, Any]]] = Field(
        None,
        description=(
            "Sort specification as list of dicts. "
            "Example: [{'@timestamp': {'order': 'desc'}}]"
        )
    )

    fields: Optional[List[str]] = Field(
        None,
        description="Specific fields to return in results"
    )

    # Document operations
    document_id: Optional[str] = Field(
        None,
        description="Document ID for get_document operation"
    )

    # Analysis parameters
    group_by: Optional[str] = Field(
        None,
        description="Field to group by for log analysis (e.g., 'host.keyword', 'level.keyword')"
    )

    time_interval: Optional[str] = Field(
        "1h",
        description="Time interval for bucketing (e.g., '5m', '1h', '1d')"
    )

    @field_validator('start_time', mode='before')
    @classmethod
    def parse_time(cls, v):
        """Parse time string to timestamp"""
        return v  # Will be parsed in the tool

    @field_validator('end_time', mode='before')
    @classmethod
    def parse_end_time(cls, v):
        """Parse end time string to timestamp"""
        return v  # Will be parsed in the tool


class ElasticsearchTool(AbstractTool):
    """
    Tool for querying Elasticsearch/OpenSearch indices and analyzing logs.

    Capabilities:
    - Execute complex searches using Elasticsearch DSL
    - Query and analyze logs (especially Logstash-formatted logs)
    - Extract metrics from log entries
    - Perform aggregations and analytics
    - List indices and explore data structure
    - Retrieve specific documents

    Example Usage:
        # Query error logs in last hour
        {
            "operation": "query_logs",
            "index": "logstash-*",
            "log_level": "ERROR",
            "start_time": "-1h"
        }

        # Get average response time metrics
        {
            "operation": "get_metrics",
            "index": "app-logs-*",
            "metric_field": "response_time",
            "metric_type": "avg",
            "start_time": "-24h"
        }

        # Analyze log patterns
        {
            "operation": "analyze_logs",
            "index": "logstash-*",
            "group_by": "level.keyword",
            "time_interval": "1h",
            "start_time": "-7d"
        }
    """

    name: str = "elasticsearch_tool"
    description: str = (
        "Query Elasticsearch/OpenSearch indices, search logs, and extract metrics. "
        "Supports complex queries, aggregations, and log analysis."
    )
    args_schema: type[AbstractToolArgsSchema] = ElasticsearchToolArgs

    def __init__(
        self,
        host: str = None,
        port: int = None,
        user: str = None,
        password: str = None,
        protocol: str = "http",
        default_index: str = "logstash-*",
        client_type: str = "auto",
        **kwargs
    ):
        """
        Initialize Elasticsearch tool.

        Args:
            host: Elasticsearch host (from ELASTICSEARCH_HOST env var if not provided)
            port: Elasticsearch port (from ELASTICSEARCH_PORT env var if not provided)
            user: Elasticsearch user (from ELASTICSEARCH_USER env var if not provided)
            password: Elasticsearch password (from ELASTICSEARCH_PASSWORD env var if not provided)
            protocol: Connection protocol (http or https, from ELASTICSEARCH_PROTOCOL env var)
            default_index: Default index to query
            client_type: Client type ('elasticsearch', 'opensearch', or 'auto')
            **kwargs: Additional parameters
        """
        super().__init__(**kwargs)
        # Import config for environment variables
        self.host = host or config.get('ELASTICSEARCH_HOST', fallback='localhost')
        self.port = port or int(config.get('ELASTICSEARCH_PORT', fallback='9200'))
        self.user = user or config.get('ELASTICSEARCH_USER')
        self.password = password or config.get('ELASTICSEARCH_PASSWORD')
        self.protocol = protocol or config.get('ELASTICSEARCH_PROTOCOL', fallback='http')
        self.default_index = default_index or config.get(
            'ELASTICSEARCH_INDEX',
            fallback='logstash-*'
        )
        self.client_type = client_type or config.get(
            'ELASTICSEARCH_CLIENT_TYPE', fallback='auto'
        )

        # Initialize AsyncDB connection
        self.config = ElasticConfig(
            host=self.host,
            port=self.port,
            user=self.user,
            password=self.password,
            db=self.default_index,
            protocol=self.protocol
        )

        self._db = AsyncDB(
            'elastic',
            params=self.config,
            client_type=self.client_type
        )

    def _parse_relative_time(self, time_str: str) -> datetime:
        """
        Parse relative time strings like '-1h', '-30m', '-7d'.

        Args:
            time_str: Time string (ISO format, 'now', or relative like '-1h')

        Returns:
            datetime object
        """
        if time_str == 'now' or time_str is None:
            return datetime.now(timezone.utc)

        # Check if it's a relative time
        if time_str.startswith('-'):
            time_str = time_str[1:]  # Remove the minus sign

            # Parse the number and unit
            match = re.match(r'^(\d+)([smhd])$', time_str)
            if not match:
                raise ValueError(
                    f"Invalid relative time format: {time_str}. "
                    "Use format like '1h', '30m', '7d'"
                )

            amount, unit = match.groups()
            amount = int(amount)

            # Calculate the timedelta
            if unit == 's':
                delta = timedelta(seconds=amount)
            elif unit == 'm':
                delta = timedelta(minutes=amount)
            elif unit == 'h':
                delta = timedelta(hours=amount)
            elif unit == 'd':
                delta = timedelta(days=amount)
            else:
                raise ValueError(f"Unknown time unit: {unit}")

            return datetime.now(timezone.utc) - delta

        # Parse as ISO format
        try:
            return datetime.fromisoformat(time_str.replace('Z', '+00:00'))
        except ValueError as e:
            raise ValueError(
                f"Invalid time format: {time_str}. Use ISO format or relative like '-1h'"
            ) from e

    def _build_time_range_filter(
        self,
        start_time: str = None,
        end_time: str = None
    ) -> Dict[str, Any]:
        """
        Build Elasticsearch time range filter.

        Args:
            start_time: Start time string
            end_time: End time string

        Returns:
            Time range filter dict
        """
        time_filter = {}

        if start_time:
            start_dt = self._parse_relative_time(start_time)
            time_filter['gte'] = start_dt.isoformat()

        if end_time:
            end_dt = self._parse_relative_time(end_time)
            time_filter['lte'] = end_dt.isoformat()

        return {'range': {'@timestamp': time_filter}} if time_filter else {}

    async def _search(
        self,
        index: str,
        query: Dict[str, Any],
        size: int = 100,
        sort: List[Dict[str, Any]] = None,
        fields: List[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Execute a search query.

        Args:
            index: Index name
            query: Elasticsearch query DSL
            size: Number of results
            sort: Sort specification
            fields: Fields to return

        Returns:
            List of matching documents
        """
        body = {
            'query': query,
            'size': size
        }

        if sort:
            body['sort'] = sort

        if fields:
            body['_source'] = fields

        # Execute query using asyncdb
        async with await self._db.connection() as conn:  # pylint: disable=E1101
            results, error = await conn.query(
                json.dumps(body)
            )
            if error:
                raise RuntimeError(
                    f"Elasticsearch query failed: {error}"
                )

        # Extract source documents
        return [hit.get('_source', hit) for hit in results]

    async def _query_logs(
        self,
        index: str,
        start_time: str = None,
        end_time: str = None,
        log_level: str = None,
        message_filter: str = None,
        size: int = 100
    ) -> List[Dict[str, Any]]:
        """
        Query logs with filters.

        Args:
            index: Index name
            start_time: Start time
            end_time: End time
            log_level: Log level filter
            message_filter: Message content filter
            size: Number of results

        Returns:
            List of log entries
        """
        # Build query filters
        must_filters = []

        # Add time range filter
        time_filter = self._build_time_range_filter(start_time, end_time)
        if time_filter:
            must_filters.append(time_filter)

        # Add log level filter
        if log_level:
            must_filters.append({
                'term': {'level.keyword': log_level.upper()}
            })

        # Add message filter
        if message_filter:
            must_filters.append({
                'match': {'message': message_filter}
            })

        # Build complete query
        query = {
            'bool': {
                'must': must_filters
            }
        } if must_filters else {'match_all': {}}

        # Sort by timestamp descending
        sort = [{'@timestamp': {'order': 'desc'}}]

        return await self._search(index, query, size, sort)

    async def _get_metrics(
        self,
        index: str,
        metric_field: str,
        metric_type: str = "avg",
        start_time: str = None,
        end_time: str = None,
        time_interval: str = "1h"
    ) -> Dict[str, Any]:
        """
        Extract metrics from log entries.

        Args:
            index: Index name
            metric_field: Field to extract metrics from
            metric_type: Type of aggregation (avg, sum, min, max, count, percentiles)
            start_time: Start time
            end_time: End time
            time_interval: Time interval for bucketing

        Returns:
            Metric results with aggregations
        """
        # Build query with time range
        time_filter = self._build_time_range_filter(start_time, end_time)
        query = {
            'bool': {
                'must': [time_filter]
            }
        } if time_filter else {'match_all': {}}

        # Build aggregation
        agg_body = {}

        # Time-based histogram
        agg_body['time_buckets'] = {
            'date_histogram': {
                'field': '@timestamp',
                'fixed_interval': time_interval
            },
            'aggs': {}
        }

        # Add metric aggregation
        if metric_type == 'percentiles':
            agg_body['time_buckets']['aggs']['metric'] = {
                'percentiles': {
                    'field': metric_field,
                    'percents': [50, 95, 99]
                }
            }
        else:
            agg_body['time_buckets']['aggs']['metric'] = {
                metric_type: {
                    'field': metric_field
                }
            }

        # Also add overall metric
        if metric_type == 'percentiles':
            agg_body['overall_metric'] = {
                'percentiles': {
                    'field': metric_field,
                    'percents': [50, 95, 99]
                }
            }
        else:
            agg_body['overall_metric'] = {
                metric_type: {
                    'field': metric_field
                }
            }

        # Build complete query
        body = {
            'query': query,
            'size': 0,
            'aggs': agg_body
        }

        # Execute query
        async with await self._db.connection() as conn:  # pylint: disable=E1101
            result = await conn._connection.search(
                index=index,
                body=body
            )

        # Extract aggregation results
        buckets = result.get('aggregations', {}).get('time_buckets', {}).get('buckets', [])
        overall = result.get('aggregations', {}).get('overall_metric', {})

        return {
            'field': metric_field,
            'metric_type': metric_type,
            'overall': overall.get('value') if 'value' in overall else overall.get('values'),
            'time_series': [
                {
                    'timestamp': bucket['key_as_string'] if 'key_as_string' in bucket else bucket['key'],
                    'value': bucket['metric'].get('value') if 'value' in bucket['metric'] else bucket['metric'].get('values')
                }
                for bucket in buckets
            ],
            'total_documents': result.get('hits', {}).get('total', {}).get('value', 0)
        }

    async def _aggregate(
        self,
        index: str,
        aggregation: Dict[str, Any],
        query: Dict[str, Any] = None,
        start_time: str = None,
        end_time: str = None
    ) -> Dict[str, Any]:
        """
        Perform custom aggregation.

        Args:
            index: Index name
            aggregation: Aggregation specification
            query: Optional query filter
            start_time: Start time
            end_time: End time

        Returns:
            Aggregation results
        """
        # Build query with time range
        time_filter = self._build_time_range_filter(start_time, end_time)

        if query:
            if time_filter:
                query = {
                    'bool': {
                        'must': [query, time_filter]
                    }
                }
        else:
            query = {
                'bool': {
                    'must': [time_filter]
                }
            } if time_filter else {'match_all': {}}

        # Build complete query
        body = {
            'query': query,
            'size': 0,
            'aggs': aggregation
        }

        # Execute query
        async with await self._db.connection() as conn:  # pylint: disable=E1101
            result = await conn._connection.search(
                index=index,
                body=body
            )

        return {
            'aggregations': result.get('aggregations', {}),
            'total_documents': result.get('hits', {}).get('total', {}).get('value', 0)
        }

    async def _list_indices(self) -> List[str]:
        """
        List all available indices.

        Returns:
            List of index names
        """
        async with await self._db.connection() as conn:  # pylint: disable=E1101
            indices = await conn._connection.cat.indices(format='json')

        return [idx['index'] for idx in indices]

    async def _get_document(self, index: str, document_id: str) -> Dict[str, Any]:
        """
        Get a specific document by ID.

        Args:
            index: Index name
            document_id: Document ID

        Returns:
            Document content
        """
        async with await self._db.connection() as conn:  # pylint: disable=E1101
            result = await conn.get(document_id)

        return result

    async def _count_documents(
        self,
        index: str,
        query: Dict[str, Any] = None,
        start_time: str = None,
        end_time: str = None
    ) -> int:
        """
        Count documents matching criteria.

        Args:
            index: Index name
            query: Optional query filter
            start_time: Start time
            end_time: End time

        Returns:
            Document count
        """
        # Build query with time range
        time_filter = self._build_time_range_filter(start_time, end_time)

        if query:
            if time_filter:
                query = {
                    'bool': {
                        'must': [query, time_filter]
                    }
                }
        else:
            query = {
                'bool': {
                    'must': [time_filter]
                }
            } if time_filter else {'match_all': {}}

        # Execute count query
        async with await self._db.connection() as conn:  # pylint: disable=E1101
            result = await conn._connection.count(
                index=index,
                body={'query': query}
            )

        return result.get('count', 0)

    async def _analyze_logs(
        self,
        index: str,
        group_by: str,
        start_time: str = None,
        end_time: str = None,
        time_interval: str = "1h",
        size: int = 10
    ) -> Dict[str, Any]:
        """
        Analyze log patterns and extract insights.

        Args:
            index: Index name
            group_by: Field to group by
            start_time: Start time
            end_time: End time
            time_interval: Time interval for bucketing
            size: Number of top groups to return

        Returns:
            Analysis results with patterns and insights
        """
        # Build query with time range
        time_filter = self._build_time_range_filter(start_time, end_time)
        query = {
            'bool': {
                'must': [time_filter]
            }
        } if time_filter else {'match_all': {}}

        # Build aggregation for log analysis
        agg_body = {
            'time_buckets': {
                'date_histogram': {
                    'field': '@timestamp',
                    'fixed_interval': time_interval
                },
                'aggs': {
                    'groups': {
                        'terms': {
                            'field': group_by,
                            'size': size
                        }
                    }
                }
            },
            'top_groups': {
                'terms': {
                    'field': group_by,
                    'size': size,
                    'order': {'_count': 'desc'}
                }
            }
        }

        # Build complete query
        body = {
            'query': query,
            'size': 0,
            'aggs': agg_body
        }

        # Execute query
        async with await self._db.connection() as conn:  # pylint: disable=E1101
            result = await conn._connection.search(
                index=index,
                body=body
            )

        # Extract analysis results
        time_buckets = result.get('aggregations', {}).get('time_buckets', {}).get('buckets', [])
        top_groups = result.get('aggregations', {}).get('top_groups', {}).get('buckets', [])

        return {
            'group_by': group_by,
            'total_documents': result.get('hits', {}).get('total', {}).get('value', 0),
            'top_groups': [
                {
                    'name': bucket['key'],
                    'count': bucket['doc_count']
                }
                for bucket in top_groups
            ],
            'time_series': [
                {
                    'timestamp': bucket['key_as_string'] if 'key_as_string' in bucket else bucket['key'],
                    'total': bucket['doc_count'],
                    'groups': [
                        {
                            'name': group['key'],
                            'count': group['doc_count']
                        }
                        for group in bucket.get('groups', {}).get('buckets', [])
                    ]
                }
                for bucket in time_buckets
            ]
        }

    async def _execute(self, **kwargs) -> ToolResult:
        """Execute Elasticsearch operation"""

        try:
            operation = kwargs['operation']
            index = kwargs.get('index') or self.default_index

            # Route to appropriate method
            if operation == ElasticsearchOperation.SEARCH:
                # Build query from parameters
                query = kwargs.get('query')
                if not query:
                    # Build query from query_string if provided
                    query_string = kwargs.get('query_string')
                    if query_string:
                        query = {
                            'query_string': {
                                'query': query_string
                            }
                        }
                    else:
                        query = {'match_all': {}}

                # Add time range if provided
                start_time = kwargs.get('start_time')
                end_time = kwargs.get('end_time')
                if start_time or end_time:
                    if time_filter := self._build_time_range_filter(start_time, end_time):
                        query = {
                            'bool': {
                                'must': [query, time_filter]
                            }
                        }

                results = await self._search(
                    index=index,
                    query=query,
                    size=kwargs.get('size', 100),
                    sort=kwargs.get('sort'),
                    fields=kwargs.get('fields')
                )

                return ToolResult(
                    success=True,
                    status="completed",
                    result={
                        'documents': results,
                        'count': len(results)
                    },
                    error=None,
                    metadata={
                        'operation': 'search',
                        'index': index
                    },
                    timestamp=datetime.now(timezone.utc).isoformat()
                )

            elif operation == ElasticsearchOperation.QUERY_LOGS:
                results = await self._query_logs(
                    index=index,
                    start_time=kwargs.get('start_time'),
                    end_time=kwargs.get('end_time'),
                    log_level=kwargs.get('log_level'),
                    message_filter=kwargs.get('message_filter'),
                    size=kwargs.get('size', 100)
                )

                return ToolResult(
                    success=True,
                    status="completed",
                    result={
                        'logs': results,
                        'count': len(results)
                    },
                    error=None,
                    metadata={
                        'operation': 'query_logs',
                        'index': index,
                        'log_level': kwargs.get('log_level')
                    },
                    timestamp=datetime.now(timezone.utc).isoformat()
                )

            elif operation == ElasticsearchOperation.GET_METRICS:
                metric_field = kwargs.get('metric_field')
                if not metric_field:
                    return ToolResult(
                        success=False,
                        status="error",
                        result=None,
                        error="metric_field is required for get_metrics operation",
                        metadata={},
                        timestamp=datetime.now(timezone.utc).isoformat()
                    )

                results = await self._get_metrics(
                    index=index,
                    metric_field=metric_field,
                    metric_type=kwargs.get('metric_type', 'avg'),
                    start_time=kwargs.get('start_time'),
                    end_time=kwargs.get('end_time'),
                    time_interval=kwargs.get('time_interval', '1h')
                )

                return ToolResult(
                    success=True,
                    status="completed",
                    result=results,
                    error=None,
                    metadata={
                        'operation': 'get_metrics',
                        'index': index,
                        'metric_field': metric_field
                    },
                    timestamp=datetime.now(timezone.utc).isoformat()
                )

            elif operation == ElasticsearchOperation.AGGREGATE:
                aggregation = kwargs.get('aggregation')
                if not aggregation:
                    return ToolResult(
                        success=False,
                        status="error",
                        result=None,
                        error="aggregation is required for aggregate operation",
                        metadata={},
                        timestamp=datetime.now(timezone.utc).isoformat()
                    )

                results = await self._aggregate(
                    index=index,
                    aggregation=aggregation,
                    query=kwargs.get('query'),
                    start_time=kwargs.get('start_time'),
                    end_time=kwargs.get('end_time')
                )

                return ToolResult(
                    success=True,
                    status="completed",
                    result=results,
                    error=None,
                    metadata={
                        'operation': 'aggregate',
                        'index': index
                    },
                    timestamp=datetime.now(timezone.utc).isoformat()
                )

            elif operation == ElasticsearchOperation.LIST_INDICES:
                indices = await self._list_indices()

                return ToolResult(
                    success=True,
                    status="completed",
                    result={
                        'indices': indices,
                        'count': len(indices)
                    },
                    error=None,
                    metadata={
                        'operation': 'list_indices'
                    },
                    timestamp=datetime.now(timezone.utc).isoformat()
                )

            elif operation == ElasticsearchOperation.GET_DOCUMENT:
                document_id = kwargs.get('document_id')
                if not document_id:
                    return ToolResult(
                        success=False,
                        status="error",
                        result=None,
                        error="document_id is required for get_document operation",
                        metadata={},
                        timestamp=datetime.now(timezone.utc).isoformat()
                    )

                document = await self._get_document(index, document_id)

                return ToolResult(
                    success=True,
                    status="completed",
                    result={'document': document},
                    error=None,
                    metadata={
                        'operation': 'get_document',
                        'index': index,
                        'document_id': document_id
                    },
                    timestamp=datetime.now(timezone.utc).isoformat()
                )

            elif operation == ElasticsearchOperation.COUNT_DOCUMENTS:
                count = await self._count_documents(
                    index=index,
                    query=kwargs.get('query'),
                    start_time=kwargs.get('start_time'),
                    end_time=kwargs.get('end_time')
                )

                return ToolResult(
                    success=True,
                    status="completed",
                    result={'count': count},
                    error=None,
                    metadata={
                        'operation': 'count_documents',
                        'index': index
                    },
                    timestamp=datetime.now(timezone.utc).isoformat()
                )

            elif operation == ElasticsearchOperation.ANALYZE_LOGS:
                group_by = kwargs.get('group_by')
                if not group_by:
                    return ToolResult(
                        success=False,
                        status="error",
                        result=None,
                        error="group_by is required for analyze_logs operation",
                        metadata={},
                        timestamp=datetime.now(timezone.utc).isoformat()
                    )

                results = await self._analyze_logs(
                    index=index,
                    group_by=group_by,
                    start_time=kwargs.get('start_time'),
                    end_time=kwargs.get('end_time'),
                    time_interval=kwargs.get('time_interval', '1h'),
                    size=kwargs.get('size', 10)
                )

                return ToolResult(
                    success=True,
                    status="completed",
                    result=results,
                    error=None,
                    metadata={
                        'operation': 'analyze_logs',
                        'index': index,
                        'group_by': group_by
                    },
                    timestamp=datetime.now(timezone.utc).isoformat()
                )

            else:
                return ToolResult(
                    success=False,
                    status="error",
                    result=None,
                    error=f"Unknown operation: {operation}",
                    metadata={'operation': str(operation)},
                    timestamp=datetime.now(timezone.utc).isoformat()
                )

        except Exception as e:
            return ToolResult(
                success=False,
                status="error",
                result=None,
                error=f"Elasticsearch operation failed: {str(e)}",
                metadata={
                    'operation': kwargs.get('operation', 'unknown'),
                    'exception_type': type(e).__name__
                },
                timestamp=datetime.now(timezone.utc).isoformat()
            )
