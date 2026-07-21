---
type: Wiki Entity
title: SpatialCompiler
id: class:parrot.tools.dataset_manager.spatial.compiler.SpatialCompiler
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Stateless spatial filter compiler and executor.
---

# SpatialCompiler

Defined in [`parrot.tools.dataset_manager.spatial.compiler`](../summaries/mod:parrot.tools.dataset_manager.spatial.compiler.md).

```python
class SpatialCompiler
```

Stateless spatial filter compiler and executor.

compile() is pure (I/O-free, syrupy-snapshotable).
execute() is async and performs DB/DataFrame I/O.

## Methods

- `def compile(self, spec: 'SpatialFilterSpec', profile: 'DatasetSpatialProfile', source: Any=None, cap: int=_DEFAULT_ENGINE_CAP) -> CompiledQuery` — Compile a spatial filter spec into a CompiledQuery.
- `async def execute(self, compiled: CompiledQuery, source: Any) -> Tuple[List[dict], int]` — Execute a compiled query against the given DataSource.
