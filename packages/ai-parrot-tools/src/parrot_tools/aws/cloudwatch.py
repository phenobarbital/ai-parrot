"""AWS CloudWatch Toolkit for AI-Parrot.

Provides querying of CloudWatch logs, metrics, alarms, and custom metric publishing.
"""
from __future__ import annotations
import contextlib
import re
import asyncio
from typing import Any, Dict, List, Literal, Optional
from datetime import datetime, timedelta, timezone
from pydantic import BaseModel, Field
from botocore.exceptions import ClientError
from ...interfaces.aws import AWSInterface
from ...conf import AWS_DEFAULT_CLOUDWATCH_LOG_GROUP
from ..decorators import tool_schema
from ..toolkit import AbstractToolkit


# ------------------------------------------------------------------
# Input Schemas
# ------------------------------------------------------------------


class QueryLogsInput(BaseModel):
    """Input for CloudWatch Logs Insights query."""

    log_group_name: Optional[str] = Field(
        None,
        description="CloudWatch log group name (e.g. '/aws/lambda/my-function')",
    )
    query_string: Optional[str] = Field(
        None,
        description=(
            "CloudWatch Logs Insights query. Example: "
            "'fields @timestamp, @message | filter @message like /ERROR/ | limit 50'"
        ),
    )
    start_time: str = Field(
        "-1h",
        description="Start time (ISO format or relative like '-1h', '-30m', '-7d')",
    )
    end_time: str = Field(
        "now", description="End time (ISO format or 'now')"
    )
    limit: int = Field(100, description="Maximum number of results")


class GetMetricsInput(BaseModel):
    """Input for retrieving CloudWatch metric statistics."""

    namespace: str = Field(
        ...,
        description="CloudWatch metric namespace (e.g. 'AWS/Lambda', 'AWS/EC2')",
    )
    metric_name: str = Field(
        ...,
        description="Metric name (e.g. 'Duration', 'Invocations', 'CPUUtilization')",
    )
    dimensions: Optional[List[Dict[str, str]]] = Field(
        None,
        description=(
            "Metric dimensions as list of {Name, Value} dicts. "
            "Example: [{'Name': 'FunctionName', 'Value': 'my-func'}]"
        ),
    )
    statistic: Literal[
        "Average", "Sum", "Minimum", "Maximum", "SampleCount"
    ] = Field("Average", description="Statistic to retrieve")
    period: int = Field(
        60, description="Period in seconds for data points (60, 300, 3600, etc.)"
    )
    start_time: str = Field(
        "-1h",
        description="Start time (ISO format or relative like '-1h', '-24h')",
    )
    end_time: str = Field(
        "now", description="End time (ISO format or 'now')"
    )


class ListLogGroupsInput(BaseModel):
    """Input for listing CloudWatch log groups."""

    pattern: Optional[str] = Field(
        None, description="Log group name prefix filter"
    )
    limit: int = Field(50, description="Maximum number of log groups")


class ListLogStreamsInput(BaseModel):
    """Input for listing log streams in a log group."""

    log_group_name: str = Field(
        ..., description="CloudWatch log group name"
    )
    limit: int = Field(50, description="Maximum number of log streams")


class GetLogEventsInput(BaseModel):
    """Input for getting log events from a specific stream."""

    log_group_name: str = Field(
        ..., description="CloudWatch log group name"
    )
    log_stream_name: str = Field(
        ..., description="Log stream name within the log group"
    )
    start_time: Optional[str] = Field(
        None, description="Start time (ISO format or relative)"
    )
    limit: int = Field(100, description="Maximum number of log events")


class PutMetricDataInput(BaseModel):
    """Input for publishing custom metric data."""

    namespace: str = Field(
        ..., description="CloudWatch metric namespace"
    )
    metric_name: str = Field(
        ..., description="Metric name to publish"
    )
    metric_value: float = Field(
        ..., description="Metric value to publish"
    )
    dimensions: Optional[List[Dict[str, str]]] = Field(
        None,
        description="Metric dimensions as list of {Name, Value} dicts",
    )
    unit: Optional[str] = Field(
        None,
        description="Metric unit (e.g. 'Seconds', 'Count', 'Bytes')",
    )


class DescribeAlarmsInput(BaseModel):
    """Input for listing CloudWatch alarms."""

    pattern: Optional[str] = Field(
        None, description="Alarm name prefix filter"
    )
    limit: int = Field(50, description="Maximum number of alarms")


