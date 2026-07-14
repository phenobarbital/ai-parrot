---
type: Wiki Summary
title: parrot_tools.scraping.flow_models
id: mod:parrot_tools.scraping.flow_models
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: ScrapingFlow DAG models — FlowNode, ScrapingFlow, FlowResult.
relates_to:
- concept: class:parrot_tools.scraping.flow_models.FlowNode
  rel: defines
- concept: class:parrot_tools.scraping.flow_models.FlowResult
  rel: defines
- concept: class:parrot_tools.scraping.flow_models.ScrapingFlow
  rel: defines
---

# `parrot_tools.scraping.flow_models`

ScrapingFlow DAG models — FlowNode, ScrapingFlow, FlowResult.

A :class:`ScrapingFlow` is a directed acyclic graph of :class:`FlowNode`s
where edges are data dependencies declared via each node's ``inputs`` map
(``{param: "node_id.field"}``) and each node carries a ``session`` label for
BrowserContext affinity (FEAT-222, Module 2).

The model validates the graph on construction (no duplicate ids, no dangling
references, no cycles) and exposes :meth:`ScrapingFlow.topological_order` for
the executor.

## Classes

- **`FlowNode(BaseModel)`** — A single stage in a :class:`ScrapingFlow` DAG.
- **`ScrapingFlow(BaseModel)`** — DAG of :class:`FlowNode`s with data-dependency edges and session affinity.
- **`FlowResult(BaseModel)`** — Aggregated result of a :class:`ScrapingFlow` execution.
