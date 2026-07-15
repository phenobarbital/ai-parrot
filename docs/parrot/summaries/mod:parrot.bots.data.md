---
type: Wiki Summary
title: parrot.bots.data
id: mod:parrot.bots.data
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: PandasAgent.
relates_to:
- concept: class:parrot.bots.data.DatasetResult
  rel: defines
- concept: class:parrot.bots.data.PandasAgent
  rel: defines
- concept: class:parrot.bots.data.PandasAgentResponse
  rel: defines
- concept: class:parrot.bots.data.PandasMetadata
  rel: defines
- concept: class:parrot.bots.data.PandasTable
  rel: defines
- concept: class:parrot.bots.data.SummaryStat
  rel: defines
- concept: mod:parrot.bots.agent
  rel: references
- concept: mod:parrot.bots.mixins.intent_router
  rel: references
- concept: mod:parrot.bots.prompts
  rel: references
- concept: mod:parrot.bots.prompts.domain_layers
  rel: references
- concept: mod:parrot.bots.prompts.layers
  rel: references
- concept: mod:parrot.conf
  rel: references
- concept: mod:parrot.memory.abstract
  rel: references
- concept: mod:parrot.models.outputs
  rel: references
- concept: mod:parrot.models.responses
  rel: references
- concept: mod:parrot.registry.capabilities.models
  rel: references
- concept: mod:parrot.tools
  rel: references
- concept: mod:parrot.tools.dataset_manager
  rel: references
- concept: mod:parrot.tools.dataset_manager.spatial.contracts
  rel: references
- concept: mod:parrot.tools.infographic_toolkit
  rel: references
- concept: mod:parrot.tools.json_tool
  rel: references
- concept: mod:parrot.tools.pythonpandas
  rel: references
- concept: mod:parrot_tools.prophetforecast
  rel: references
- concept: mod:parrot_tools.whatif
  rel: references
---

# `parrot.bots.data`

PandasAgent.
A specialized agent for data analysis using pandas DataFrames.

## Classes

- **`PandasTable(BaseModel)`** — Tabular data structure for PandasAgent responses.
- **`DatasetResult(BaseModel)`** — A single named dataset in a multi-dataset response.
- **`SummaryStat(BaseModel)`** — Single summary statistic for a DataFrame column.
- **`PandasMetadata(BaseModel)`** — Metadata information for PandasAgent responses.
- **`PandasAgentResponse(BaseModel)`** — Structured response for PandasAgent operations.
- **`PandasAgent(IntentRouterMixin, BasicAgent)`** — A specialized agent for data analysis using pandas DataFrames.
