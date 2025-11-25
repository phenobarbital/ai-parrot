"""
AWS CloudWatch Tool for AI-Parrot
Enables AI agents to query CloudWatch logs and metrics
"""
from typing import Optional, List, Dict, Any, Literal
from datetime import datetime, timedelta
from enum import Enum
import asyncio
from pydantic import Field, field_validator
from botocore.exceptions import ClientError
from ..interfaces.aws import AWSInterface
from ..conf import AWS_DEFAULT_CLOUDWATCH_LOG_GROUP
from .abstract import AbstractTool, AbstractToolArgsSchema, ToolResult


class CloudWatchOperation(str, Enum):
    """Available CloudWatch operations"""
    QUERY_LOGS = "query_logs"
    GET_METRICS = "get_metrics"
    LIST_LOG_GROUPS = "list_log_groups"
    LIST_LOG_STREAMS = "list_log_streams"
    GET_LOG_EVENTS = "get_log_events"
    PUT_METRIC_DATA = "put_metric_data"
    DESCRIBE_ALARMS = "describe_alarms"


class CloudWatchToolArgs(AbstractToolArgsSchema):
    """Arguments schema for CloudWatch operations"""
    
    operation: CloudWatchOperation = Field(
        ...,
        description=(
            "CloudWatch operation to perform:\n"
            "- 'query_logs': Run CloudWatch Logs Insights query\n"
            "- 'get_metrics': Get metric statistics\n"
            "- 'list_log_groups': List available log groups\n"
            "- 'list_log_streams': List log streams in a log group\n"
            "- 'get_log_events': Get recent log events from a stream\n"
            "- 'put_metric_data': Publish custom metric data\n"
            "- 'describe_alarms': List CloudWatch alarms"
        )
    )
    
    # Log query parameters
    log_group_name: Optional[str] = Field(
        None,
        description="CloudWatch log group name (e.g., '/aws/lambda/my-function')"
    )
    
    query_string: Optional[str] = Field(
        None,
        description=(
            "CloudWatch Logs Insights query. Examples:\n"
            "- 'fields @timestamp, @message | sort @timestamp desc | limit 20'\n"
            "- 'filter @message like /ERROR/ | stats count() by bin(5m)'"
        )
    )
    
    log_stream_name: Optional[str] = Field(
        None,
        description="Specific log stream name within the log group"
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
    
    # Metric parameters
    namespace: Optional[str] = Field(
        None,
        description="CloudWatch metric namespace (e.g., 'AWS/Lambda', 'AWS/EC2', custom namespace)"
    )
    
    metric_name: Optional[str] = Field(
        None,
        description="Metric name to query (e.g., 'Duration', 'Invocations', 'CPUUtilization')"
    )
    
    dimensions: Optional[List[Dict[str, str]]] = Field(
        None,
        description=(
            "Metric dimensions as list of {Name: ..., Value: ...} dicts. "
            "Example: [{'Name': 'FunctionName', 'Value': 'my-function'}]"
        )
    )
    
    statistic: Optional[Literal["Average", "Sum", "Minimum", "Maximum", "SampleCount"]] = Field(
        "Average",
        description="Statistic to retrieve for metrics"
    )
    
    period: Optional[int] = Field(
        60,
        description="Period in seconds for metric data points (60, 300, 3600, etc.)"
    )
    
    # General parameters
    limit: Optional[int] = Field(
        50,
        description="Maximum number of results to return"
    )
    
    pattern: Optional[str] = Field(
        None,
        description="Filter pattern for log groups/streams (supports wildcards)"
    )
    
    # Custom metric publishing
    metric_value: Optional[float] = Field(
        None,
        description="Metric value to publish (for put_metric_data operation)"
    )
    
    unit: Optional[str] = Field(
        None,
        description="Metric unit (e.g., 'Seconds', 'Count', 'Bytes')"
    )
    
    @field_validator('start_time', mode='before')
    @classmethod
    def parse_time(cls, v):
        """Parse time string to timestamp"""
        if v is None or v == 'now':
            return v
        return v  # Will be parsed in the tool
    
    @field_validator('end_time', mode='before')
    @classmethod
    def parse_end_time(cls, v):
        """Parse end time string to timestamp"""
        if v is None or v == 'now':
            return v
        return v  # Will be parsed in the tool


class CloudWatchTool(AbstractTool):
    """
    Tool for querying AWS CloudWatch logs and metrics.
    
    Capabilities:
    - Query logs using CloudWatch Logs Insights
    - Retrieve metric statistics and timeseries data
    - List and explore log groups and streams
    - Get recent log events
    - Publish custom metrics
    - Check alarm status
    
    Example Usage:
        # Query logs for errors in last hour
        {
            "operation": "query_logs",
            "log_group_name": "/aws/lambda/my-function",
            "query_string": "fields @timestamp, @message | filter @message like /ERROR/ | limit 50",
            "start_time": "-1h"
        }
        
        # Get Lambda duration metrics
        {
            "operation": "get_metrics",
            "namespace": "AWS/Lambda",
            "metric_name": "Duration",
            "dimensions": [{"Name": "FunctionName", "Value": "my-function"}],
            "statistic": "Average",
            "start_time": "-24h"
        }
    """
    
    name: str = "cloudwatch"
    description: str = (
        "Query AWS CloudWatch logs and metrics. "
        "Supports log queries, metric retrieval, and monitoring operations."
    )
    args_schema: type[AbstractToolArgsSchema] = CloudWatchToolArgs
    
    def __init__(
        self,
        aws_id: str = 'default',
        region_name: Optional[str] = None,
        default_log_group: Optional[str] = None,
        max_query_wait: int = 30,
        **kwargs
    ):
        """
        Initialize CloudWatch tool.
        
        Args:
            aws_id: AWS credentials identifier
            region_name: AWS region
            default_log_group: Default log group for queries
            max_query_wait: Maximum seconds to wait for Insights query completion
            **kwargs: Additional AWS interface parameters
        """
        super().__init__()
        self.aws = AWSInterface(
            aws_id=aws_id,
            region_name=region_name,
            **kwargs
        )
        self.default_log_group = default_log_group or AWS_DEFAULT_CLOUDWATCH_LOG_GROUP
        self.max_query_wait = max_query_wait
    
    def _parse_relative_time(self, time_str: str) -> datetime:
        """
        Parse relative time strings like '-1h', '-30m', '-7d'.
        
        Args:
            time_str: Time string (e.g., '-1h', '-24h', '-7d')
            
        Returns:
            datetime object
        """
        if time_str == 'now' or time_str is None:
            return datetime.utcnow()
        
        # Try parsing as ISO format first
        try:
            return datetime.fromisoformat(time_str.replace('Z', '+00:00'))
        except (ValueError, AttributeError):
            pass
        
        # Parse relative time
        if time_str.startswith('-'):
            time_str = time_str[1:]
            
            # Extract number and unit
            import re
            match = re.match(r'(\d+)([smhd])', time_str)
            if not match:
                raise ValueError(f"Invalid time format: {time_str}")
            
            amount, unit = match.groups()
            amount = int(amount)
            
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
            
            return datetime.utcnow() - delta
        
        raise ValueError(f"Invalid time format: {time_str}")
    
    async def _query_logs_insights(
        self,
        log_group_name: str,
        query_string: str,
        start_time: datetime,
        end_time: datetime,
        limit: int
    ) -> List[Dict[str, Any]]:
        """Execute CloudWatch Logs Insights query"""
        
        async with self.aws.client('logs') as logs:
            # Start query
            response = await logs.start_query(
                logGroupName=log_group_name,
                startTime=int(start_time.timestamp()),
                endTime=int(end_time.timestamp()),
                queryString=query_string,
                limit=limit
            )
            
            query_id = response['queryId']
            
            # Poll for results
            for _ in range(self.max_query_wait):
                result = await logs.get_query_results(queryId=query_id)
                
                status = result['status']
                
                if status == 'Complete':
                    # Parse results
                    parsed_results = []
                    for record in result.get('results', []):
                        parsed_record = {}
                        for field in record:
                            parsed_record[field['field']] = field['value']
                        parsed_results.append(parsed_record)
                    
                    return parsed_results
                
                elif status == 'Failed' or status == 'Cancelled':
                    raise RuntimeError(f"Query failed with status: {status}")
                
                await asyncio.sleep(1)
            
            raise TimeoutError(f"Query did not complete within {self.max_query_wait} seconds")
    
    async def _get_metrics(
        self,
        namespace: str,
        metric_name: str,
        dimensions: List[Dict[str, str]],
        statistic: str,
        start_time: datetime,
        end_time: datetime,
        period: int
    ) -> Dict[str, Any]:
        """Get metric statistics"""
        
        async with self.aws.client('cloudwatch') as cloudwatch:
            # Convert dimensions to proper format
            dims = [
                {'Name': d['Name'], 'Value': d['Value']}
                for d in (dimensions or [])
            ]
            
            response = await cloudwatch.get_metric_statistics(
                Namespace=namespace,
                MetricName=metric_name,
                Dimensions=dims,
                StartTime=start_time,
                EndTime=end_time,
                Period=period,
                Statistics=[statistic]
            )
            
            # Sort datapoints by timestamp
            datapoints = sorted(
                response.get('Datapoints', []),
                key=lambda x: x['Timestamp']
            )
            
            return {
                'label': response.get('Label', metric_name),
                'datapoints': [
                    {
                        'timestamp': dp['Timestamp'].isoformat(),
                        'value': dp.get(statistic),
                        'unit': dp.get('Unit')
                    }
                    for dp in datapoints
                ]
            }
    
    async def _list_log_groups(
        self,
        pattern: Optional[str] = None,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """List CloudWatch log groups"""
        
        async with self.aws.client('logs') as logs:
            params = {'limit': limit}
            if pattern:
                params['logGroupNamePrefix'] = pattern
            
            response = await logs.describe_log_groups(**params)
            
            return [
                {
                    'name': lg['logGroupName'],
                    'creation_time': datetime.fromtimestamp(
                        lg['creationTime'] / 1000
                    ).isoformat(),
                    'stored_bytes': lg.get('storedBytes', 0),
                    'retention_days': lg.get('retentionInDays')
                }
                for lg in response.get('logGroups', [])
            ]
    
    async def _list_log_streams(
        self,
        log_group_name: str,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """List log streams in a log group"""
        
        async with self.aws.client('logs') as logs:
            response = await logs.describe_log_streams(
                logGroupName=log_group_name,
                orderBy='LastEventTime',
                descending=True,
                limit=limit
            )
            
            return [
                {
                    'name': ls['logStreamName'],
                    'creation_time': datetime.fromtimestamp(
                        ls['creationTime'] / 1000
                    ).isoformat(),
                    'last_event_time': datetime.fromtimestamp(
                        ls.get('lastEventTimestamp', ls['creationTime']) / 1000
                    ).isoformat() if ls.get('lastEventTimestamp') else None,
                    'stored_bytes': ls.get('storedBytes', 0)
                }
                for ls in response.get('logStreams', [])
            ]
    
    async def _get_log_events(
        self,
        log_group_name: str,
        log_stream_name: str,
        start_time: Optional[datetime] = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """Get log events from a specific log stream"""
        
        async with self.aws.client('logs') as logs:
            params = {
                'logGroupName': log_group_name,
                'logStreamName': log_stream_name,
                'limit': limit,
                'startFromHead': False  # Get most recent events first
            }
            
            if start_time:
                params['startTime'] = int(start_time.timestamp() * 1000)
            
            response = await logs.get_log_events(**params)
            
            return [
                {
                    'timestamp': datetime.fromtimestamp(
                        event['timestamp'] / 1000
                    ).isoformat(),
                    'message': event['message']
                }
                for event in response.get('events', [])
            ]
    
    async def _put_metric_data(
        self,
        namespace: str,
        metric_name: str,
        metric_value: float,
        dimensions: Optional[List[Dict[str, str]]] = None,
        unit: Optional[str] = None
    ) -> bool:
        """Publish custom metric data"""
        
        async with self.aws.client('cloudwatch') as cloudwatch:
            metric_data = {
                'MetricName': metric_name,
                'Value': metric_value,
                'Timestamp': datetime.utcnow()
            }
            
            if dimensions:
                metric_data['Dimensions'] = [
                    {'Name': d['Name'], 'Value': d['Value']}
                    for d in dimensions
                ]
            
            if unit:
                metric_data['Unit'] = unit
            
            await cloudwatch.put_metric_data(
                Namespace=namespace,
                MetricData=[metric_data]
            )
            
            return True
    
    async def _describe_alarms(
        self,
        pattern: Optional[str] = None,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """List CloudWatch alarms"""
        
        async with self.aws.client('cloudwatch') as cloudwatch:
            params = {'MaxRecords': limit}
            if pattern:
                params['AlarmNamePrefix'] = pattern
            
            response = await cloudwatch.describe_alarms(**params)
            
            return [
                {
                    'name': alarm['AlarmName'],
                    'description': alarm.get('AlarmDescription'),
                    'state': alarm['StateValue'],
                    'state_reason': alarm.get('StateReason'),
                    'metric_name': alarm.get('MetricName'),
                    'namespace': alarm.get('Namespace'),
                    'comparison': alarm.get('ComparisonOperator'),
                    'threshold': alarm.get('Threshold'),
                    'evaluation_periods': alarm.get('EvaluationPeriods')
                }
                for alarm in response.get('MetricAlarms', [])
            ]
    
    async def _execute(self, **kwargs) -> ToolResult:
        """Execute CloudWatch operation"""
        
        try:
            operation = kwargs['operation']
            
            # Parse time parameters
            start_time = self._parse_relative_time(
                kwargs.get('start_time', '-1h')
            )
            end_time = self._parse_relative_time(
                kwargs.get('end_time', 'now')
            )
            
            # Route to appropriate method
            if operation == CloudWatchOperation.QUERY_LOGS:
                log_group = kwargs.get('log_group_name') or self.default_log_group
                if not log_group:
                    return ToolResult(
                        success=False,
                        status="error",
                        result=None,
                        error="log_group_name is required for query_logs operation",
                        metadata={},
                        timestamp=datetime.utcnow().isoformat()
                    )
                
                query_string = kwargs.get('query_string')
                if not query_string:
                    # Default query if none provided
                    query_string = (
                        "fields @timestamp, @message "
                        "| sort @timestamp desc "
                        f"| limit {kwargs.get('limit', 100)}"
                    )
                
                results = await self._query_logs_insights(
                    log_group_name=log_group,
                    query_string=query_string,
                    start_time=start_time,
                    end_time=end_time,
                    limit=kwargs.get('limit', 100)
                )
                
                return ToolResult(
                    success=True,
                    status="completed",
                    result={
                        'log_group': log_group,
                        'query': query_string,
                        'time_range': {
                            'start': start_time.isoformat(),
                            'end': end_time.isoformat()
                        },
                        'results': results,
                        'count': len(results)
                    },
                    error=None,
                    metadata={
                        'operation': 'query_logs',
                        'log_group': log_group
                    },
                    timestamp=datetime.utcnow().isoformat()
                )
            
            elif operation == CloudWatchOperation.GET_METRICS:
                if not kwargs.get('namespace') or not kwargs.get('metric_name'):
                    return ToolResult(
                        success=False,
                        status="error",
                        result=None,
                        error="namespace and metric_name are required for get_metrics",
                        metadata={},
                        timestamp=datetime.utcnow().isoformat()
                    )
                
                metrics = await self._get_metrics(
                    namespace=kwargs['namespace'],
                    metric_name=kwargs['metric_name'],
                    dimensions=kwargs.get('dimensions', []),
                    statistic=kwargs.get('statistic', 'Average'),
                    start_time=start_time,
                    end_time=end_time,
                    period=kwargs.get('period', 60)
                )
                
                return ToolResult(
                    success=True,
                    status="completed",
                    result=metrics,
                    error=None,
                    metadata={
                        'operation': 'get_metrics',
                        'namespace': kwargs['namespace'],
                        'metric_name': kwargs['metric_name']
                    },
                    timestamp=datetime.utcnow().isoformat()
                )
            
            elif operation == CloudWatchOperation.LIST_LOG_GROUPS:
                log_groups = await self._list_log_groups(
                    pattern=kwargs.get('pattern'),
                    limit=kwargs.get('limit', 50)
                )
                
                return ToolResult(
                    success=True,
                    status="completed",
                    result={
                        'log_groups': log_groups,
                        'count': len(log_groups)
                    },
                    error=None,
                    metadata={
                        'operation': 'list_log_groups',
                        'pattern': kwargs.get('pattern')
                    },
                    timestamp=datetime.utcnow().isoformat()
                )
            
            elif operation == CloudWatchOperation.LIST_LOG_STREAMS:
                if not kwargs.get('log_group_name'):
                    return ToolResult(
                        success=False,
                        status="error",
                        result=None,
                        error="log_group_name is required for list_log_streams",
                        metadata={},
                        timestamp=datetime.utcnow().isoformat()
                    )
                
                log_streams = await self._list_log_streams(
                    log_group_name=kwargs['log_group_name'],
                    limit=kwargs.get('limit', 50)
                )
                
                return ToolResult(
                    success=True,
                    status="completed",
                    result={
                        'log_group': kwargs['log_group_name'],
                        'log_streams': log_streams,
                        'count': len(log_streams)
                    },
                    error=None,
                    metadata={
                        'operation': 'list_log_streams',
                        'log_group': kwargs['log_group_name']
                    },
                    timestamp=datetime.utcnow().isoformat()
                )
            
            elif operation == CloudWatchOperation.GET_LOG_EVENTS:
                if not kwargs.get('log_group_name') or not kwargs.get('log_stream_name'):
                    return ToolResult(
                        success=False,
                        status="error",
                        result=None,
                        error="log_group_name and log_stream_name are required",
                        metadata={},
                        timestamp=datetime.utcnow().isoformat()
                    )
                
                events = await self._get_log_events(
                    log_group_name=kwargs['log_group_name'],
                    log_stream_name=kwargs['log_stream_name'],
                    start_time=start_time if kwargs.get('start_time') else None,
                    limit=kwargs.get('limit', 100)
                )
                
                return ToolResult(
                    success=True,
                    status="completed",
                    result={
                        'log_group': kwargs['log_group_name'],
                        'log_stream': kwargs['log_stream_name'],
                        'events': events,
                        'count': len(events)
                    },
                    error=None,
                    metadata={
                        'operation': 'get_log_events',
                        'log_group': kwargs['log_group_name'],
                        'log_stream': kwargs['log_stream_name']
                    },
                    timestamp=datetime.utcnow().isoformat()
                )
            
            elif operation == CloudWatchOperation.PUT_METRIC_DATA:
                if not all([
                    kwargs.get('namespace'),
                    kwargs.get('metric_name'),
                    kwargs.get('metric_value') is not None
                ]):
                    return ToolResult(
                        success=False,
                        status="error",
                        result=None,
                        error="namespace, metric_name, and metric_value are required",
                        metadata={},
                        timestamp=datetime.utcnow().isoformat()
                    )
                
                success = await self._put_metric_data(
                    namespace=kwargs['namespace'],
                    metric_name=kwargs['metric_name'],
                    metric_value=kwargs['metric_value'],
                    dimensions=kwargs.get('dimensions'),
                    unit=kwargs.get('unit')
                )
                
                return ToolResult(
                    success=True,
                    status="completed",
                    result={
                        'message': 'Metric data published successfully',
                        'namespace': kwargs['namespace'],
                        'metric_name': kwargs['metric_name'],
                        'value': kwargs['metric_value']
                    },
                    error=None,
                    metadata={
                        'operation': 'put_metric_data',
                        'namespace': kwargs['namespace'],
                        'metric_name': kwargs['metric_name']
                    },
                    timestamp=datetime.utcnow().isoformat()
                )
            
            elif operation == CloudWatchOperation.DESCRIBE_ALARMS:
                alarms = await self._describe_alarms(
                    pattern=kwargs.get('pattern'),
                    limit=kwargs.get('limit', 50)
                )
                
                return ToolResult(
                    success=True,
                    status="completed",
                    result={
                        'alarms': alarms,
                        'count': len(alarms)
                    },
                    error=None,
                    metadata={
                        'operation': 'describe_alarms',
                        'pattern': kwargs.get('pattern')
                    },
                    timestamp=datetime.utcnow().isoformat()
                )
            
            else:
                return ToolResult(
                    success=False,
                    status="error",
                    result=None,
                    error=f"Unknown operation: {operation}",
                    metadata={'operation': str(operation)},
                    timestamp=datetime.utcnow().isoformat()
                )
        
        except ClientError as e:
            error_code = e.response['Error']['Code']
            error_msg = e.response['Error']['Message']
            return ToolResult(
                success=False,
                status="aws_error",
                result=None,
                error=f"AWS Error ({error_code}): {error_msg}",
                metadata={
                    'error_code': error_code,
                    'operation': kwargs.get('operation', 'unknown')
                },
                timestamp=datetime.utcnow().isoformat()
            )
        
        except Exception as e:
            return ToolResult(
                success=False,
                status="error",
                result=None,
                error=f"CloudWatch operation failed: {str(e)}",
                metadata={
                    'operation': kwargs.get('operation', 'unknown'),
                    'exception_type': type(e).__name__
                },
                timestamp=datetime.utcnow().isoformat()
            )