---
type: Wiki Entity
title: ElasticsearchToolArgs
id: class:parrot_tools.elasticsearch.ElasticsearchToolArgs
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Arguments schema for Elasticsearch operations
relates_to:
- concept: class:parrot.tools.abstract.AbstractToolArgsSchema
  rel: extends
---

# ElasticsearchToolArgs

Defined in [`parrot_tools.elasticsearch`](../summaries/mod:parrot_tools.elasticsearch.md).

```python
class ElasticsearchToolArgs(AbstractToolArgsSchema)
```

Arguments schema for Elasticsearch operations

## Methods

- `def parse_time(cls, v)` — Parse time string to timestamp
- `def parse_end_time(cls, v)` — Parse end time string to timestamp
