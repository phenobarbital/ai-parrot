---
type: Wiki Summary
title: parrot_tools.aws.documentdb
id: mod:parrot_tools.aws.documentdb
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: AWS DocumentDB Toolkit for AI-Parrot.
relates_to:
- concept: class:parrot_tools.aws.documentdb.CreateSnapshotInput
  rel: defines
- concept: class:parrot_tools.aws.documentdb.DescribeEventsInput
  rel: defines
- concept: class:parrot_tools.aws.documentdb.DocumentDBToolkit
  rel: defines
- concept: class:parrot_tools.aws.documentdb.DownloadLogInput
  rel: defines
- concept: class:parrot_tools.aws.documentdb.GetClusterDetailsInput
  rel: defines
- concept: class:parrot_tools.aws.documentdb.GetInstanceDetailsInput
  rel: defines
- concept: class:parrot_tools.aws.documentdb.ListClusterInstancesInput
  rel: defines
- concept: class:parrot_tools.aws.documentdb.ListClustersInput
  rel: defines
- concept: class:parrot_tools.aws.documentdb.ListLogFilesInput
  rel: defines
- concept: class:parrot_tools.aws.documentdb.ListSnapshotsInput
  rel: defines
- concept: class:parrot_tools.aws.documentdb.RebootInstanceInput
  rel: defines
- concept: class:parrot_tools.aws.documentdb.StartClusterInput
  rel: defines
- concept: class:parrot_tools.aws.documentdb.StopClusterInput
  rel: defines
- concept: mod:parrot.interfaces.aws
  rel: references
- concept: mod:parrot_tools.decorators
  rel: references
- concept: mod:parrot_tools.toolkit
  rel: references
---

# `parrot_tools.aws.documentdb`

AWS DocumentDB Toolkit for AI-Parrot.

Provides inspection and management of DocumentDB clusters, instances,
snapshots, logs, and events.

## Classes

- **`ListClustersInput(BaseModel)`** — Input for listing DocumentDB clusters.
- **`GetClusterDetailsInput(BaseModel)`** — Input for getting DocumentDB cluster details.
- **`ListClusterInstancesInput(BaseModel)`** — Input for listing instances in a DocumentDB cluster.
- **`GetInstanceDetailsInput(BaseModel)`** — Input for getting DocumentDB instance details.
- **`StartClusterInput(BaseModel)`** — Input for starting a DocumentDB cluster.
- **`StopClusterInput(BaseModel)`** — Input for stopping a DocumentDB cluster.
- **`RebootInstanceInput(BaseModel)`** — Input for rebooting a DocumentDB instance.
- **`ListSnapshotsInput(BaseModel)`** — Input for listing DocumentDB cluster snapshots.
- **`CreateSnapshotInput(BaseModel)`** — Input for creating a manual DocumentDB cluster snapshot.
- **`ListLogFilesInput(BaseModel)`** — Input for listing available DB log files.
- **`DownloadLogInput(BaseModel)`** — Input for downloading DocumentDB log file content.
- **`DescribeEventsInput(BaseModel)`** — Input for listing DocumentDB operational events.
- **`DocumentDBToolkit(AbstractToolkit)`** — Toolkit for managing AWS DocumentDB clusters, instances, and snapshots.
