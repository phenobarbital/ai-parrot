---
type: Wiki Summary
title: parrot_tools.troc.tool
id: mod:parrot_tools.troc.tool
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: TROCOperationsToolkit - KPI computation tools for TROC vending operations.
relates_to:
- concept: class:parrot_tools.troc.tool.TROCOperationsToolkit
  rel: defines
- concept: mod:parrot.tools
  rel: references
- concept: mod:parrot.tools.dataset_manager
  rel: references
- concept: mod:parrot.tools.dataset_manager.sources.table
  rel: references
---

# `parrot_tools.troc.tool`

TROCOperationsToolkit - KPI computation tools for TROC vending operations.

Provides specialized tools for computing operational KPIs across
TROC's kiosk fleet: burn rate, fill rate, LRW, KMR, merchandiser
workload, growth feasibility, and burn rate forecasting.

All tools accept a QuerySource-style filter dict and a group_by list,
delegating filtering logic to the toolkit rather than requiring the LLM
to generate Pandas code.

Usage:
    toolkit = TROCOperationsToolkit(dataset_manager=dm)
    tools = toolkit.get_tools()
    # Each async method becomes a ToolkitTool automatically.

YAML registration:
    toolkits:
      - name: troc_operations
        class: TROCOperationsToolkit
        params:
          dataset_manager: "{dataset_manager}"

## Classes

- **`TROCOperationsToolkit(AbstractToolkit)`** — TROC vending operations KPI toolkit.
