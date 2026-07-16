---
type: Wiki Summary
title: parrot_tools.aws.rds
id: mod:parrot_tools.aws.rds
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: AWS RDS Toolkit for AI-Parrot.
relates_to:
- concept: class:parrot_tools.aws.rds.CreateSnapshotInput
  rel: defines
- concept: class:parrot_tools.aws.rds.DescribeEventsInput
  rel: defines
- concept: class:parrot_tools.aws.rds.DownloadLogFilteredInput
  rel: defines
- concept: class:parrot_tools.aws.rds.DownloadLogInput
  rel: defines
- concept: class:parrot_tools.aws.rds.GetInstanceDetailsInput
  rel: defines
- concept: class:parrot_tools.aws.rds.ListInstancesInput
  rel: defines
- concept: class:parrot_tools.aws.rds.ListLogFilesInput
  rel: defines
- concept: class:parrot_tools.aws.rds.ListSnapshotsInput
  rel: defines
- concept: class:parrot_tools.aws.rds.PerformanceInsightsInput
  rel: defines
- concept: class:parrot_tools.aws.rds.RDSToolkit
  rel: defines
- concept: class:parrot_tools.aws.rds.RebootInstanceInput
  rel: defines
- concept: class:parrot_tools.aws.rds.StartInstanceInput
  rel: defines
- concept: class:parrot_tools.aws.rds.StopInstanceInput
  rel: defines
- concept: mod:parrot.interfaces.aws
  rel: references
- concept: mod:parrot_tools.decorators
  rel: references
- concept: mod:parrot_tools.toolkit
  rel: references
---

# `parrot_tools.aws.rds`

AWS RDS Toolkit for AI-Parrot.

Provides inspection and management of RDS instances, snapshots,
logs, events, and Performance Insights.

## Classes

- **`ListInstancesInput(BaseModel)`** — Input for listing RDS instances.
- **`GetInstanceDetailsInput(BaseModel)`** — Input for getting RDS instance details.
- **`StartInstanceInput(BaseModel)`** — Input for starting an RDS instance.
- **`StopInstanceInput(BaseModel)`** — Input for stopping an RDS instance.
- **`RebootInstanceInput(BaseModel)`** — Input for rebooting an RDS instance.
- **`ListSnapshotsInput(BaseModel)`** — Input for listing RDS snapshots.
- **`CreateSnapshotInput(BaseModel)`** — Input for creating a manual DB snapshot.
- **`ListLogFilesInput(BaseModel)`** — Input for listing available DB log files.
- **`DownloadLogInput(BaseModel)`** — Input for downloading RDS log file content.
- **`DownloadLogFilteredInput(BaseModel)`** — Input for downloading and filtering RDS log file content by severity.
- **`DescribeEventsInput(BaseModel)`** — Input for listing RDS operational events.
- **`PerformanceInsightsInput(BaseModel)`** — Input for fetching Performance Insights metrics.
- **`RDSToolkit(AbstractToolkit)`** — Toolkit for managing AWS RDS instances, snapshots, logs, and diagnostics.
