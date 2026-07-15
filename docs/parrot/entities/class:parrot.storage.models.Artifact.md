---
type: Wiki Entity
title: Artifact
id: class:parrot.storage.models.Artifact
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Full artifact with definition payload.
---

# Artifact

Defined in [`parrot.storage.models`](../summaries/mod:parrot.storage.models.md).

```python
class Artifact(BaseModel)
```

Full artifact with definition payload.

The ``definition`` field holds the artifact data inline.  For CHART
artifacts the definition carries a :class:`~parrot.models.outputs.StructuredChartConfig`
dump (camelCase, ``data`` excluded).  For other artifact types it holds
the type-specific payload (canvas blocks, infographic response, …).
When the serialised definition exceeds 200 KB it is offloaded to S3 and
``definition_ref`` holds the S3 URI instead.

## Methods

- `def from_structured_config(cls, cfg: Any, artifact_type: 'ArtifactType', artifact_id: str, title: str, created_at: datetime, updated_at: datetime, **kwargs: Any) -> 'Artifact'` — Create an Artifact for any structured output type (chart / map / table).
- `def from_chart_config(cls, cfg: Any, artifact_id: str, title: str, created_at: datetime, updated_at: datetime, **kwargs: Any) -> 'Artifact'` — Create a CHART Artifact whose definition carries the converged config.
- `def as_chart_config(self) -> Any` — Parse ``definition`` as a :class:`~parrot.models.outputs.StructuredChartConfig`.
