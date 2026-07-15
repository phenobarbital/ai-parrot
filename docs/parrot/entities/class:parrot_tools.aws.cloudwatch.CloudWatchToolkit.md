---
type: Wiki Entity
title: CloudWatchToolkit
id: class:parrot_tools.aws.cloudwatch.CloudWatchToolkit
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Toolkit for querying AWS CloudWatch logs and metrics.
relates_to:
- concept: class:parrot.tools.toolkit.AbstractToolkit
  rel: extends
---

# CloudWatchToolkit

Defined in [`parrot_tools.aws.cloudwatch`](../summaries/mod:parrot_tools.aws.cloudwatch.md).

```python
class CloudWatchToolkit(AbstractToolkit)
```

Toolkit for querying AWS CloudWatch logs and metrics.

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

## Methods

- `async def aws_cloudwatch_query_logs(self, log_group_name: Optional[str]=None, query_string: Optional[str]=None, start_time: str='-1h', end_time: str='now', limit: int=100) -> Dict[str, Any]` — Run a CloudWatch Logs Insights query.
- `async def aws_cloudwatch_get_metrics(self, namespace: str, metric_name: str, dimensions: Optional[List[Dict[str, str]]]=None, statistic: str='Average', period: int=60, start_time: str='-1h', end_time: str='now') -> Dict[str, Any]` — Get CloudWatch metric statistics.
- `async def aws_cloudwatch_list_log_groups(self, pattern: Optional[str]=None, limit: int=50) -> Dict[str, Any]` — List available CloudWatch log groups.
- `async def aws_cloudwatch_list_log_streams(self, log_group_name: str, limit: int=50) -> Dict[str, Any]` — List log streams in a CloudWatch log group.
- `async def aws_cloudwatch_get_log_events(self, log_group_name: str, log_stream_name: Optional[str]=None, start_time: Optional[str]=None, limit: int=100) -> Dict[str, Any]` — Get log events from a CloudWatch log stream.
- `async def aws_cloudwatch_put_metric_data(self, namespace: str, metric_name: str, metric_value: float, dimensions: Optional[List[Dict[str, str]]]=None, unit: Optional[str]=None) -> Dict[str, Any]` — Publish custom metric data to CloudWatch.
- `async def aws_cloudwatch_describe_alarms(self, pattern: Optional[str]=None, limit: int=50) -> Dict[str, Any]` — List CloudWatch alarms.
- `async def aws_cloudwatch_log_summary(self, log_group_name: str, log_stream_name: Optional[str]=None, start_time: Optional[str]=None, limit: int=100, max_message_length: int=500) -> Dict[str, Any]` — Get summarized log events with parsed facility and truncated messages.
