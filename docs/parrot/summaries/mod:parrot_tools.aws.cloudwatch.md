---
type: Wiki Summary
title: parrot_tools.aws.cloudwatch
id: mod:parrot_tools.aws.cloudwatch
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: AWS CloudWatch Toolkit for AI-Parrot.
relates_to:
- concept: class:parrot_tools.aws.cloudwatch.CloudWatchToolkit
  rel: defines
- concept: class:parrot_tools.aws.cloudwatch.DescribeAlarmsInput
  rel: defines
- concept: class:parrot_tools.aws.cloudwatch.GetLogEventsInput
  rel: defines
- concept: class:parrot_tools.aws.cloudwatch.GetMetricsInput
  rel: defines
- concept: class:parrot_tools.aws.cloudwatch.ListLogGroupsInput
  rel: defines
- concept: class:parrot_tools.aws.cloudwatch.ListLogStreamsInput
  rel: defines
- concept: class:parrot_tools.aws.cloudwatch.LogSummaryInput
  rel: defines
- concept: class:parrot_tools.aws.cloudwatch.PutMetricDataInput
  rel: defines
- concept: class:parrot_tools.aws.cloudwatch.QueryLogsInput
  rel: defines
- concept: mod:parrot.conf
  rel: references
- concept: mod:parrot.interfaces.aws
  rel: references
- concept: mod:parrot_tools.decorators
  rel: references
- concept: mod:parrot_tools.toolkit
  rel: references
---

# `parrot_tools.aws.cloudwatch`

AWS CloudWatch Toolkit for AI-Parrot.

Provides querying of CloudWatch logs, metrics, alarms, and custom metric publishing.

## Classes

- **`QueryLogsInput(BaseModel)`** — Input for CloudWatch Logs Insights query.
- **`GetMetricsInput(BaseModel)`** — Input for retrieving CloudWatch metric statistics.
- **`ListLogGroupsInput(BaseModel)`** — Input for listing CloudWatch log groups.
- **`ListLogStreamsInput(BaseModel)`** — Input for listing log streams in a log group.
- **`GetLogEventsInput(BaseModel)`** — Input for getting log events from a specific stream.
- **`PutMetricDataInput(BaseModel)`** — Input for publishing custom metric data.
- **`DescribeAlarmsInput(BaseModel)`** — Input for listing CloudWatch alarms.
- **`LogSummaryInput(BaseModel)`** — Input for getting summarized log events.
- **`CloudWatchToolkit(AbstractToolkit)`** — Toolkit for querying AWS CloudWatch logs and metrics.
