---
type: Wiki Summary
title: parrot.knowledge.graphindex.schema
id: mod:parrot.knowledge.graphindex.schema
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Core schema models for GraphIndex.
relates_to:
- concept: class:parrot.knowledge.graphindex.schema.BuildResult
  rel: defines
- concept: class:parrot.knowledge.graphindex.schema.EdgeKind
  rel: defines
- concept: class:parrot.knowledge.graphindex.schema.GraphProjectionReport
  rel: defines
- concept: class:parrot.knowledge.graphindex.schema.IngestResult
  rel: defines
- concept: class:parrot.knowledge.graphindex.schema.NodeKind
  rel: defines
- concept: class:parrot.knowledge.graphindex.schema.Provenance
  rel: defines
- concept: class:parrot.knowledge.graphindex.schema.SourceConfig
  rel: defines
- concept: class:parrot.knowledge.graphindex.schema.UniversalEdge
  rel: defines
- concept: class:parrot.knowledge.graphindex.schema.UniversalNode
  rel: defines
---

# `parrot.knowledge.graphindex.schema`

Core schema models for GraphIndex.

Defines the universal node/edge contract that all pipeline stages share:
``UniversalNode``, ``UniversalEdge``, ``Provenance``, ``NodeKind``,
``EdgeKind``, ``SourceConfig``, ``GraphProjectionReport``, ``BuildResult``,
and ``IngestResult``.

## Classes

- **`Provenance(str, Enum)`** — How a node or edge was created.
- **`NodeKind(str, Enum)`** — Semantic category of a graph node.
- **`EdgeKind(str, Enum)`** — Semantic category of a directed graph edge.
- **`UniversalNode(BaseModel)`** — A node in the GraphIndex knowledge graph.
- **`UniversalEdge(BaseModel)`** — A directed edge in the GraphIndex knowledge graph.
- **`SourceConfig(BaseModel)`** — Configuration describing what to index in a pipeline run.
- **`GraphProjectionReport(BaseModel)`** — Summary of a completed GraphIndex OKF projection run (FEAT-239).
- **`BuildResult(BaseModel)`** — Outcome of a full ``GraphIndexBuilder.build()`` run.
- **`IngestResult(BaseModel)`** — Outcome of an incremental ``GraphIndexBuilder.ingest_document()`` run.
