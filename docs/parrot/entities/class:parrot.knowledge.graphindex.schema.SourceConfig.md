---
type: Wiki Entity
title: SourceConfig
id: class:parrot.knowledge.graphindex.schema.SourceConfig
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Configuration describing what to index in a pipeline run.
---

# SourceConfig

Defined in [`parrot.knowledge.graphindex.schema`](../summaries/mod:parrot.knowledge.graphindex.schema.md).

```python
class SourceConfig(BaseModel)
```

Configuration describing what to index in a pipeline run.

Args:
    code_paths: Filesystem directories/files to parse with tree-sitter.
    loader_sources: URIs (files, URLs) to process via ai-parrot-loaders.
    skill_paths: Directories/files containing SKILL.md definitions.
    ignore_file: Path to a ``.graphindexignore`` file (gitignore syntax).
    tenant_id: Tenant identifier — used for graph isolation.
