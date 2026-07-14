---
type: Wiki Summary
title: parrot_tools.elasticsearch
id: mod:parrot_tools.elasticsearch
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Elasticsearch/OpenSearch Tool for AI-Parrot
relates_to:
- concept: class:parrot_tools.elasticsearch.ElasticsearchOperation
  rel: defines
- concept: class:parrot_tools.elasticsearch.ElasticsearchTool
  rel: defines
- concept: class:parrot_tools.elasticsearch.ElasticsearchToolArgs
  rel: defines
- concept: mod:parrot_tools.abstract
  rel: references
---

# `parrot_tools.elasticsearch`

Elasticsearch/OpenSearch Tool for AI-Parrot
Enables AI agents to query Elasticsearch indices, search logs, and extract metrics

## Classes

- **`ElasticsearchOperation(str, Enum)`** — Available Elasticsearch operations
- **`ElasticsearchToolArgs(AbstractToolArgsSchema)`** — Arguments schema for Elasticsearch operations
- **`ElasticsearchTool(AbstractTool)`** — Tool for querying Elasticsearch/OpenSearch indices and analyzing logs.