class LogSummaryInput(BaseModel):
    """Input for getting summarized log events."""

    log_group_name: str = Field(
        ..., description="CloudWatch log group name"
    )
    log_stream_name: Optional[str] = Field(
        None, description="Specific log stream (defaults to most recent)"
    )
    start_time: Optional[str] = Field(
        None, description="Start time (ISO format or relative)"
    )
    limit: int = Field(100, description="Maximum number of log events")
    max_message_length: int = Field(
        500, description="Maximum length for log messages"
    )


# ------------------------------------------------------------------
# Toolkit
# ------------------------------------------------------------------


class CloudWatchToolkit(AbstractToolkit):
    """Toolkit for querying AWS CloudWatch logs and metrics.

    Each public method is exposed as a separate tool with the `aws_cloudwatch_` prefix.

    Available Operations:
    - aws_cloudwatch_query_logs: Run CloudWatch Logs Insights queries
    - aws_cloudwatch_get_metrics: Get metric statistics
    - aws_cloudwatch_list_log_groups: List available log groups
    - aws_cloudwatch_list_log_streams: List log streams in a group
    - aws_cloudwatch_get_log_events: Get events from a stream
    - aws_cloudwatch_put_metric_data: Publish custom metrics
    - aws_cloudwatch_describe_alarms: List CloudWatch alarms
    - aws_cloudwatch_log_summary: Get summarized log events
    """

    def __init__(
        self,
        aws_id: str = "cloudwatch",
        region_name: Optional[str] = None,
        default_log_group: Optional[str] = None,
        max_query_wait: int = 30,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.aws = AWSInterface(
            aws_id=aws_id,
            region_name=region_name,
            **kwargs,
        )
        self.default_log_group = (
            default_log_group or AWS_DEFAULT_CLOUDWATCH_LOG_GROUP
        )
        self.max_query_wait = max_query_wait

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _parse_relative_time(self, time_str: str) -> datetime:
        """Parse relative time strings like '-1h', '-30m', '-7d'."""
        if time_str == "now" or time_str is None:
            return datetime.now(timezone.utc)

        with contextlib.suppress(ValueError, AttributeError):
            return datetime.fromisoformat(
                time_str.replace("Z", "+00:00")
            )

        if time_str.startswith("-"):
            raw = time_str[1:]
            match = re.match(r"(\d+)([smhd])", raw)
            if not match:
                raise ValueError(f"Invalid time format: {time_str}")

            amount, unit = match.groups()
            amount = int(amount)
            deltas = {
                "s": timedelta(seconds=amount),
                "m": timedelta(minutes=amount),
                "h": timedelta(hours=amount),
                "d": timedelta(days=amount),
            }
            delta = deltas.get(unit)
            if delta is None:
                raise ValueError(f"Unknown time unit: {unit}")
            return datetime.now(timezone.utc) - delta

        raise ValueError(f"Invalid time format: {time_str}")

    def _parse_log_message(
        self, message: str, timestamp: str
    ) -> Dict[str, Any]:
        """Parse log message to extract facility, time, and message."""
        facility = "INFO"
        parsed_message = message

        # Rails/Ruby logger format
        rails_pattern = (
            r'^([A-Z]),\s*\[([^\]]+)\]\s*(\w+)\s*--\s*:\s*(.+)$'
        )
        match = re.match(rails_pattern, message)
        if match:
            _, _, level_name, msg = match.groups()
            return {
                "facility": level_name,
                "timestamp": timestamp,
                "message": msg.strip(),
            }

        # Standard log format with level prefix
        level_patterns = [
            r'^\[?(DEBUG|INFO|WARN|WARNING|ERROR|FATAL|CRITICAL)\]?\s*:?\s*(.+)$',
            r'^\d{4}-\d{2}-\d{2}[T\s]\d{2}:\d{2}:\d{2}[^\s]*\s+'
            r'\[?(DEBUG|INFO|WARN|WARNING|ERROR|FATAL|CRITICAL)\]?\s*:?\s*(.+)$',
        ]
        for pattern in level_patterns:
            match = re.match(pattern, message, re.IGNORECASE)
            if match:
                groups = match.groups()
                facility = groups[0].upper()
                parsed_message = groups[1].strip()
                break

        parsed_message = parsed_message.replace("\\n", " ").replace(
            "\\t", " "
        )
        parsed_message = re.sub(r"\s+", " ", parsed_message).strip()

        return {
            "facility": facility,
            "timestamp": timestamp,
            "message": parsed_message,
        }

    def _truncate_message(self, message: str, max_length: int) -> str:
        """Truncate message to max_length, adding ellipsis if truncated."""
        if len(message) <= max_length:
            return message
        return message[: max_length - 3] + "..."

    # ------------------------------------------------------------------
    # Query Logs
    # ------------------------------------------------------------------

    @tool_schema(QueryLogsInput)
    async def aws_cloudwatch_query_logs(
        self,
        log_group_name: Optional[str] = None,
        query_string: Optional[str] = None,
        start_time: str = "-1h",
        end_time: str = "now",
        limit: int = 100,
    ) -> Dict[str, Any]:
        """Run a CloudWatch Logs Insights query."""
        try:
            log_group = log_group_name or self.default_log_group
            if not log_group:
                raise ValueError(
                    "log_group_name is required for query_logs"
                )

            parsed_start = self._parse_relative_time(start_time)
            parsed_end = self._parse_relative_time(end_time)

            if not query_string:
                query_string = (
                    "fields @timestamp, @message "
                    "| sort @timestamp desc "
                    f"| limit {limit}"
                )

            async with self.aws.client("logs") as logs:
                response = await logs.start_query(
                    logGroupName=log_group,
                    startTime=int(parsed_start.timestamp()),
                    endTime=int(parsed_end.timestamp()),
                    queryString=query_string,
                    limit=limit,
                )
                query_id = response["queryId"]

                for _ in range(self.max_query_wait):
                    result = await logs.get_query_results(
                        queryId=query_id
                    )
                    status = result["status"]

                    if status == "Complete":
                        parsed_results = [
                            {
                                field["field"]: field["value"]
                                for field in record
                            }
                            for record in result.get("results", [])
                        ]
                        return {
                            "log_group": log_group,
                            "query": query_string,
                            "time_range": {
                                "start": parsed_start.isoformat(),
                                "end": parsed_end.isoformat(),
                            },
                            "results": parsed_results,
                            "count": len(parsed_results),
                        }
                    elif status in ("Failed", "Cancelled"):
                        raise RuntimeError(
                            f"Query failed with status: {status}"
                        )

                    await asyncio.sleep(1)

                raise TimeoutError(
                    f"Query did not complete within {self.max_query_wait}s"
                )
        except ClientError as e:
            error_code = e.response["Error"].get("Code", "Unknown")
            raise RuntimeError(
                f"AWS CloudWatch error ({error_code}): {e}"
            ) from e

    # ------------------------------------------------------------------
    # Get Metrics
    # ------------------------------------------------------------------

    @tool_schema(GetMetricsInput)
    async def aws_cloudwatch_get_metrics(
        self,
        namespace: str,
        metric_name: str,
        dimensions: Optional[List[Dict[str, str]]] = None,
        statistic: str = "Average",
        period: int = 60,
        start_time: str = "-1h",
        end_time: str = "now",
    ) -> Dict[str, Any]:
        """Get CloudWatch metric statistics."""
        try:
            parsed_start = self._parse_relative_time(start_time)
            parsed_end = self._parse_relative_time(end_time)
            dims = [
                {"Name": d["Name"], "Value": d["Value"]}
                for d in (dimensions or [])
            ]

            async with self.aws.client("cloudwatch") as cloudwatch:
                response = await cloudwatch.get_metric_statistics(
                    Namespace=namespace,
                    MetricName=metric_name,
                    Dimensions=dims,
                    StartTime=parsed_start,
                    EndTime=parsed_end,
                    Period=period,
                    Statistics=[statistic],
                )

                datapoints = sorted(
                    response.get("Datapoints", []),
                    key=lambda x: x["Timestamp"],
                )

                return {
                    "label": response.get("Label", metric_name),
                    "datapoints": [
                        {
                            "timestamp": dp["Timestamp"].isoformat(),
                            "value": dp.get(statistic),
                            "unit": dp.get("Unit"),
                        }
                        for dp in datapoints
                    ],
                    "count": len(datapoints),
                }
        except ClientError as e:
            error_code = e.response["Error"].get("Code", "Unknown")
            raise RuntimeError(
                f"AWS CloudWatch error ({error_code}): {e}"
            ) from e

    # ------------------------------------------------------------------
    # List Log Groups
    # ------------------------------------------------------------------

    @tool_schema(ListLogGroupsInput)
    async def aws_cloudwatch_list_log_groups(
        self,
        pattern: Optional[str] = None,
        limit: int = 50,
    ) -> Dict[str, Any]:
        """List available CloudWatch log groups."""
        try:
            async with self.aws.client("logs") as logs:
                params: Dict[str, Any] = {}
                if pattern:
                    params["logGroupNamePrefix"] = pattern

                log_groups: List[Dict[str, Any]] = []
                paginator = logs.get_paginator("describe_log_groups")

                async for page in paginator.paginate(**params):
                    for lg in page.get("logGroups", []):
                        log_groups.append(
                            {
                                "name": lg["logGroupName"],
                                "creation_time": datetime.fromtimestamp(
                                    lg["creationTime"] / 1000
                                ).isoformat(),
                                "stored_bytes": lg.get(
                                    "storedBytes", 0
                                ),
                                "retention_days": lg.get(
                                    "retentionInDays"
                                ),
                            }
                        )
                    if len(log_groups) >= limit:
                        break

                return {
                    "log_groups": log_groups[:limit],
                    "count": len(log_groups[:limit]),
                }
        except ClientError as e:
            error_code = e.response["Error"].get("Code", "Unknown")
            raise RuntimeError(
                f"AWS CloudWatch error ({error_code}): {e}"
            ) from e

    # ------------------------------------------------------------------
    # List Log Streams
    # ------------------------------------------------------------------

    @tool_schema(ListLogStreamsInput)
    async def aws_cloudwatch_list_log_streams(
        self,
        log_group_name: str,
        limit: int = 50,
    ) -> Dict[str, Any]:
        """List log streams in a CloudWatch log group."""
        try:
            async with self.aws.client("logs") as logs:
                response = await logs.describe_log_streams(
                    logGroupName=log_group_name,
                    orderBy="LastEventTime",
                    descending=True,
                    limit=limit,
                )

                streams = [
                    {
                        "name": ls["logStreamName"],
                        "creation_time": datetime.fromtimestamp(
                            ls["creationTime"] / 1000
                        ).isoformat(),
                        "last_event_time": (
                            datetime.fromtimestamp(
                                ls.get(
                                    "lastEventTimestamp",
                                    ls["creationTime"],
                                )
                                / 1000
                            ).isoformat()
                            if ls.get("lastEventTimestamp")
                            else None
                        ),
                        "stored_bytes": ls.get("storedBytes", 0),
                    }
                    for ls in response.get("logStreams", [])
                ]

                return {
                    "log_group": log_group_name,
                    "log_streams": streams,
                    "count": len(streams),
                }
        except ClientError as e:
            error_code = e.response["Error"].get("Code", "Unknown")
            raise RuntimeError(
                f"AWS CloudWatch error ({error_code}): {e}"
            ) from e

    # ------------------------------------------------------------------
    # Get Log Events
    # ------------------------------------------------------------------

    @tool_schema(GetLogEventsInput)
    async def aws_cloudwatch_get_log_events(
        self,
        log_group_name: str,
        log_stream_name: str,
        start_time: Optional[str] = None,
        limit: int = 100,
    ) -> Dict[str, Any]:
        """Get log events from a specific CloudWatch log stream."""
        try:
            async with self.aws.client("logs") as logs:
                params: Dict[str, Any] = {
                    "logGroupName": log_group_name,
                    "logStreamName": log_stream_name,
                    "limit": limit,
                    "startFromHead": False,
                }
                if start_time:
                    parsed = self._parse_relative_time(start_time)
                    params["startTime"] = int(parsed.timestamp() * 1000)

                response = await logs.get_log_events(**params)

                events = [
                    {
                        "timestamp": datetime.fromtimestamp(
                            event["timestamp"] / 1000
                        ).isoformat(),
                        "message": event["message"],
                    }
                    for event in response.get("events", [])
                ]

                return {
                    "log_group": log_group_name,
                    "log_stream": log_stream_name,
                    "events": events,
                    "count": len(events),
                }
        except ClientError as e:
            error_code = e.response["Error"].get("Code", "Unknown")
            raise RuntimeError(
                f"AWS CloudWatch error ({error_code}): {e}"
            ) from e

    # ------------------------------------------------------------------
    # Put Metric Data
    # ------------------------------------------------------------------

    @tool_schema(PutMetricDataInput)
    async def aws_cloudwatch_put_metric_data(
        self,
        namespace: str,
        metric_name: str,
        metric_value: float,
        dimensions: Optional[List[Dict[str, str]]] = None,
        unit: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Publish custom metric data to CloudWatch."""
        try:
            async with self.aws.client("cloudwatch") as cloudwatch:
                metric_data: Dict[str, Any] = {
                    "MetricName": metric_name,
                    "Value": metric_value,
                    "Timestamp": datetime.now(timezone.utc),
                }
                if dimensions:
                    metric_data["Dimensions"] = [
                        {"Name": d["Name"], "Value": d["Value"]}
                        for d in dimensions
                    ]
                if unit:
                    metric_data["Unit"] = unit

                await cloudwatch.put_metric_data(
                    Namespace=namespace,
                    MetricData=[metric_data],
                )

                return {
                    "message": "Metric data published successfully",
                    "namespace": namespace,
                    "metric_name": metric_name,
                    "value": metric_value,
                }
        except ClientError as e:
            error_code = e.response["Error"].get("Code", "Unknown")
            raise RuntimeError(
                f"AWS CloudWatch error ({error_code}): {e}"
            ) from e

    # ------------------------------------------------------------------
    # Describe Alarms
    # ------------------------------------------------------------------

    @tool_schema(DescribeAlarmsInput)
    async def aws_cloudwatch_describe_alarms(
        self,
        pattern: Optional[str] = None,
        limit: int = 50,
    ) -> Dict[str, Any]:
        """List CloudWatch alarms."""
        try:
            async with self.aws.client("cloudwatch") as cloudwatch:
                params: Dict[str, Any] = {"MaxRecords": limit}
                if pattern:
                    params["AlarmNamePrefix"] = pattern

                response = await cloudwatch.describe_alarms(**params)

                alarms = [
                    {
                        "name": alarm["AlarmName"],
                        "description": alarm.get("AlarmDescription"),
                        "state": alarm["StateValue"],
                        "state_reason": alarm.get("StateReason"),
                        "metric_name": alarm.get("MetricName"),
                        "namespace": alarm.get("Namespace"),
                        "comparison": alarm.get("ComparisonOperator"),
                        "threshold": alarm.get("Threshold"),
                        "evaluation_periods": alarm.get(
                            "EvaluationPeriods"
                        ),
                    }
                    for alarm in response.get("MetricAlarms", [])
                ]

                return {"alarms": alarms, "count": len(alarms)}
        except ClientError as e:
            error_code = e.response["Error"].get("Code", "Unknown")
            raise RuntimeError(
                f"AWS CloudWatch error ({error_code}): {e}"
            ) from e

    # ------------------------------------------------------------------
    # Log Summary
    # ------------------------------------------------------------------

    @tool_schema(LogSummaryInput)
    async def aws_cloudwatch_log_summary(
        self,
        log_group_name: str,
        log_stream_name: Optional[str] = None,
        start_time: Optional[str] = None,
        limit: int = 100,
        max_message_length: int = 500,
    ) -> Dict[str, Any]:
        """Get summarized log events with parsed facility and truncated messages."""
        try:
            parsed_start = (
                self._parse_relative_time(start_time)
                if start_time
                else None
            )

            # Get events from specified stream or most recent stream
            if log_stream_name:
                events_result = await self.aws_cloudwatch_get_log_events(
                    log_group_name=log_group_name,
                    log_stream_name=log_stream_name,
                    start_time=start_time,
                    limit=limit,
                )
                events = events_result["events"]
            else:
                streams_result = (
                    await self.aws_cloudwatch_list_log_streams(
                        log_group_name=log_group_name, limit=1
                    )
                )
                streams = streams_result["log_streams"]
                if not streams:
                    return {
                        "log_group": log_group_name,
                        "summary": [],
                        "count": 0,
                    }
                events_result = await self.aws_cloudwatch_get_log_events(
                    log_group_name=log_group_name,
                    log_stream_name=streams[0]["name"],
                    start_time=start_time,
                    limit=limit,
                )
                events = events_result["events"]

            # Parse and summarize
            summary = [
                {
                    "timestamp": parsed["timestamp"],
                    "facility": parsed["facility"],
                    "message": self._truncate_message(
                        parsed["message"], max_message_length
                    ),
                }
                for event in events
                for parsed in [
                    self._parse_log_message(
                        event["message"], event["timestamp"]
                    )
                ]
            ]

            return {
                "log_group": log_group_name,
                "log_stream": log_stream_name,
                "summary": summary,
                "count": len(summary),
                "max_message_length": max_message_length,
            }
        except ClientError as e:
            error_code = e.response["Error"].get("Code", "Unknown")
            raise RuntimeError(
                f"AWS CloudWatch error ({error_code}): {e}"
            ) from e
