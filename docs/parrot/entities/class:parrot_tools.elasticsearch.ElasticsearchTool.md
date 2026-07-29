---
type: Wiki Entity
title: ElasticsearchTool
id: class:parrot_tools.elasticsearch.ElasticsearchTool
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Tool for querying Elasticsearch/OpenSearch indices and analyzing logs.
relates_to:
- concept: class:parrot.tools.abstract.AbstractTool
  rel: extends
---

# ElasticsearchTool

Defined in [`parrot_tools.elasticsearch`](../summaries/mod:parrot_tools.elasticsearch.md).

```python
class ElasticsearchTool(AbstractTool)
```

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
