---
type: Wiki Entity
title: RDSToolkit
id: class:parrot_tools.aws.rds.RDSToolkit
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Toolkit for managing AWS RDS instances, snapshots, logs, and diagnostics.
relates_to:
- concept: class:parrot.tools.toolkit.AbstractToolkit
  rel: extends
---

# RDSToolkit

Defined in [`parrot_tools.aws.rds`](../summaries/mod:parrot_tools.aws.rds.md).

```python
class RDSToolkit(AbstractToolkit)
```

Toolkit for managing AWS RDS instances, snapshots, logs, and diagnostics.

Each public method is exposed as a separate tool with the `aws_rds_` prefix.

Available Operations:
- aws_rds_list_instances: List RDS instances
- aws_rds_get_instance_details: Get instance details
- aws_rds_start_instance: Start an RDS instance
- aws_rds_stop_instance: Stop an RDS instance
- aws_rds_reboot_instance: Reboot an RDS instance
- aws_rds_list_snapshots: List DB snapshots
- aws_rds_create_snapshot: Create a manual DB snapshot
- aws_rds_list_log_files: List available DB log files
- aws_rds_download_log: Download DB log file content
- aws_rds_download_log_filtered: Download log content filtered by severity (ERROR/WARN/...)
- aws_rds_describe_events: List RDS operational events/alerts
- aws_rds_get_logs: Alias for aws_rds_describe_events
- aws_rds_get_performance_insights: Fetch PI metrics (blocking queries, waits)

## Methods

- `async def aws_rds_list_instances(self, limit: int=100, next_token: Optional[str]=None) -> Dict[str, Any]` — List RDS instances with pagination.
- `async def aws_rds_get_instance_details(self, instance_identifier: str) -> Dict[str, Any]` — Get detailed information about a specific RDS instance.
- `async def aws_rds_start_instance(self, instance_identifier: str) -> Dict[str, Any]` — Start a stopped RDS instance.
- `async def aws_rds_stop_instance(self, instance_identifier: str, snapshot_identifier: Optional[str]=None) -> Dict[str, Any]` — Stop a running RDS instance.
- `async def aws_rds_reboot_instance(self, instance_identifier: str, force_failover: bool=False) -> Dict[str, Any]` — Reboot an RDS instance.
- `async def aws_rds_list_snapshots(self, instance_identifier: Optional[str]=None, snapshot_type: Optional[str]=None, limit: int=100, next_token: Optional[str]=None) -> Dict[str, Any]` — List RDS snapshots with optional filtering.
- `async def aws_rds_create_snapshot(self, instance_identifier: str, snapshot_identifier: str, tags: Optional[Dict[str, str]]=None) -> Dict[str, Any]` — Create a manual DB snapshot.
- `async def aws_rds_list_log_files(self, instance_identifier: str, filename_contains: Optional[str]=None, last_written_after: Optional[int]=None, limit: int=100) -> Dict[str, Any]` — List available DB log files for an RDS instance.
- `async def aws_rds_download_log(self, instance_identifier: str, log_file_name: str, marker: Optional[str]=None, number_of_lines: int=500) -> Dict[str, Any]` — Download a portion of an RDS log file.
- `async def aws_rds_download_log_filtered(self, instance_identifier: str, log_file_name: str, severity_filter: Optional[str]=None, severity_levels: Optional[List[str]]=None, marker: Optional[str]=None, number_of_lines: int=500) -> Dict[str, Any]` — Download a portion of an RDS log file and keep only lines matching a severity pattern.
- `async def aws_rds_describe_events(self, source_identifier: Optional[str]=None, source_type: str='db-instance', duration_minutes: int=1440, event_categories: Optional[List[str]]=None, limit: int=100) -> Dict[str, Any]` — List RDS operational events and alerts.
- `async def aws_rds_get_logs(self, source_identifier: Optional[str]=None, source_type: str='db-instance', duration_minutes: int=1440, event_categories: Optional[List[str]]=None, limit: int=100) -> Dict[str, Any]` — Alias for aws_rds_describe_events — list RDS operational events/alerts.
- `async def aws_rds_get_performance_insights(self, instance_identifier: str, metric_queries: Optional[List[str]]=None, start_time: str='-1h', end_time: str='now', period_seconds: int=60) -> Dict[str, Any]` — Fetch Performance Insights metrics for blocking queries and wait events.
