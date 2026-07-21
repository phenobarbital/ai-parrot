---
type: Wiki Entity
title: DocumentDBToolkit
id: class:parrot_tools.aws.documentdb.DocumentDBToolkit
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Toolkit for managing AWS DocumentDB clusters, instances, and snapshots.
relates_to:
- concept: class:parrot.tools.toolkit.AbstractToolkit
  rel: extends
---

# DocumentDBToolkit

Defined in [`parrot_tools.aws.documentdb`](../summaries/mod:parrot_tools.aws.documentdb.md).

```python
class DocumentDBToolkit(AbstractToolkit)
```

Toolkit for managing AWS DocumentDB clusters, instances, and snapshots.

Each public method is exposed as a separate tool with the `aws_docdb_` prefix.

Available Operations:
- aws_docdb_list_clusters: List DocumentDB clusters
- aws_docdb_get_cluster_details: Get cluster details
- aws_docdb_list_instances: List instances in a cluster
- aws_docdb_get_instance_details: Get instance details
- aws_docdb_start_cluster: Start a stopped cluster
- aws_docdb_stop_cluster: Stop a running cluster
- aws_docdb_reboot_instance: Reboot a cluster instance
- aws_docdb_list_snapshots: List cluster snapshots
- aws_docdb_create_snapshot: Create a manual cluster snapshot
- aws_docdb_list_log_files: List available DB log files
- aws_docdb_download_log: Download DB log file content
- aws_docdb_describe_events: List operational events/alerts

## Methods

- `async def aws_docdb_list_clusters(self, limit: int=100, next_token: Optional[str]=None) -> Dict[str, Any]` — List DocumentDB clusters with pagination.
- `async def aws_docdb_get_cluster_details(self, cluster_identifier: str) -> Dict[str, Any]` — Get detailed information about a specific DocumentDB cluster.
- `async def aws_docdb_list_instances(self, cluster_identifier: str, limit: int=100, next_token: Optional[str]=None) -> Dict[str, Any]` — List DocumentDB instances belonging to a cluster.
- `async def aws_docdb_get_instance_details(self, instance_identifier: str) -> Dict[str, Any]` — Get detailed information about a specific DocumentDB instance.
- `async def aws_docdb_start_cluster(self, cluster_identifier: str) -> Dict[str, Any]` — Start a stopped DocumentDB cluster.
- `async def aws_docdb_stop_cluster(self, cluster_identifier: str) -> Dict[str, Any]` — Stop a running DocumentDB cluster.
- `async def aws_docdb_reboot_instance(self, instance_identifier: str, force_failover: bool=False) -> Dict[str, Any]` — Reboot a DocumentDB instance.
- `async def aws_docdb_list_snapshots(self, cluster_identifier: Optional[str]=None, snapshot_type: Optional[str]=None, limit: int=100, next_token: Optional[str]=None) -> Dict[str, Any]` — List DocumentDB cluster snapshots with optional filtering.
- `async def aws_docdb_create_snapshot(self, cluster_identifier: str, snapshot_identifier: str, tags: Optional[Dict[str, str]]=None) -> Dict[str, Any]` — Create a manual DocumentDB cluster snapshot.
- `async def aws_docdb_list_log_files(self, instance_identifier: str, filename_contains: Optional[str]=None, last_written_after: Optional[int]=None, limit: int=100) -> Dict[str, Any]` — List available DB log files for a DocumentDB instance.
- `async def aws_docdb_download_log(self, instance_identifier: str, log_file_name: str, marker: Optional[str]=None, number_of_lines: int=500) -> Dict[str, Any]` — Download a portion of a DocumentDB log file.
- `async def aws_docdb_describe_events(self, source_identifier: Optional[str]=None, source_type: str='db-cluster', duration_minutes: int=1440, event_categories: Optional[List[str]]=None, limit: int=100) -> Dict[str, Any]` — List DocumentDB operational events and alerts.
